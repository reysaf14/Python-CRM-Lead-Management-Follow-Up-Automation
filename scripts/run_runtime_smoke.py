"""Run a disposable mock Compose runtime smoke and emit sanitized evidence."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=check, capture_output=True, text=True)


def _request(url: str, *, token: str | None = None) -> tuple[int, str]:
    request = urllib.request.Request(url)
    if token is not None:
        request.add_header("X-Operator-Token", token)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read(512).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read(512).decode("utf-8", errors="replace")


def _wait_for(url: str, *, expected_status: int, token: str | None = None) -> tuple[int, str]:
    last_status = 0
    last_body = ""
    for _ in range(30):
        last_status, last_body = _request(url, token=token)
        if last_status == expected_status:
            return last_status, last_body
        time.sleep(2)
    return last_status, last_body


def _compose_base(project_root: Path, project_name: str, env_path: Path, override_path: Path) -> list[str]:
    return [
        "docker",
        "compose",
        "--project-name",
        project_name,
        "--env-file",
        str(env_path),
        "--file",
        str(project_root / "docker-compose.yml"),
        "--file",
        str(override_path),
    ]


def _safe_logs(compose: list[str], secret_values: tuple[str, ...]) -> dict[str, Any]:
    result = _run([*compose, "logs", "--no-color"], check=False)
    raw = result.stdout + result.stderr
    markers = (
        *secret_values,
        "GMAIL_OAUTH_REFRESH_TOKEN",
        "GMAIL_OAUTH_CLIENT_SECRET",
        "LLM_API_KEY",
        "Authorization: Bearer",
    )
    return {
        "command_succeeded": result.returncode == 0,
        "line_count": len(raw.splitlines()),
        "secret_markers_found": any(marker and marker in raw for marker in markers),
        "raw_logs_persisted": False,
    }


def run_smoke(
    *, project_root: Path, project_name: str, image: str, manifest_sha256: str, candidate: str
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="crm-runtime-smoke-") as temporary_directory:
        temporary = Path(temporary_directory)
        env_path = temporary / "runtime.env"
        override_path = temporary / "compose.override.yml"
        token = "synthetic-runtime-operator-token"
        password = "synthetic-runtime-db-password"
        env_path.write_text(
            "\n".join(
                (
                    "APP_ENV=local",
                    "SERVICE_ROLE=application",
                    f"POSTGRES_PASSWORD={password}",
                    "API_BASE_URL=http://api:8000",
                    f"OPERATOR_ACCESS_TOKEN={token}",
                    f"SOURCE_MANIFEST_SHA256={manifest_sha256}",
                    f"SOURCE_CANDIDATE_ID={candidate}",
                    "GMAIL_TRANSPORT=mock",
                    "GMAIL_LABEL_NAME=Sales Leads",
                    "GMAIL_POLL_INTERVAL_SECONDS=60",
                    "LLM_TRANSPORT=mock",
                    "LLM_PROVIDER=mock",
                    "LLM_MODEL=mock-model",
                    "LLM_MAX_INPUT_CHARS=320",
                    "LLM_TIMEOUT_SECONDS=5",
                    "LLM_RETRY_MAX=1",
                    "FOLLOW_UP_SCAN_INTERVAL_SECONDS=60",
                    "LOG_LEVEL=info",
                    "OPERATOR_ACCESS_MODE=private-host-only",
                )
            )
            + "\n",
            encoding="utf-8",
        )
        override_path.write_text(
            "services:\n"
            + "  api:\n"
            + f"    image: {image}\n"
            + "    build: null\n"
            + '    ports: ["127.0.0.1:18000:8000"]\n'
            + "  worker:\n"
            + f"    image: {image}\n"
            + "    build: null\n"
            + "  dashboard:\n"
            + f"    image: {image}\n"
            + "    build: null\n"
            + '    ports: ["127.0.0.1:18501:8501"]\n',
            encoding="utf-8",
        )
        compose = _compose_base(project_root, project_name, env_path, override_path)
        result: dict[str, Any] = {
            "status": "PASS_WITH_LIMITATIONS",
            "evidence_type": "implementer-generated-disposable-runtime-smoke",
            "external_attestation": False,
            "stack_cleaned_up": False,
        }
        try:
            if _run([*compose, "up", "-d", "postgres"]).returncode != 0:
                raise RuntimeError("postgres startup failed")
            if _run([*compose, "run", "--rm", "api", "alembic", "upgrade", "head"]).returncode != 0:
                raise RuntimeError("migration failed")
            if _run([*compose, "up", "-d", "api", "worker", "dashboard"]).returncode != 0:
                raise RuntimeError("application startup failed")

            health_status, _ = _wait_for("http://127.0.0.1:18000/health", expected_status=200)
            ready_status, _ = _wait_for("http://127.0.0.1:18000/ready", expected_status=200)
            unauth_status, _ = _wait_for(
                "http://127.0.0.1:18000/api/v1/dashboard/summary", expected_status=401
            )
            auth_status, _ = _wait_for(
                "http://127.0.0.1:18000/api/v1/dashboard/summary",
                expected_status=200,
                token=token,
            )
            dashboard_status, dashboard_body = _wait_for(
                "http://127.0.0.1:18501/", expected_status=200
            )
            worker_id = _run([*compose, "ps", "-q", "worker"]).stdout.strip()
            worker_status = "unknown"
            if worker_id:
                worker_status = _run(
                    ["docker", "inspect", "--format", "{{.State.Status}}", worker_id]
                ).stdout.strip()
            result["runtime"] = {
                "api_health_status": health_status,
                "api_ready_status": ready_status,
                "api_unauthenticated_status": unauth_status,
                "api_authenticated_status": auth_status,
                "dashboard_http_status": dashboard_status,
                "dashboard_streamlit_marker": "streamlit" in dashboard_body.lower(),
                "worker_state": worker_status,
            }
            result["logs"] = _safe_logs(compose, (token, password))
            if any(
                (
                    health_status != 200,
                    ready_status != 200,
                    unauth_status != 401,
                    auth_status != 200,
                    dashboard_status != 200,
                    "streamlit" not in dashboard_body.lower(),
                    worker_status != "running",
                    result["logs"]["secret_markers_found"],
                )
            ):
                result["status"] = "FAIL"
        finally:
            _run([*compose, "down", "--volumes", "--remove-orphans"], check=False)
            result["stack_cleaned_up"] = True
        return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--project-name", default="crm-engineer-runtime-smoke-v7")
    parser.add_argument("--image", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run_smoke(
        project_root=args.project_root.resolve(),
        project_name=args.project_name,
        image=args.image,
        manifest_sha256=args.manifest_sha256,
        candidate=args.candidate,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    if result["status"] == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()