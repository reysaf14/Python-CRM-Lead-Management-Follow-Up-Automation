"""Generate a candidate-bound SPDX inventory from a local Docker image."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PYTHON_INVENTORY = r'''
import hashlib
import importlib.metadata as metadata
import json

packages = []
for distribution in sorted(metadata.distributions(), key=lambda item: item.metadata['Name'].lower()):
    files = []
    for item in distribution.files or ():
        path = distribution.locate_file(item)
        if path.is_file():
            files.append((str(item).replace('\\', '/'), hashlib.sha256(path.read_bytes()).hexdigest()))
    canonical = ''.join(f'{name}\t{digest}\n' for name, digest in sorted(files))
    packages.append({
        'name': distribution.metadata['Name'],
        'version': distribution.version,
        'installedContentSha256': hashlib.sha256(canonical.encode()).hexdigest(),
        'fileCount': len(files),
    })
print(json.dumps(packages))
'''


def _run_docker(*arguments: str) -> str:
    result = subprocess.run(
        ["docker", *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _image_inspect(image: str) -> dict[str, Any]:
    payload = _run_docker("image", "inspect", image, "--format", "{{json .}}")
    return json.loads(payload)


def _runtime_inventory(image: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    python_json = _run_docker(
        "run",
        "--rm",
        "--read-only",
        "--tmpfs",
        "/tmp",
        "--entrypoint",
        "python",
        image,
        "-c",
        PYTHON_INVENTORY,
    )
    python_packages = json.loads(python_json)
    os_output = _run_docker(
        "run",
        "--rm",
        "--read-only",
        "--tmpfs",
        "/tmp",
        "--entrypoint",
        "dpkg-query",
        image,
        "-W",
        "-f=${Package}|${Version}\\n",
    )
    os_packages = []
    for line in os_output.splitlines():
        if not line.strip() or "|" not in line:
            continue
        name, version = line.split("|", 1)
        os_packages.append({"name": name, "version": version})
    return python_packages, os_packages


def _spdx_package(
    *,
    identifier: str,
    name: str,
    version: str,
    download_location: str,
    checksum: str | None = None,
    comment: str,
) -> dict[str, Any]:
    package: dict[str, Any] = {
        "SPDXID": identifier,
        "name": name,
        "versionInfo": version,
        "downloadLocation": download_location,
        "filesAnalyzed": False,
        "comment": comment,
    }
    if checksum:
        package["checksums"] = [{"algorithm": "SHA256", "checksumValue": checksum}]
    return package


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    image = _image_inspect(args.image)
    labels = image.get("Config", {}).get("Labels") or {}
    expected_manifest = manifest["manifestSha256"]
    actual_manifest = labels.get("org.opencontainers.image.source-manifest-sha256")
    if actual_manifest != expected_manifest:
        raise SystemExit(
            f"image manifest binding mismatch: expected {expected_manifest}, got {actual_manifest}"
        )
    expected_candidate = manifest["sourceCandidate"]
    actual_candidate = labels.get("org.opencontainers.image.source-candidate")
    if actual_candidate != expected_candidate:
        raise SystemExit(
            f"image candidate binding mismatch: expected {expected_candidate}, got {actual_candidate}"
        )

    digest = image.get("RepoDigests", [args.image])[0]
    image_id = image["Id"]
    python_packages, os_packages = _runtime_inventory(args.image)

    packages: list[dict[str, Any]] = []
    for index, package in enumerate(python_packages, start=1):
        name = package["name"]
        normalized = name.lower().replace("_", "-")
        packages.append(
            _spdx_package(
                identifier=f"SPDXRef-Python-{index}",
                name=name,
                version=package["version"],
                download_location=f"pkg:pypi/{normalized}@{package['version']}",
                checksum=package["installedContentSha256"],
                comment=(
                    "SHA-256 of the deterministic installed-file manifest for this Python "
                    "distribution; the distribution artifact hash remains a separate lock concern."
                ),
            )
        )
    for index, package in enumerate(os_packages, start=1):
        normalized = package["name"].lower()
        packages.append(
            _spdx_package(
                identifier=f"SPDXRef-Debian-{index}",
                name=package["name"],
                version=package["version"],
                download_location=f"pkg:deb/debian/{normalized}@{package['version']}",
                comment="Installed Debian base-image package inventory from the candidate image.",
            )
        )

    document = {
        "SPDXID": "SPDXRef-DOCUMENT",
        "spdxVersion": "SPDX-2.3",
        "name": args.image,
        "dataLicense": "CC0-1.0",
        "documentNamespace": f"urn:uuid:{hashlib.sha256(digest.encode()).hexdigest()}",
        "creationInfo": {
            "created": datetime.now(timezone.utc).isoformat(),
            "creators": ["Tool: generate_local_image_sbom.py"],
            "comment": (
                f"Image digest: {digest}; image ID: {image_id}; "
                f"source manifest SHA-256: {expected_manifest}; "
                f"source candidate: {expected_candidate}."
            ),
        },
        "packages": packages,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"image={digest}")
    print(f"manifest={expected_manifest}")
    print(f"python_packages={len(python_packages)}")
    print(f"debian_packages={len(os_packages)}")


if __name__ == "__main__":
    main()
