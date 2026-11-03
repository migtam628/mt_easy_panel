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
    (preview / "index.html").write_text(
        '<h1>NEW_SAFE_PREVIEW</h1>'
        '<script src="/next-preview/_next/static/main.js"></script>'
        '<script>self.__next_f.push([1,"hydration-ready"])</script>'
        '<script>window.__next_data = "fixture";</script>'
    )
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


def test_preview_csp_hashes_allow_exact_inline_hydration_only(tmp_path, monkeypatch):
    import base64
    import hashlib

    web_tree(tmp_path, monkeypatch)
    client = TestClient(create_app(settings(tmp_path, enabled=True)))

    inline1 = 'self.__next_f.push([1,"hydration-ready"])'
    inline2 = 'window.__next_data = "fixture";'
    digest1 = base64.b64encode(hashlib.sha256(inline1.encode()).digest()).decode()
    digest2 = base64.b64encode(hashlib.sha256(inline2.encode()).digest()).decode()

    preview_response = client.get("/next-preview/")
    assert preview_response.status_code == 200
    preview_csp = preview_response.headers["content-security-policy"]
    assert "'sha256-" + digest1 + "'" in preview_csp
    assert "'sha256-" + digest2 + "'" in preview_csp
    assert "script-src 'self'" in preview_csp
    assert "'unsafe-inline'" not in preview_csp
    assert "'unsafe-eval'" not in preview_csp
    assert "connect-src 'self'" in preview_csp
    assert "form-action 'self'" in preview_csp

    for path in ("/", "/api/health", "/api/auth/me",
                 "/next-preview/_next/static/main.js"):
        response = client.get(path)
        policy = response.headers["content-security-policy"]
        assert "script-src 'self';" in policy
        assert "sha256-" not in policy
        assert "'unsafe-inline'" not in policy
    assert client.get("/api/auth/me").status_code == 401


def test_preview_script_policy_never_expands_for_unknown_routes(tmp_path, monkeypatch):
    from panel.next_preview_csp import PreviewCsp
    root = web_tree(tmp_path, monkeypatch)
    policy = PreviewCsp(root)
    for path in ("/api/health", "/", "/next-preview/_next/static/main.js",
                 "/next-preview/bogus/", "/next-preview/%2e%2e/other",
                 "/next-preview//", "/next-preview/../index.html"):
        assert policy.script_policy(path) is None
    assert policy.script_policy("/next-preview/monitoring/") == "script-src 'self'"


def test_static_preview_inline_csp_hashes_match_literal_script_data():
    from panel.next_preview_csp import _inline_hashes
    import base64
    import hashlib
    script = 'self.__next_f.push([1,"x&y < z"]);'
    html = '<script src="/_next/static/chunk.js"></script><script>' + script + '</script>'
    expected = "'sha256-" + base64.b64encode(
        hashlib.sha256(script.encode()).digest()).decode() + "'"
    assert _inline_hashes(html) == (expected,)
