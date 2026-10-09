"""Verify local source, Docker image, and SBOM identity without external services."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import sys

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from build_context_manifest import _require_committed_build_inputs


_CREDENTIAL_FILE_PATTERNS = (
    re.compile(r"(?:^|[-_])client[-_]?secret.*\.json$", re.IGNORECASE),
    re.compile(r"(?:^|[-_])service[-_]?account.*\.json$", re.IGNORECASE),
    re.compile(r"(?:^|[-_])oauth.*\.json$", re.IGNORECASE),
    re.compile(r"credential.*\.json$", re.IGNORECASE),
)
_CREDENTIAL_SUFFIXES = {".pem", ".key", ".crt", ".cer", ".p12", ".pfx"}


def _run_git(project_root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(project_root), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


def _canonical_manifest(manifest: dict[str, Any]) -> str:
    return (
        f"manifestVersion\t{manifest['manifestVersion']}\n"
        f"target\t{manifest['target']}\n"
        f"sourceCandidate\t{manifest['sourceCandidate']}\n"
        + "".join(
            f"{entry['path']}\t{entry['sha256']}\n" for entry in manifest["entries"]
        )
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _credential_artifacts(project_root: Path) -> list[str]:
    ignored_directories = {".git", ".venv", "venv", "__pycache__", ".pytest_cache"}
    found: list[str] = []
    for path in project_root.rglob("*"):
        if not path.is_file() or any(part in ignored_directories for part in path.parts):
            continue
        name = path.name
        if path.suffix.lower() in _CREDENTIAL_SUFFIXES or any(
            pattern.search(name) for pattern in _CREDENTIAL_FILE_PATTERNS
        ):
            found.append(path.relative_to(project_root).as_posix())
    return sorted(found)


def _ignore_rules(project_root: Path, filename: str) -> set[str]:
    path = project_root / filename
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def _image_inspect(image: str) -> dict[str, Any]:
    result = subprocess.run(
        ["docker", "image", "inspect", image, "--format", "{{json .}}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _verify_manifest(project_root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    head_result = _run_git(project_root, "rev-parse", "--verify", "HEAD")
    if head_result.returncode != 0:
        raise RuntimeError("unable to resolve committed HEAD")
    head = head_result.stdout.strip()
    expected_candidate = f"git:{head}"
    if manifest.get("sourceCandidate") != expected_candidate:
        raise RuntimeError(
            "manifest sourceCandidate does not match committed HEAD; rebuild the candidate"
        )

    expected_manifest_hash = manifest.get("manifestSha256")
    actual_manifest_hash = hashlib.sha256(
        _canonical_manifest(manifest).encode("utf-8")
    ).hexdigest()
    if expected_manifest_hash != actual_manifest_hash:
        raise RuntimeError("manifest canonical hash mismatch")

    mismatches: list[str] = []
    seen: set[str] = set()
    for entry in manifest.get("entries", []):
        relative = str(entry["path"])
        if relative in seen:
            mismatches.append(f"duplicate:{relative}")
            continue
        seen.add(relative)
        path = project_root / Path(relative)
        if not path.is_file():
            mismatches.append(f"missing:{relative}")
            continue
        if path.stat().st_size != entry["size"]:
            mismatches.append(f"size:{relative}")
        if _sha256(path) != entry["sha256"]:
            mismatches.append(f"sha256:{relative}")
    if mismatches:
        raise RuntimeError("manifest entry mismatch: " + ",".join(mismatches))

    _require_committed_build_inputs(project_root, "production")
    return {
        "source_candidate": expected_candidate,
        "manifest_sha256": actual_manifest_hash,
        "entry_count": len(seen),
    }


def _verify_image(
    *, image: str, manifest: dict[str, Any], sbom_path: Path | None
) -> dict[str, Any]:
    inspected = _image_inspect(image)
    labels = inspected.get("Config", {}).get("Labels") or {}
    expected_manifest = manifest["manifestSha256"]
    expected_candidate = manifest["sourceCandidate"]
    if labels.get("org.opencontainers.image.source-manifest-sha256") != expected_manifest:
        raise RuntimeError("image source-manifest label mismatch")
    if labels.get("org.opencontainers.image.source-candidate") != expected_candidate:
        raise RuntimeError("image source-candidate label mismatch")

    image_id = inspected.get("Id", "")
    repo_digests = inspected.get("RepoDigests") or []
    image_digest = repo_digests[0] if repo_digests else image_id
    result: dict[str, Any] = {
        "image": image,
        "image_digest": image_digest,
        "image_id": image_id,
        "labels_match": True,
    }
    if sbom_path is not None:
        sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
        comment = sbom.get("creationInfo", {}).get("comment", "")
        if expected_manifest not in comment or expected_candidate not in comment:
            raise RuntimeError("SBOM source binding mismatch")
        if image_digest not in comment and image_id not in comment:
            raise RuntimeError("SBOM image binding mismatch")
        result.update(
            {
                "sbom_path": sbom_path.as_posix(),
                "sbom_sha256": _sha256(sbom_path),
                "sbom_binding_match": True,
                "sbom_package_count": len(sbom.get("packages", [])),
            }
        )
    return result


def verify_candidate(
    *, project_root: Path, manifest_path: Path, image: str, sbom_path: Path | None
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_result = _verify_manifest(project_root, manifest)
    credential_artifacts = _credential_artifacts(project_root)
    if credential_artifacts:
        raise RuntimeError("credential artifact found in workspace")
    required_patterns = (
        "**/client_secret*.json",
        "**/service_account*.json",
        "**/*credential*.json",
    )
    ignore_result = {
        "gitignore_patterns_present": all(
            pattern in _ignore_rules(project_root, ".gitignore") for pattern in required_patterns
        ),
        "dockerignore_patterns_present": all(
            pattern in _ignore_rules(project_root, ".dockerignore") for pattern in required_patterns
        ),
    }
    if not all(ignore_result.values()):
        raise RuntimeError("credential ignore coverage is incomplete")
    image_result = _verify_image(image=image, manifest=manifest, sbom_path=sbom_path)
    return {
        "status": "PASS_WITH_LIMITATIONS",
        "evidence_type": "implementer-generated-local-verification",
        "external_attestation": False,
        "manifest": manifest_result,
        "credential_artifacts": {"count": 0, "paths": []},
        "ignore_coverage": ignore_result,
        "image": image_result,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--sbom", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = verify_candidate(
        project_root=args.project_root.resolve(),
        manifest_path=args.manifest.resolve(),
        image=args.image,
        sbom_path=args.sbom.resolve() if args.sbom else None,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()