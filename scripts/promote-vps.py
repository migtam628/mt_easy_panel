#!/usr/bin/env python3
"""Controlled MT Panel-only promotion and rollback for an already installed VPS.

Never changes Docker, Caddy, Tailscale, firewall, or any non-MT-Panel unit.
The operator must explicitly opt into activation or rollback.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

INSTALL = Path("/opt/mt-panel")
BACKUPS = Path("/opt/mt-panel-backups")
ENV = Path("/etc/mt-panel/mt-panel.env")
DATA = Path("/var/lib/mt-panel/panel.db")
UNITS = ("mt-panel-agent.service", "mt-panel.service")
STAGE_PATTERN = re.compile(r"mt-panel-stage\.[a-zA-Z0-9]{8,16}")
BACKUP_PATTERN = re.compile(r"mt-panel-backup\.[a-zA-Z0-9]{8,16}")


class PromotionError(RuntimeError):
    pass


def command(*parts: str, cwd: Path | None = None) -> str:
    p = subprocess.run(parts, cwd=cwd, text=True, capture_output=True, timeout=35)
    if p.returncode:
        raise PromotionError(f"Command failed: {parts[0]} {parts[1] if len(parts)>1 else ''} (exit {p.returncode})")
    return p.stdout.strip()


def directory(path: Path, root: Path, matcher: re.Pattern[str]) -> Path:
    if path.is_symlink() or not path.is_dir() or path.parent != root or not matcher.fullmatch(path.name):
        raise PromotionError("Path must be a real MT Panel directory directly under " + str(root))
    if path.stat().st_uid != 0:
        raise PromotionError("Directory must be root-owned")
    return path


def stage_check(path: Path) -> str:
    directory(path, Path("/opt"), STAGE_PATTERN)
    for rel in ("panel/api.py", "agent/api.py", "requirements.txt",
                ".venv/bin/python", ".staged-commit"):
        if not (path / rel).is_file():
            raise PromotionError("Staged release is incomplete: " + rel)
    commit = (path / ".staged-commit").read_text().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise PromotionError("Staged release commit marker is invalid")
    return commit


def install_check() -> None:
    if INSTALL.is_symlink() or not (INSTALL / ".venv/bin/python").is_file():
        raise PromotionError("Existing /opt/mt-panel installation is missing or not supported")
    if not ENV.is_file() or not DATA.is_file():
        raise PromotionError("Installed MT Panel configuration/database is missing")
    if ENV.stat().st_mode & 0o077:
        raise PromotionError("Installed environment file permissions are too broad")
    for unit in UNITS:
        fragment = command("systemctl", "show", "-p", "FragmentPath", "--value", unit)
        if fragment != "/etc/systemd/system/" + unit:
            raise PromotionError("Unexpected systemd unit path: " + unit)
        command("systemctl", "is-active", "--quiet", unit)
    settings = {}
    # Read only two safe keys; NEVER print the token.
    for line in ENV.read_text().splitlines():
        if line.startswith("PANEL_PUBLIC_ORIGIN="):
            settings["origin"] = line.partition("=")[2]
        elif line.startswith("PANEL_COOKIE_SECURE="):
            settings["cookie"] = line.partition("=")[2]
    if not re.fullmatch(r"https://[a-z0-9-]+(?:\.[a-z0-9-]+)+\.ts\.net:8443", settings.get("origin", "")):
        raise PromotionError("Expected Tailscale-only origin on HTTPS port 8443")
    if settings.get("cookie") != "true":
        raise PromotionError("Secure browser cookie must be enabled")


def sqlite_backup(destination: Path) -> None:
    with sqlite3.connect(f"file:{DATA}?mode=ro", uri=True) as src:
        with sqlite3.connect(destination) as dst:
            src.backup(dst)
            result = dst.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise PromotionError("SQLite backup integrity check failed")
    destination.chmod(0o600)


def sqlite_restore(source: Path) -> None:
    # Atomic replacement on the same /var/lib/mt-panel filesystem.
    tmp = DATA.with_name(".mt-panel-restore-" + str(os.getpid()))
    try:
        shutil.copyfile(source, tmp)
        os.chown(tmp, DATA.stat().st_uid, DATA.stat().st_gid)
        tmp.chmod(0o600)
        os.replace(tmp, DATA)
    finally:
        tmp.unlink(missing_ok=True)


def stop_mtpanel() -> None:
    command("systemctl", "stop", "mt-panel.service")
    command("systemctl", "stop", "mt-panel-agent.service")


def start_mtpanel() -> None:
    command("systemctl", "start", "mt-panel-agent.service")
    command("systemctl", "start", "mt-panel.service")


def check_http(url: str, expect_code: int, expected_service: str | None = None) -> None:
    last = None
    for _ in range(12):
        try:
            with urlopen(url, timeout=2) as response:
                body = response.read(1024)
                if response.status != expect_code:
                    raise PromotionError("Unexpected service HTTP status")
                if expected_service and json.loads(body).get("service") != expected_service:
                    raise PromotionError("Unexpected service identity")
                return
        except HTTPError as exc:
            if exc.code == expect_code:
                return
            last = str(exc.code)
        except (URLError, OSError, ValueError, PromotionError) as exc:
            last = type(exc).__name__
        time.sleep(1)
    raise PromotionError("Post-start health/auth check failed for " + url + " (" + str(last) + ")")


def verify_services() -> None:
    for unit in UNITS:
        command("systemctl", "is-active", "--quiet", unit)
    check_http("http://127.0.0.1:8788/health", 200, "mt-panel-agent")
    check_http("http://127.0.0.1:8086/api/health", 200, "mt-panel")
    check_http("http://127.0.0.1:8788/v1/overview", 401)
    check_http("http://127.0.0.1:8086/api/server/overview", 401)


def snapshot(backup: Path) -> None:
    backup.mkdir(mode=0o700)
    backup.chmod(0o700)
    # Called only AFTER both MT Panel units have stopped, so SQLite is quiescent.
    sqlite_backup(backup / "panel.db")
    shutil.copy2(ENV, backup / "mt-panel.env")
    (backup / "mt-panel.env").chmod(0o600)
    for unit in UNITS:
        shutil.copy2(Path("/etc/systemd/system") / unit, backup / unit)
    (backup / "ready").write_text("MT Panel private rollback backup\n")


def stage_smoke() -> None:
    # After relocation, validate the moved venv still imports its dependencies.
    command(str(INSTALL / ".venv/bin/python"), "-c",
            "import fastapi, uvicorn, panel.api, agent.api, panel.registry",
            cwd=INSTALL)


def activate(stage: Path) -> None:
    commit = stage_check(stage)
    install_check()
    verify_services()
    BACKUPS.mkdir(mode=0o700, exist_ok=True)
    if BACKUPS.is_symlink() or BACKUPS.stat().st_uid != 0 or BACKUPS.stat().st_mode & 0o077:
        raise PromotionError("Backup root must be a private, root-owned directory")
    backup = BACKUPS / ("mt-panel-backup." + os.urandom(6).hex())
    print("Activating tested revision:", commit[:12])
    print("Rollback data directory:", backup)
    print("Stopping ONLY the MT Panel dashboard and agent")
    stopped = False
    previous_moved = False
    new_moved = False
    try:
        stopped = True
        stop_mtpanel()
        snapshot(backup)
        os.rename(INSTALL, backup / "code")
        previous_moved = True
        os.rename(stage, INSTALL)
        new_moved = True
        stage_smoke()
        start_mtpanel()
        verify_services()
        (backup / "revision").write_text(commit + "\n")
    except Exception:
        print("Activation failed; attempting automatic MT Panel-only rollback", file=sys.stderr)
        if stopped:
            try:
                stop_mtpanel()
                if new_moved:
                    os.rename(INSTALL, backup / "failed-candidate")
                if previous_moved:
                    os.rename(backup / "code", INSTALL)
                if (backup / "panel.db").is_file():
                    sqlite_restore(backup / "panel.db")
                start_mtpanel()
                verify_services()
                print("Previous MT Panel installation restored", file=sys.stderr)
            except Exception as rollback_exc:
                print("URGENT: Automatic rollback could not complete:", rollback_exc, file=sys.stderr)
                print("Review the private backup and MT Panel units. Other services were untouched.", file=sys.stderr)
        raise
    print("PASS: MT Panel upgraded; code/data rollback copy retained at:", backup)
    print("PASS: Tailscale Serve routes, Docker, Caddy and other applications unchanged.")
    print("To revert later, use --rollback with the backup directory and explicit confirmation.")


def rollback(backup: Path) -> None:
    directory(backup, BACKUPS, BACKUP_PATTERN)
    if not (backup / "ready").is_file() or not (backup / "panel.db").is_file() or not (backup / "code").is_dir():
        raise PromotionError("Rollback snapshot incomplete or already used")
    # Rollback must remain available even when the current MT Panel units are down.
    if INSTALL.is_symlink() or not INSTALL.is_dir() or not ENV.is_file() or not DATA.is_file():
        raise PromotionError("Existing code/configuration/database is missing; use manual recovery")
    for unit in UNITS:
        fragment = command("systemctl", "show", "-p", "FragmentPath", "--value", unit)
        if fragment != "/etc/systemd/system/" + unit:
            raise PromotionError("Unexpected systemd unit path: " + unit)
    failed_new = backup / "replaced-current"
    if failed_new.exists():
        raise PromotionError("This backup was already used for a rollback")
    print("Rolling back ONLY MT Panel using:", backup)
    stopped = False
    new_moved = False
    old_moved = False
    try:
        stopped = True
        stop_mtpanel()
        # Preserve the currently installed database, even on manual rollback.
        sqlite_backup(backup / "pre-rollback.db")
        os.rename(INSTALL, failed_new)
        new_moved = True
        os.rename(backup / "code", INSTALL)
        old_moved = True
        sqlite_restore(backup / "panel.db")
        stage_smoke()
        start_mtpanel()
        verify_services()
    except Exception:
        print("Rollback failed. Attempting to preserve the currently installed release.", file=sys.stderr)
        if stopped:
            try:
                stop_mtpanel()
                if old_moved and INSTALL.exists():
                    os.rename(INSTALL, backup / "failed-rollback-old-code")
                if new_moved and failed_new.exists():
                    os.rename(failed_new, INSTALL)
                if (backup / "pre-rollback.db").exists():
                    sqlite_restore(backup / "pre-rollback.db")
                start_mtpanel()
                verify_services()
                print("Original installed release recovered from failed rollback", file=sys.stderr)
            except Exception as recovery_error:
                print("URGENT: Manual recovery required:", recovery_error, file=sys.stderr)
        raise
    print("PASS: Previous MT Panel code and SQLite snapshot restored.")
    print("The newer code and pre-rollback DB remain preserved under:", backup)

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--activate", action="store_true")
    group.add_argument("--rollback", action="store_true")
    parser.add_argument("--stage", type=Path)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        if args.rollback:
            if os.geteuid() != 0 or args.confirm != "ROLLBACK_MT_PANEL" or args.backup is None:
                raise PromotionError("Rollback requires root, --backup PATH and --confirm ROLLBACK_MT_PANEL")
            rollback(args.backup)
        else:
            if args.stage is None:
                raise PromotionError("Use --stage with the exact tested staging directory")
            commit = stage_check(args.stage)
            install_check()
            verify_services()
            if args.check:
                print("PASS: Staged release", commit[:12], "is eligible for operator-approved promotion")
                print("PASS: Live services, private Tailscale origin and auth boundaries checked")
                print("No changes made")
            else:
                if os.geteuid() != 0 or args.confirm != "ACTIVATE_MT_PANEL":
                    raise PromotionError("Activation requires root and --confirm ACTIVATE_MT_PANEL")
                activate(args.stage)
    except (PromotionError, OSError, sqlite3.Error, subprocess.TimeoutExpired) as exc:
        print("FAIL:", exc, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
