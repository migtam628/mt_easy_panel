"""Hash-only CSP for Next.js *static* preview HTML, never for API/legacy pages.

Next.js 16 static exports embed inline bootstrap/Flight data scripts.
A strict `script-src 'self'` blocks those scripts and prevents hydration,
leaving the browser stuck at the server-rendered session placeholder.

The CSP is derived at process startup only from the trusted, root-owned
static HTML files already installed under the opt-in preview tree.
No unsafe-inline, unsafe-eval, dynamic user script, or script source
outside the original same-origin policy is introduced.
"""
from __future__ import annotations

import base64
import hashlib
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote

MAX_HTML_FILES = 128
MAX_HTML_BYTES = 2_000_000
MAX_INLINE_SCRIPTS = 128
MAX_INLINE_SCRIPT_BYTES = 1_000_000
PREFIX = "/next-preview"


class PreviewCspError(ValueError):
    """Refuse a malformed or insecure static preview bundle."""


class _InlineScriptParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.in_script = False
        self.chunks: list[str] = []
        self.inline_scripts: list[str] = []
        self.external = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        if tag.lower() != "script":
            return
        if self.in_script:
            raise PreviewCspError("Nested script tag in static HTML")
        self.in_script = True
        self.chunks = []
        self.external = any(key.lower() == "src" for key, _ in attrs)

    def handle_data(self, data: str):
        if self.in_script:
            self.chunks.append(data)

    def handle_endtag(self, tag: str):
        if tag.lower() != "script" or not self.in_script:
            return
        if not self.external:
            script = "".join(self.chunks)
            if script:
                self.inline_scripts.append(script)
                if len(self.inline_scripts) > MAX_INLINE_SCRIPTS:
                    raise PreviewCspError("Static HTML has too many inline scripts")
                if sum(len(x.encode("utf-8")) for x in self.inline_scripts) > MAX_INLINE_SCRIPT_BYTES:
                    raise PreviewCspError("Static HTML inline scripts exceed size limit")
        self.in_script = False
        self.chunks = []
        self.external = False


def _inline_hashes(contents: str) -> tuple[str, ...]:
    parser = _InlineScriptParser()
    try:
        parser.feed(contents)
        parser.close()
    except (ValueError, UnicodeError) as exc:
        raise PreviewCspError("Unable to parse preview static HTML") from exc
    return tuple(sorted({
        "'sha256-" + base64.b64encode(hashlib.sha256(
            script.encode("utf-8")).digest()).decode("ascii") + "'"
        for script in parser.inline_scripts
    }))


class PreviewCsp:
    def __init__(self, root: Path):
        if not root.is_dir() or root.is_symlink():
            raise PreviewCspError("Preview export must be a normal directory")
        self.hashes_by_path: dict[str, tuple[str, ...]] = {}
        paths = sorted(root.rglob("*.html"))
        if not paths or len(paths) > MAX_HTML_FILES or not (root / "index.html").is_file():
            raise PreviewCspError("Static preview has missing or excessive HTML pages")
        for file in paths:
            relative = file.relative_to(root)
            if file.is_symlink() or any(part in {"", ".", ".."} for part in relative.parts):
                raise PreviewCspError("Preview HTML includes an unsafe path")
            if not file.is_file() or file.stat().st_size > MAX_HTML_BYTES:
                raise PreviewCspError("Preview HTML missing or too large")
            content = file.read_text(encoding="utf-8")
            hashes = _inline_hashes(content)
            url = PREFIX + "/" + relative.as_posix()
            self.hashes_by_path[url] = hashes
            if file.name == "index.html":
                parent = url[:-len("index.html")]
                self.hashes_by_path[parent] = hashes

    def script_policy(self, request_path: str) -> str | None:
        # Never expand policy for legacy UI, API routes or static JS files.
        # Starlette's scope["path"] is already decoded. Reject ambiguous
        # percent encodings instead of trying to interpret them.
        if ("%" in request_path or "\\" in request_path
                or "//" in request_path or ".." in request_path.split("/")):
            return None
        exact = self.hashes_by_path.get(request_path)
        if exact is None:
            return None
        return "script-src 'self'" + (" " + " ".join(exact) if exact else "")
