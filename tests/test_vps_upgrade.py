"""Offline tests for read-only installed status and staged-only VPS upgrades."""
from __future__ import annotations

import importlib.util
import io
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
import subprocess

ROOT = Path(__file__).resolve().parent.parent


def load_status():
    path = ROOT / "scripts" / "vps-status.py"
    spec = importlib.util.spec_from_file_location("mtpanel_vps_status", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def fake_run(*args):
    if args[:2] == ("systemctl", "is-active"):
        return SimpleNamespace(returncode=0, stdout="")
    if args[:3] == ("systemctl", "show", "-p"):
        service = args[-1]
        user = "mtpanel-agent" if service == "mt-panel-agent.service" else "mtpanel"
        return SimpleNamespace(returncode=0, stdout=user + "\n")
    if args[:2] == ("ss", "-H"):
        return SimpleNamespace(returncode=0, stdout=(
            "LISTEN 0 2048 127.0.0.1:8086 0.0.0.0:*\n"
            "LISTEN 0 2048 127.0.0.1:8788 0.0.0.0:*\n"
        ))
    raise AssertionError("Unexpected subprocess command")


def test_status_is_read_only_and_redacts_agent_token(tmp_path):
    status = load_status()
    status.ENV_PATH = tmp_path / "mt-panel.env"
    status.ENV_PATH.write_text(
        "AGENT_TOKEN=VERY_PRIVATE_AGENT_SECRET\n"
        "PANEL_PUBLIC_ORIGIN=https://node.tailnet.ts.net:8443\n"
        "PANEL_COOKIE_SECURE=true\n"
    )
    status.run = fake_run
    output = io.StringIO()
    with redirect_stdout(output):
        result = status.inspect()
    assert result == 0
    assert "PASS: Tailscale HTTPS origin" in output.getvalue()
    assert "VERY_PRIVATE_AGENT_SECRET" not in output.getvalue()


def test_status_fails_nonloopback_listener(tmp_path):
    status = load_status()
    status.ENV_PATH = tmp_path / "missing"
    def exposed(*args):
        result = fake_run(*args)
        if args[:2] == ("ss", "-H"):
            result.stdout = result.stdout.replace("127.0.0.1:8086", "0.0.0.0:8086")
        return result
    status.run = exposed
    with redirect_stdout(io.StringIO()):
        assert status.inspect() == 1


def test_vps_stage_script_has_no_activation_or_docker_mutations():
    script = ROOT / "scripts" / "upgrade-vps.sh"
    subprocess.run(["bash", "-n", str(script)], check=True)
    result = subprocess.run(["bash", str(script), "--help"],
                            capture_output=True, text=True, check=True)
    assert "--stage" in result.stdout
    source = script.read_text()
    assert "git -C \"$SRC\" archive --format=tar HEAD" in source
    assert "git -C \"$SRC\" diff --quiet HEAD" in source
    assert "requirements-dev.txt" in source
    assert "/opt/mt-panel-stage." in source
    for prohibited in [
        "systemctl restart", "systemctl start", "systemctl stop",
        "systemctl enable", "systemctl disable",
        "docker run", "docker rm", "docker compose up",
        "tailscale serve reset", "tailscale funnel --bg",
    ]:
        assert prohibited not in source


def test_staging_preserves_existing_candidates():
    # This is a static gate: the live operator --stage path must never
    # delete an older, successfully tested candidate to make room.
    src = (ROOT / "scripts" / "upgrade-vps.sh").read_text()
    assert "existing_stages=" in src
    assert 'if [[ "$existing_stages" -ge 5 ]]' in src
    assert 'mktemp -d /opt/mt-panel-stage.XXXXXXXX' in src
    assert 'rm -rf -- "$stage"' in src  # cleanup only of *this* failed build
    assert "rm -rf /opt/mt-panel-stage" not in src
    assert "An existing MT Panel staged upgrade is present" not in src
