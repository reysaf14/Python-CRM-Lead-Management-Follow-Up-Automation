from __future__ import annotations

import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[2]


def _load_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / "scripts" / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_canonicalization_is_stable() -> None:
    module = _load_script("candidate_evidence", "verify_candidate_evidence.py")
    manifest = {
        "manifestVersion": "2.0",
        "target": "production",
        "sourceCandidate": "git:" + "a" * 40,
        "entries": [{"path": "Dockerfile", "sha256": "b" * 64}],
    }
    assert module._canonical_manifest(manifest) == (
        "manifestVersion\t2.0\n"
        "target\tproduction\n"
        "sourceCandidate\tgit:" + "a" * 40 + "\n"
        "Dockerfile\t" + "b" * 64 + "\n"
    )


def test_credential_filename_detection_is_fail_closed() -> None:
    module = _load_script("candidate_evidence_detection", "verify_candidate_evidence.py")
    assert any(pattern.search("client_secret.json") for pattern in module._CREDENTIAL_FILE_PATTERNS)
    assert any(pattern.search("oauth-client.json") for pattern in module._CREDENTIAL_FILE_PATTERNS)
    assert ".p12" in module._CREDENTIAL_SUFFIXES

def test_runtime_smoke_fails_when_log_collection_fails() -> None:
    module = _load_script("runtime_smoke", "run_runtime_smoke.py")
    runtime = {
        "api_health_status": 200,
        "api_ready_status": 200,
        "api_unauthenticated_status": 401,
        "api_authenticated_status": 200,
        "dashboard_http_status": 200,
        "dashboard_streamlit_marker": True,
        "worker_state": "running",
    }
    logs = {
        "command_succeeded": False,
        "secret_markers_found": False,
    }
    assert module._runtime_checks_failed(runtime, logs)