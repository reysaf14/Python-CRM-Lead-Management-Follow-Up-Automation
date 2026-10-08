"""Regression tests for candidate-bound Docker input manifests."""

from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "build_context_manifest.py"
SPEC = importlib.util.spec_from_file_location("build_context_manifest", SCRIPT_PATH)
assert SPEC and SPEC.loader
MANIFEST_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MANIFEST_MODULE)


def _create_project(root: Path) -> None:
    for name in (
        "Dockerfile",
        ".dockerignore",
        "alembic.ini",
        "pyproject.toml",
        "requirements.lock",
        "requirements.dev.lock",
        "app/service.py",
        "app/__pycache__/service.cpython-311.pyc",
        "migrations/env.py",
        "migrations/script.py.mako",
        "scripts/maintenance.py",
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture\n", encoding="utf-8")
    (root / ".dockerignore").write_text("__pycache__/\n*.py[cod]\n", encoding="utf-8")


def test_production_manifest_matches_effective_copy_scope(tmp_path: Path) -> None:
    _create_project(tmp_path)

    paths = [
        path.relative_to(tmp_path).as_posix()
        for path in MANIFEST_MODULE._included_files(tmp_path, "production")
    ]
    manifest = MANIFEST_MODULE.build_manifest(
        tmp_path,
        target="production",
        source_revision="a" * 40,
    )

    assert ".dockerignore" in paths
    assert "app/service.py" in paths
    assert "migrations/script.py.mako" in paths
    assert "app/__pycache__/service.cpython-311.pyc" not in paths
    assert "requirements.dev.lock" not in paths
    assert "scripts/maintenance.py" not in paths
    assert manifest["sourceCandidate"] == f"git:{'a' * 40}"
    assert manifest["contextControlFiles"] == ["Dockerfile", ".dockerignore"]


def test_test_target_includes_only_its_additional_dependency_lock(tmp_path: Path) -> None:
    _create_project(tmp_path)

    paths = [
        path.relative_to(tmp_path).as_posix()
        for path in MANIFEST_MODULE._included_files(tmp_path, "test")
    ]

    assert "requirements.lock" in paths
    assert "requirements.dev.lock" in paths
