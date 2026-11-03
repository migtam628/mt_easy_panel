"""Offline, no-root tests for exact-commit Next static asset staging."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def load():
    p = ROOT / "scripts" / "install-next-preview-stage.py"
    spec = importlib.util.spec_from_file_location("mtpanel_next_stage", p)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bundle(tmp_path, commit="a" * 40):
    path = tmp_path / "bundle"
    (path / "_next" / "static").mkdir(parents=True)
    (path / "monitoring").mkdir()
    (path / "index.html").write_text("<h1>Preview only</h1>")
    (path / "monitoring" / "index.html").write_text("<h1>Monitoring</h1>")
    (path / "_next" / "static" / "app.js").write_text("console.log('preview')")
    files = {}
    for file in path.rglob("*"):
        if file.is_file():
            files[file.relative_to(path).as_posix()] = hashlib.sha256(
                file.read_bytes()).hexdigest()
    (path / "mt-panel-build-manifest.json").write_text(
        json.dumps({"format": 1, "commit": commit, "files": files}))
    return path


def test_exact_sha_bundle_can_install_only_to_selected_staging_path(tmp_path):
    m = load()
    commit = "a" * 40
    source = bundle(tmp_path)
    files = m.validate_bundle(source, commit)
    output = tmp_path / "stage" / "frontend-next" / "out"
    output.parent.mkdir(parents=True)
    m.install_bundle(source, output, files)
    assert (output / "monitoring" / "index.html").read_text() == "<h1>Monitoring</h1>"
    assert (output / "mt-panel-build-manifest.json").is_file()
    assert not list(output.parent.glob(".next-preview.*"))
    with pytest.raises(m.PreviewBundleError, match="already exists"):
        m.install_bundle(source, output, files)


def test_wrong_revision_and_tampered_payload_fail_closed(tmp_path):
    m = load()
    source = bundle(tmp_path)
    with pytest.raises(m.PreviewBundleError, match="revision"):
        m.validate_bundle(source, "b" * 40)
    (source / "_next" / "static" / "app.js").write_text("altered")
    with pytest.raises(m.PreviewBundleError, match="digest mismatch"):
        m.validate_bundle(source, "a" * 40)


def test_extra_files_and_symlinks_are_rejected(tmp_path):
    m = load()
    source = bundle(tmp_path)
    (source / "untracked.js").write_text("unexpected")
    with pytest.raises(m.PreviewBundleError, match="Unexpected"):
        m.validate_bundle(source, "a" * 40)
    (source / "untracked.js").unlink()
    (source / "_next" / "static" / "other.js").symlink_to("app.js")
    with pytest.raises(m.PreviewBundleError, match="symlink"):
        m.validate_bundle(source, "a" * 40)


def test_unsafe_manifest_entries_and_incomplete_exports_are_rejected(tmp_path):
    m = load()
    source = bundle(tmp_path)
    manifest_path = source / "mt-panel-build-manifest.json"
    data = json.loads(manifest_path.read_text())
    data["files"]["../escape.js"] = hashlib.sha256(b"oops").hexdigest()
    manifest_path.write_text(json.dumps(data))
    with pytest.raises(m.PreviewBundleError, match="Unsafe"):
        m.validate_bundle(source, "a" * 40)
    del data["files"]["../escape.js"]
    del data["files"]["index.html"]
    manifest_path.write_text(json.dumps(data))
    with pytest.raises(m.PreviewBundleError, match="Incomplete"):
        m.validate_bundle(source, "a" * 40)


def test_stage_source_enforces_explicit_operator_confirmation_and_no_restart():
    source = (ROOT / "scripts" / "install-next-preview-stage.py").read_text()
    assert "INSTALL_MT_PANEL_NEXT_PREVIEW" in source
    assert "os.geteuid()" in source
    assert "stage_commit(args.stage" in source
    for forbidden in ("systemctl restart", "docker run", "docker rm",
                      "tailscale serve reset", "npm install", "subprocess.run"):
        assert forbidden not in source
