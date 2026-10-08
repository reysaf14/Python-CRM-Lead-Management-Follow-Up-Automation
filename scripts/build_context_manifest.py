"""Create the canonical hash manifest for Docker build inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


STATIC_FILES = (
    "Dockerfile",
    "alembic.ini",
    "pyproject.toml",
    "requirements.lock",
    "requirements.dev.lock",
)
SOURCE_DIRECTORIES = ("app", "migrations", "scripts")


def _included_files(project_root: Path) -> list[Path]:
    files = [project_root / relative for relative in STATIC_FILES]
    for directory in SOURCE_DIRECTORIES:
        files.extend(path for path in (project_root / directory).rglob("*") if path.is_file())
    return sorted(files, key=lambda path: path.relative_to(project_root).as_posix())


def build_manifest(project_root: Path) -> dict[str, object]:
    entries: list[dict[str, object]] = []
    for path in _included_files(project_root):
        relative = path.relative_to(project_root).as_posix()
        content = path.read_bytes()
        entries.append(
            {
                "path": relative,
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )

    canonical = "".join(f"{entry['path']}\t{entry['sha256']}\n" for entry in entries)
    return {
        "manifestVersion": "1.0",
        "hashAlgorithm": "SHA-256",
        "scope": "Docker build inputs copied by Dockerfile",
        "entries": entries,
        "manifestSha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    manifest = build_manifest(args.project_root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(manifest["manifestSha256"])


if __name__ == "__main__":
    main()
