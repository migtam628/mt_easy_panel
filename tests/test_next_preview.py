"""Next.js migration: static preview stays opt-in and on existing origin.

No Docker writes, Node runtime, new listener, auth replacement or proxy.
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from panel.api import Settings, create_app


def web_tree(tmp_path, monkeypatch):
    web = tmp_path / "web"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<h1>LEGACY_ROOT_REMAINS_ACTIVE</h1>")
    preview = tmp_path / "frontend-next" / "out"
    preview.mkdir(parents=True)
    (preview / "index.html").write_text("<h1>NEW_SAFE_PREVIEW</h1>")
    (preview / "monitoring").mkdir()
    (preview / "monitoring" / "index.html").write_text("<h1>MONITORING_PREVIEW</h1>")
    (preview / "_next" / "static").mkdir(parents=True)
    (preview / "_next" / "static" / "main.js").write_text("console.log('test')")
    module = importlib.import_module("panel.api")
    monkeypatch.setattr(module, "WEB_DIR", web)
    return preview


def settings(tmp_path, enabled=False):
    return Settings(str(tmp_path / "private.db"),
                    "http://127.0.0.1:8788", "t" * 64,
                    "http://127.0.0.1:8086",
                    next_preview_enabled=enabled)


def test_disabled_by_default_even_if_assets_are_present(tmp_path, monkeypatch):
    web_tree(tmp_path, monkeypatch)
    app = create_app(settings(tmp_path))
    client = TestClient(app)
    assert client.get("/next-preview/").status_code == 404
    assert "LEGACY_ROOT_REMAINS_ACTIVE" in client.get("/").text
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/health").json()["lab_execution_enabled"] is False


def test_enabled_preview_same_origin_without_changing_api_or_root(tmp_path, monkeypatch):
    web_tree(tmp_path, monkeypatch)
    client = TestClient(create_app(settings(tmp_path, enabled=True)))
    assert "NEW_SAFE_PREVIEW" in client.get("/next-preview/").text
    assert "MONITORING_PREVIEW" in client.get("/next-preview/monitoring/").text
    assert client.get("/next-preview/_next/static/main.js").status_code == 200
    assert "LEGACY_ROOT_REMAINS_ACTIVE" in client.get("/").text
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/health").json()["lab_execution_enabled"] is False
    assert client.get("/api/health").json()["version"]
    assert client.post("/api/deployments/jobs/" + "a" * 32 + "/run").status_code == 401


def test_missing_preview_assets_refuse_enabled_startup(tmp_path, monkeypatch):
    preview = web_tree(tmp_path, monkeypatch)
    (preview / "index.html").unlink()
    preview.rmdir() if not any(preview.iterdir()) else None
    # Directory exists but lacks index: static preview MUST have a usable
    # export, not just an arbitrary directory.
    with pytest.raises(RuntimeError, match="export missing"):
        create_app(settings(tmp_path, enabled=True))


def test_preview_does_not_follow_symlink_export(tmp_path, monkeypatch):
    preview = web_tree(tmp_path, monkeypatch)
    import shutil
    shutil.rmtree(preview)
    preview.symlink_to(tmp_path / "web", target_is_directory=True)
    with pytest.raises(RuntimeError, match="unsafe"):
        create_app(settings(tmp_path, enabled=True))


def test_next_configuration_is_static_and_api_paths_same_origin():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "frontend-next"
    config = (root / "next.config.ts").read_text()
    net = (root / "src" / "lib" / "api.ts").read_text()
    assert 'output: "export"' in config
    assert 'basePath: "/next-preview"' in config
    assert 'credentials: "same-origin"' in net
    assert 'path.startsWith("/api/")' in net
    assert not (root / "src" / "app" / "api").exists()
    assert not (root / "src" / "proxy.ts").exists()
