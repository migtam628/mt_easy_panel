"""No live service actions: test promotion preflight and SQLite rollback helpers."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sqlite3
import subprocess

import pytest

ROOT = Path(__file__).resolve().parent.parent


def load_module():
    path = ROOT / "scripts" / "promote-vps.py"
    spec = importlib.util.spec_from_file_location("mtpanel_promote", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_promotion_cli_requires_explicit_mode_and_confirmation():
    script = ROOT / "scripts" / "promote-vps.py"
    help_out = subprocess.run(["python3", str(script), "--help"],
                              text=True, capture_output=True, check=True)
    assert "--check" in help_out.stdout
    assert "--activate" in help_out.stdout
    assert "--rollback" in help_out.stdout
    assert "--confirm" in help_out.stdout
    # No stage path or confirmation: fail before touching services.
    output = subprocess.run(["python3", str(script), "--activate"],
                            text=True, capture_output=True)
    assert output.returncode != 0


def test_staged_release_rejects_symlink_and_missing_commit(tmp_path, monkeypatch):
    m = load_module()
    stage = tmp_path / "mt-panel-stage.abcd1234"
    stage.mkdir()
    for rel in ("panel/api.py", "agent/api.py", "requirements.txt",
                ".venv/bin/python", ".staged-commit"):
        f = stage / rel
        f.parent.mkdir(exist_ok=True, parents=True)
        f.write_text("stub" if rel != ".staged-commit" else "a" * 40)
    monkeypatch.setattr(m, "directory",
                        lambda path, root, pattern: path if path.is_dir() and not path.is_symlink()
                        else (_ for _ in ()).throw(m.PromotionError("unsafe path")))
    assert m.stage_check(stage) == "a" * 40
    (stage / ".staged-commit").write_text("invalid")
    with pytest.raises(m.PromotionError):
        m.stage_check(stage)
    alias = tmp_path / "mt-panel-stage.alias1234"
    alias.symlink_to(stage, target_is_directory=True)
    with pytest.raises(m.PromotionError):
        m.stage_check(alias)


def test_sqlite_snapshot_and_recovery(tmp_path, monkeypatch):
    m = load_module()
    database = tmp_path / "panel.db"
    monkeypatch.setattr(m, "DATA", database)
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE admin (name TEXT)")
        db.execute("INSERT INTO admin VALUES ('existing-owner')")
    original_mode = os.stat(database).st_mode
    backup = tmp_path / "backup.db"
    m.sqlite_backup(backup)
    assert backup.stat().st_mode & 0o077 == 0
    with sqlite3.connect(database) as db:
        db.execute("DELETE FROM admin")
        db.execute("INSERT INTO admin VALUES ('changed-owner')")
    m.sqlite_restore(backup)
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT name FROM admin").fetchall() == [("existing-owner",)]
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_promotion_only_controls_mtpanel_services_and_never_tailscale():
    src = (ROOT / "scripts" / "promote-vps.py").read_text()
    for forbidden in ["docker run", "docker rm", "docker compose",
                      "tailscale serve reset", "tailscale funnel",
                      "systemctl restart docker", "systemctl stop docker",
                      "systemctl stop caddy", "systemctl restart caddy"]:
        assert forbidden not in src
    assert "mt-panel-agent.service" in src
    assert "mt-panel.service" in src
    assert "os.rename(stage, INSTALL)" in src
    assert "sqlite_backup(backup / \"panel.db\")" in src
    assert "os.replace(tmp, DATA)" in src
    assert "PANEL_COOKIE_SECURE" in src
    assert "ACTIVATE_MT_PANEL" in src
    assert "ROLLBACK_MT_PANEL" in src
