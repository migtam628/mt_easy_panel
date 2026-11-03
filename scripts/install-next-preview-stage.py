#!/usr/bin/env python3
"""Attach a CI-built Next.js static export to an *unactivated* release stage.

This deliberately does NOT modify live /opt/mt-panel, systemd, .env,
Tailscale, Caddy or any Docker workload. No npm, Node or root shell execution.
Only use a bundle downloaded from the same reviewed GitHub CI commit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

STAGE = re.compile(r"mt-panel-stage\.[a-zA-Z0-9]{8,16}\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")
SAFE_FILE = re.compile(r"[A-Za-z0-9_./-]{1,250}\Z")
EXTENSIONS = {".html", ".js", ".css", ".json", ".txt",
              ".svg", ".png", ".jpg", ".jpeg", ".ico", ".woff", ".woff2",
              ".webp", ".xml", ".map"}
MAX_FILES = 2000
MAX_TOTAL = 80 * 1024 * 1024
MANIFEST = "mt-panel-build-manifest.json"


class PreviewBundleError(ValueError):
    pass


def validate_bundle(source: Path, expected_commit: str) -> list[str]:
    if not SHA.fullmatch(expected_commit):
        raise PreviewBundleError("Expected commit must be exact 40-hex SHA")
    if source.is_symlink() or not source.is_dir():
        raise PreviewBundleError("Source must be a normal directory")
    manifest_path = source / MANIFEST
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise PreviewBundleError("CI static export manifest missing")
    if manifest_path.stat().st_size > 512 * 1024:
        raise PreviewBundleError("Bundle manifest is too large")
    try:
        document = json.loads(manifest_path.read_text("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise PreviewBundleError("Invalid bundle manifest") from exc
    if (not isinstance(document, dict) or set(document) !=
            {"format", "commit", "files"} or document["format"] != 1
            or document["commit"] != expected_commit
            or not isinstance(document["files"], dict)):
        raise PreviewBundleError("CI bundle revision does not match staged Git commit")
    expected = document["files"]
    if (not 1 <= len(expected) <= MAX_FILES
            or "index.html" not in expected
            or "monitoring/index.html" not in expected
            or not any(name.startswith("_next/static/") for name in expected)):
        raise PreviewBundleError("Incomplete or oversized static export")
    total = 0
    for rel, digest in expected.items():
        if (not isinstance(rel, str) or not SAFE_FILE.fullmatch(rel)
                or any(component in {"", ".", ".."} for component in rel.split("/"))
                or Path(rel).suffix.lower() not in EXTENSIONS
                or not isinstance(digest, str) or not HASH.fullmatch(digest)):
            raise PreviewBundleError("Unsafe static asset manifest entry")
        path = source
        for part in rel.split("/"):
            path = path / part
            if path.is_symlink():
                raise PreviewBundleError("Static bundle symlink forbidden")
        if not path.is_file():
            raise PreviewBundleError("Missing static asset: " + rel)
        size = path.stat().st_size
        total += size
        if total > MAX_TOTAL:
            raise PreviewBundleError("Static bundle exceeds size limit")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise PreviewBundleError("Static asset digest mismatch: " + rel)
    found = set()
    for path in source.rglob("*"):
        if path.is_symlink():
            raise PreviewBundleError("Static bundle may not contain symlinks")
        if path.is_file():
            found.add(path.relative_to(source).as_posix())
    if found != set(expected) | {MANIFEST}:
        raise PreviewBundleError("Unexpected or missing bundle files")
    return sorted(expected)


def stage_commit(stage: Path, expected: str):
    if (stage.is_symlink() or stage.parent != Path("/opt")
            or not STAGE.fullmatch(stage.name)
            or not stage.is_dir()
            or stage.stat().st_uid != 0):
        raise PreviewBundleError("Stage must be a root-owned /opt/mt-panel-stage.* directory")
    marker = stage / ".staged-commit"
    if marker.is_symlink() or not marker.is_file() or marker.read_text().strip() != expected:
        raise PreviewBundleError("Stage commit marker mismatch")
    frontend = stage / "frontend-next"
    if frontend.is_symlink() or not frontend.is_dir():
        raise PreviewBundleError("Stage does not include the reviewed Next source")
    output = frontend / "out"
    if output.exists() or output.is_symlink():
        raise PreviewBundleError("Stage already has a preview bundle; never overwrite")
    return output


def install_bundle(source: Path, output: Path, files: list[str]) -> None:
    """Atomic, add-only copy into the selected staged release."""
    if output.exists() or output.is_symlink():
        raise PreviewBundleError("Preview output already exists")
    parent = output.parent
    temp = Path(tempfile.mkdtemp(prefix=".next-preview.", dir=parent))
    try:
        for rel in [*files, MANIFEST]:
            target = temp / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / rel, target, follow_symlinks=False)
            target.chmod(0o644)
        # Validate copied bytes, not just the downloaded bundle.
        expected = json.loads((temp / MANIFEST).read_text("utf-8"))
        for rel, digest in expected["files"].items():
            if hashlib.sha256((temp / rel).read_bytes()).hexdigest() != digest:
                raise PreviewBundleError("Copied asset digest mismatch")
        os.replace(temp, output)
    finally:
        if temp.exists():
            shutil.rmtree(temp)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--install", action="store_true")
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--expect-commit", required=True)
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        files = validate_bundle(args.bundle_dir, args.expect_commit)
        output = stage_commit(args.stage, args.expect_commit)
        print(f"PASS: {len(files)} CI static assets match stage commit {args.expect_commit}")
        print(f"Target: {output}")
        if args.check:
            print("CHECK ONLY: no files, services, or configuration changed")
            return
        if os.geteuid() != 0 or args.confirm != "INSTALL_MT_PANEL_NEXT_PREVIEW":
            raise PreviewBundleError("Root and explicit INSTALL_MT_PANEL_NEXT_PREVIEW confirmation required")
        install_bundle(args.bundle_dir, output, files)
        print("PASS: Static preview installed only in the selected unactivated stage")
        print("No current dashboard, credentials, systemd units, or Docker workloads changed")
        print("Use the existing pinned promotion preflight before activating this stage")
    except (OSError, PreviewBundleError) as exc:
        print("FAIL: " + str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
