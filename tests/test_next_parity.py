"""Keep Next.js UI parity explicit and prevent the preview from drifting.

These source-contract tests protect the original 11 navigation screens,
same-origin endpoints, existing dialogs and the exact original CSS base.
Browser interaction/screenshot parity still needs a separately configured
end-to-end browser test before replacing the original dashboard.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
NEXT = ROOT / "frontend-next"
LEGACY = ROOT / "web"

PAGE_NAMES = (
    "overview", "servers", "projects", "containers", "images",
    "networks", "volumes", "activity", "monitoring",
    "deployments", "settings",
)


def test_all_original_sections_present_in_order():
    routes = (NEXT / "src/lib/sections.ts").read_text()
    nav = (LEGACY / "index.html").read_text()
    original = re.findall(r'data-view="([a-z]+)"', nav)
    assert original == list(PAGE_NAMES)
    assert re.findall(r'"(' + "|".join(PAGE_NAMES) + r')"', routes.split("] as const")[0]) == list(PAGE_NAMES)
    assert "generateStaticParams" in (NEXT / "src/app/[section]/page.tsx").read_text()


def test_exact_legacy_css_reused_before_next_additions():
    legacy = (LEGACY / "styles.css").read_text()
    next_css = (NEXT / "src/app/globals.css").read_text()
    assert next_css.startswith(legacy)
    for original_class in (".sidebar", ".logo-mark", ".nav-item", ".stat",
                           ".panel-heading", ".pill", ".login-wrap",
                           ".login-card", ".topbar", ".table-wrap"):
        assert original_class in next_css


def test_original_screen_data_and_actions_are_migrated():
    js = (NEXT / "src/components/dashboard.tsx").read_text()
    urls = (
        "/api/server/overview", "/api/server/containers", "/api/server/images",
        "/api/server/networks", "/api/server/volumes", "/api/fleet/summary",
        "/api/catalog/projects", "/api/audit/events?limit=100",
        "/api/monitoring/overview", "/api/monitoring/diagnostics",
        "/api/deployments/readiness", "/api/deployments/jobs?limit=50",
        "/api/settings/security",
    )
    for url in urls:
        assert url in js, f"Missing original API source {url}"
    for action in ("View logs", "Identity / health", "Manage",
                   "Review policy", "Save dry-run", "Evidence packet",
                   "+ Add server", "+ New project"):
        assert action in js


def test_original_modals_are_react_components_without_agent_secrets():
    dialogs = (NEXT / "src/components/legacy-dialogs.tsx").read_text()
    for title in ("Create project", "Register server",
                  "Agent identity", "Signed host health", "Signed disk history",
                  "Image deployment drafts", "Compose compatibility check",
                  "Validate only", "New", "Review packet", "CONTAINER LOGS"):
        # New refers to static compatibility text for the future, not a Docker action.
        if title == "New":
            continue
        assert title in dialogs, title
    endpoints = (
        "/api/catalog/servers/", "/identity", "/invites", "/revoke",
        "/host-report", "/host-history?limit=96", "/environments", "/drafts",
        "/api/validate/compose", "/review", "/review-packet", "/logs",
    )
    for endpoint in endpoints:
        assert endpoint in dialogs, endpoint
    for forbidden in ("docker.sock", "AGENT_TOKEN", "AGENT_EXECUTION_KEY",
                      "PANEL_LOCAL_EXECUTION_ENABLED", "eval(", "dangerouslySetInnerHTML"):
        assert forbidden not in dialogs
    assert "window.confirm" in dialogs  # Identity revocation remains explicit.


def test_login_and_static_preview_security_preserved():
    gate = (NEXT / "src/components/session-gate.tsx").read_text()
    assert "Welcome back." in gate
    assert "SELF-HOSTED INFRASTRUCTURE" in gate
    assert "/api/auth/me" in gate
    assert "/api/auth/login" in gate
    assert "/api/auth/logout" in gate
    assert "credentials" not in gate # Set by central same-origin API wrapper.
    net = (NEXT / "src/lib/api.ts").read_text()
    assert 'credentials: "same-origin"' in net
    assert 'path.startsWith("/api/")' in net
    assert not (NEXT / "src/app/api").exists()
