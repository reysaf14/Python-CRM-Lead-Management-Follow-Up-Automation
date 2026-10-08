"""Create a candidate-bound canonical manifest for Docker build inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


STATIC_FILES_BY_TARGET = {
    "production": (
        "Dockerfile",
        ".dockerignore",
        "alembic.ini",
        "pyproject.toml",
        "requirements.lock",
    ),
    "test": (
        "Dockerfile",
        ".dockerignore",
        "alembic.ini",
        "pyproject.toml",
        "requirements.lock",
        "requirements.dev.lock",
    ),
}
COPIED_SOURCE_DIRECTORIES = ("app", "migrations")


def _dockerignore_rules(project_root: Path) -> tuple[str, ...]:
    """Return the non-comment rules that control the effective Docker context."""
    lines = (project_root / ".dockerignore").read_text(encoding="utf-8").splitlines()
    return tuple(line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#"))


def _is_docker_ignored(relative: Path, rules: tuple[str, ...]) -> bool:
    """Match the supported Dockerignore rules used by the copied source directories.

    The project intentionally has no negated rules. A new negated rule fails closed until
    this selector is updated, rather than silently producing an inaccurate manifest.
    """
    path_parts = relative.parts
    for rule in rules:
        if rule.startswith("!"):
            raise ValueError(f"unsupported negated .dockerignore rule: {rule}")
        if rule.endswith("/"):
            directory_name = rule.rstrip("/").split("/")[-1]
            if directory_name in path_parts[:-1]:
                return True
            continue
        if rule.startswith("**/"):
            candidate_rule = rule.removeprefix("**/")
            if relative.match(candidate_rule) or any(
                part.startswith(candidate_rule.rstrip("*")) for part in path_parts
            ):
                return True
            continue
        if "/" not in rule:
            if relative.match(rule) or relative.name.endswith(rule.removeprefix("*")):
                return True
            continue
        if relative.match(rule):
            return True
    return False


def _included_files(project_root: Path, target: str) -> list[Path]:
    files = [project_root / relative for relative in STATIC_FILES_BY_TARGET[target]]
    rules = _dockerignore_rules(project_root)
    for directory in COPIED_SOURCE_DIRECTORIES:
        for path in (project_root / directory).rglob("*"):
            if not path.is_file():
                continue
            if not _is_docker_ignored(path.relative_to(project_root), rules):
                files.append(path)
    return sorted(files, key=lambda path: path.relative_to(project_root).as_posix())


def _run_git(project_root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(project_root), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


def _require_committed_build_inputs(project_root: Path, target: str) -> str:
    """Require every file that can affect the selected image to equal committed HEAD."""
    pathspecs = [*STATIC_FILES_BY_TARGET[target], *COPIED_SOURCE_DIRECTORIES]
    for arguments, description in (
        (("diff", "--quiet", "--", *pathspecs), "unstaged changes"),
        (("diff", "--cached", "--quiet", "--", *pathspecs), "staged changes"),
    ):
        result = _run_git(project_root, *arguments)
        if result.returncode != 0:
            raise SystemExit(f"refusing manifest: {description} affect the {target} Docker inputs")

    tracked = _run_git(project_root, "ls-files", "--error-unmatch", "--", *pathspecs)
    if tracked.returncode != 0:
        raise SystemExit(f"refusing manifest: untracked or missing {target} Docker input")

    untracked = _run_git(
        project_root,
        "ls-files",
        "--others",
        "--exclude-standard",
        "--",
        *COPIED_SOURCE_DIRECTORIES,
    )
    if untracked.stdout.strip():
        raise SystemExit(f"refusing manifest: untracked {target} Docker source exists")

    revision = _run_git(project_root, "rev-parse", "--verify", "HEAD")
    if revision.returncode != 0:
        raise SystemExit("refusing manifest: unable to resolve committed Git HEAD")
    return revision.stdout.strip()


def build_manifest(project_root: Path, *, target: str, source_revision: str) -> dict[str, object]:
    entries: list[dict[str, object]] = []
    for path in _included_files(project_root, target):
        relative = path.relative_to(project_root).as_posix()
        content = path.read_bytes()
        entries.append(
            {
                "path": relative,
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )

    candidate_id = f"git:{source_revision}"
    canonical = (
        f"manifestVersion\t2.0\n"
        f"target\t{target}\n"
        f"sourceCandidate\t{candidate_id}\n"
        + "".join(f"{entry['path']}\t{entry['sha256']}\n" for entry in entries)
    )
    return {
        "manifestVersion": "2.0",
        "hashAlgorithm": "SHA-256",
        "target": target,
        "scope": (
            f"Effective Docker {target} target inputs selected by Dockerfile after "
            ".dockerignore rules"
        ),
        "sourceCandidate": candidate_id,
        "contextControlFiles": ["Dockerfile", ".dockerignore"],
        "dockerignoreRules": list(_dockerignore_rules(project_root)),
        "entries": entries,
        "manifestSha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--target", choices=tuple(STATIC_FILES_BY_TARGET), default="production")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    source_revision = _require_committed_build_inputs(project_root, args.target)
    manifest = build_manifest(project_root, target=args.target, source_revision=source_revision)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(manifest["manifestSha256"])


if __name__ == "__main__":
    main()
