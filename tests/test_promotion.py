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


def test_manual_rollback_does_not_require_current_services_healthy(tmp_path, monkeypatch):
    m = load_module()
    install = tmp_path / "mt-panel"
    backup_root = tmp_path / "backups"
    backup = backup_root / "mt-panel-backup.abcdef012345"
    backup_root.mkdir()
    backup.mkdir()
    install.mkdir()
    (install / "version").write_text("new")
    (backup / "code").mkdir()
    (backup / "code" / "version").write_text("old")
    (backup / "ready").write_text("ready")
    database = tmp_path / "panel.db"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE state (value TEXT)")
        db.execute("INSERT INTO state VALUES ('new')")
    snapshot = backup / "panel.db"
    with sqlite3.connect(snapshot) as db:
        db.execute("CREATE TABLE state (value TEXT)")
        db.execute("INSERT INTO state VALUES ('old')")
    private_config = tmp_path / "mt-panel.env"
    private_config.write_text("secret=value\n")

    monkeypatch.setattr(m, "INSTALL", install)
    monkeypatch.setattr(m, "DATA", database)
    monkeypatch.setattr(m, "ENV", private_config)
    monkeypatch.setattr(m, "BACKUPS", backup_root)
    monkeypatch.setattr(m, "directory", lambda *args: backup)
    monkeypatch.setattr(m, "command", lambda *args, **kwargs:
                        "/etc/systemd/system/" + args[-1])
    monkeypatch.setattr(m, "stop_mtpanel", lambda: None)
    monkeypatch.setattr(m, "start_mtpanel", lambda: None)
    monkeypatch.setattr(m, "stage_smoke", lambda: None)
    monkeypatch.setattr(m, "verify_services", lambda: None)

    m.rollback(backup)
    assert (install / "version").read_text() == "old"
    assert (backup / "replaced-current" / "version").read_text() == "new"
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT value FROM state").fetchone() == ("old",)
    with sqlite3.connect(backup / "pre-rollback.db") as db:
        assert db.execute("SELECT value FROM state").fetchone() == ("new",)


def test_promotion_expected_commit_requires_exact_sha():
    m = load_module()
    correct = "a" * 40
    m.verify_expected_commit(correct, None)  # Legacy workflow still supported.
    m.verify_expected_commit(correct, correct)
    with pytest.raises(m.PromotionError, match="40-character"):
        m.verify_expected_commit(correct, "a" * 7)
    with pytest.raises(m.PromotionError, match="does not match"):
        m.verify_expected_commit(correct, "b" * 40)


def test_upgrade_script_prints_commit_pinned_commands():
    src = (ROOT / "scripts" / "upgrade-vps.sh").read_text()
    assert 'STAGE_PATH=$stage' in src
    assert 'STAGE_REVISION=$revision' in src
    assert '--expect-commit %q' in src
    assert '--activate --stage %q --expect-commit %q --confirm ACTIVATE_MT_PANEL' in src
    assert "ONLY AFTER activation" in src
    assert "systemctl restart" not in src
