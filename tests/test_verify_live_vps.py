"""Read-only live verifier never changes services, credentials, or Docker."""
from __future__ import annotations

import importlib.util
import io
from contextlib import redirect_stdout
from pathlib import Path
import sqlite3
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent


def load_module():
    spec = importlib.util.spec_from_file_location(
        "mt_panel_verify_live", ROOT / "scripts" / "verify-live-vps.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_version_and_unauthenticated_routes(monkeypatch):
    m = load_module()
    routes = {
        (8086, "/api/health"): (200, {"ok": True, "service": "mt-panel", "version": "0.3.2-dev"}),
        (8788, "/health"): (200, {"ok": True, "service": "mt-panel-agent", "version": "0.1.1"}),
        (8086, "/api/auth/me"): (401, {"detail": "Please sign in"}),
        (8086, "/api/catalog/servers"): (401, {"detail": "Please sign in"}),
        (8086, "/api/server/overview"): (401, {"detail": "Please sign in"}),
        (8086, "/api/monitoring/overview"): (401, {"detail": "Please sign in"}),
        (8086, "/api/deployments/readiness"): (401, {"detail": "Please sign in"}),
        (8086, "/api/settings/security"): (401, {"detail": "Please sign in"}),
    }
    monkeypatch.setattr(m, "get_local", lambda p, u: routes[p, u])
    with redirect_stdout(io.StringIO()):
        assert m.check_http("0.3.2-dev") == []
        errors = m.check_http("0.3.3-dev")
    assert len(errors) == 1
    assert "not promoted" in errors[0]
    routes[(8086, "/api/catalog/servers")] = (200, {"data": []})
    with redirect_stdout(io.StringIO()):
        errors = m.check_http("0.3.2-dev")
    assert any("expected 401" in error for error in errors)


def test_sqlite_existing_schema_and_secret_never_printed(tmp_path):
    m = load_module()
    db_file = tmp_path / "panel.db"
    with sqlite3.connect(db_file) as db:
        for name, columns in m.TABLES.items():
            names = ",".join(f"{column} TEXT" for column in sorted(columns))
            db.execute(f"CREATE TABLE {name} ({names})")
        db.execute("INSERT INTO users(username,password_hash) VALUES(?,?)",
                   ("admin", "DO_NOT_PRINT_THIS_HASH"))
    stream = io.StringIO()
    with redirect_stdout(stream):
        assert m.check_database(db_file) == []
    assert "DO_NOT_PRINT_THIS_HASH" not in stream.getvalue()
    with sqlite3.connect(db_file) as db:
        db.execute("DROP TABLE host_snapshots")
    with redirect_stdout(io.StringIO()):
        result = m.check_database(db_file)
    assert any("host_snapshots" in problem for problem in result)
    assert not m.check_database(tmp_path / "not-there.db") == []


def test_tailscale_route_requires_tailnet_only_and_specific_backend(monkeypatch):
    m = load_module()
    correct = (
        "|-- tcp://node.tailnet.ts.net:5901 (tailnet only)\n"
        "https://node.tailnet.ts.net (tailnet only)\n"
        "|-- / proxy http://127.0.0.1:8080\n"
        "\nhttps://node.tailnet.ts.net:8443 (tailnet only)\n"
        "|-- / proxy http://127.0.0.1:8086\n"
    )
    monkeypatch.setattr(m.subprocess, "run",
                        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=correct))
    with redirect_stdout(io.StringIO()):
        assert m.check_tailscale() == []
    public = correct.replace(
        "https://node.tailnet.ts.net:8443 (tailnet only)",
        "https://node.tailnet.ts.net:8443 (public)"
    )
    monkeypatch.setattr(m.subprocess, "run",
                        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=public))
    assert m.check_tailscale()
    wrong_backend = correct.replace("127.0.0.1:8086", "127.0.0.1:8080")
    monkeypatch.setattr(m.subprocess, "run",
                        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=wrong_backend))
    assert m.check_tailscale()


def test_revision_marker_is_safe_and_exact(tmp_path):
    m = load_module()
    with redirect_stdout(io.StringIO()):
        assert m.check_revision(tmp_path) == []
    marker = tmp_path / ".staged-commit"
    marker.write_text("1" * 40 + "\n")
    with redirect_stdout(io.StringIO()):
        assert m.check_revision(tmp_path) == []
    marker.write_text("../../../etc/passwd")
    assert m.check_revision(tmp_path)


def test_verifier_uses_localhost_and_read_only_pragmas():
    source = (ROOT / "scripts" / "verify-live-vps.py").read_text()
    assert 'HTTPConnection("127.0.0.1"' in source
    assert 'mode=ro' in source
    assert "PRAGMA query_only=ON" in source
    assert '["tailscale", "serve", "status"]' in source
    for unsafe in ("docker run", "docker rm", "docker compose", "systemctl restart",
                   "systemctl stop", "tailscale serve reset", "tailscale funnel"):
        assert unsafe not in source
