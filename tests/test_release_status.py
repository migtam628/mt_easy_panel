"""Safe read-only release lifecycle diagnostics without VPS access."""
from __future__ import annotations

import importlib.util
import io
import subprocess
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent


def load():
    spec = importlib.util.spec_from_file_location(
        "mtpanel_release_status", ROOT / "scripts/release-status.py"
    )
    obj = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(obj)
    return obj


def test_stage_listing_filters_symlinks_and_unverified_marker(tmp_path):
    m = load()
    good = tmp_path / "mt-panel-stage.abcdefgh"
    good.mkdir()
    (good / ".staged-commit").write_text("b" * 40 + "\n")
    broken = tmp_path / "mt-panel-stage.abcd1234"
    broken.mkdir()
    (broken / ".staged-commit").write_text("invalid-commit")
    alias = tmp_path / "mt-panel-stage.alias1234"
    alias.symlink_to(good, target_is_directory=True)
    misc = tmp_path / "unrelated"
    misc.mkdir()
    stages = m.candidate_stages(tmp_path)
    assert len(stages) == 2
    assert (good, "b" * 40) in stages
    assert (broken, None) in stages
    assert all(path != alias for path, _ in stages)


def test_status_distinguishes_staged_from_live_without_activation(monkeypatch, capsys, tmp_path):
    m = load()
    marker = tmp_path / "installed"
    marker.mkdir()
    (marker / ".staged-commit").write_text("a" * 40)
    stage = tmp_path / "mt-panel-stage.zxcv1234"
    stage.mkdir()
    monkeypatch.setattr(m, "INSTALL", marker)
    monkeypatch.setattr(m, "source_info", lambda: ("b" * 40, "0.3.6-dev"))
    monkeypatch.setattr(m, "live_version", lambda: "0.3.5-dev")
    monkeypatch.setattr(m, "candidate_stages", lambda: [(stage, "b" * 40)])
    monkeypatch.setattr("sys.argv", ["release-status.py", "--check"])
    m.main()
    out = capsys.readouterr().out
    assert "LIVE VERSION: 0.3.5-dev" in out
    assert "SOURCE VERSION: 0.3.6-dev" in out
    assert "SOURCE REVISION STAGED, NOT CONFIRMED LIVE" in out
    assert "--expect-commit" in out
    assert "no services or databases changed" in out


def test_status_detects_live_version_already_current(monkeypatch, capsys):
    m = load()
    monkeypatch.setattr(m, "source_info", lambda: ("c" * 40, "0.3.6-dev"))
    monkeypatch.setattr(m, "live_version", lambda: "0.3.6-dev")
    monkeypatch.setattr(m, "candidate_stages", lambda: [])
    monkeypatch.setattr(m, "revision", lambda path: "c" * 40)
    monkeypatch.setattr("sys.argv", ["release-status.py", "--check"])
    m.main()
    assert "LIVE VERSION MATCHES" in capsys.readouterr().out


def test_status_reports_no_current_stage_when_only_older_candidates_exist(monkeypatch, capsys):
    m = load()
    monkeypatch.setattr(m, "source_info", lambda: ("d" * 40, "0.3.6-dev"))
    monkeypatch.setattr(m, "live_version", lambda: "0.3.5-dev")
    monkeypatch.setattr(m, "candidate_stages", lambda: [(Path("/opt/mt-panel-stage.abcdefgh"),"c"*40)])
    monkeypatch.setattr(m, "revision", lambda path: "c" * 40)
    monkeypatch.setattr("sys.argv", ["release-status.py", "--check"])
    m.main()
    assert "NO STAGE MATCHES" in capsys.readouterr().out


def test_lifecycle_reader_does_not_call_mutating_commands():
    code = (ROOT / "scripts/release-status.py").read_text()
    assert '["git", "-C", str(SOURCE), "rev-parse", "HEAD"]' in code
    assert 'HTTPConnection("127.0.0.1", 8086' in code
    for forbidden in (
        "systemctl stop", "systemctl start", "systemctl restart",
        "docker run", "docker rm", "docker compose",
        "os.rename(", "os.replace(", "subprocess.Popen(", "sqlite3.connect(",
    ):
        assert forbidden not in code
