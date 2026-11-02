"""Exercise Tailscale-only preflight with fake binaries; never change real Tailscale."""
from pathlib import Path
import os
import subprocess

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "tailscale-access.sh"


def run_check(tmp_path, fqdn="mttech-vps.my-tailnet.ts.net.", serve_status="{}", funnel_status=""):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    mock_tailscale = bin_dir / "tailscale"
    mock_tailscale.write_text(
        "#!/usr/bin/env python3\n"
        "import json,sys\n"
        f"dns={fqdn!r}\n"
        f"serve={serve_status!r}\n"
        f"funnel={funnel_status!r}\n"
        "args=sys.argv[1:]\n"
        "if args==['status','--json']:\n"
        "    print(json.dumps({'Self':{'DNSName':dns}}))\n"
        "elif args==['serve','status','--json']:\n"
        "    print(serve)\n"
        "elif args==['funnel','status']:\n"
        "    print(funnel)\n"
        "else:\n"
        "    sys.exit(9)\n"
    )
    mock_tailscale.chmod(0o755)
    mock_ss = bin_dir / "ss"
    mock_ss.write_text("#!/usr/bin/env bash\nexit 0\n")
    mock_ss.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
    return subprocess.run(["bash", str(SCRIPT), "--check"],
                          capture_output=True, text=True, env=env)


def test_check_prints_serve_only_command_and_real_dns(tmp_path):
    result = run_check(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "https://mttech-vps.my-tailnet.ts.net:8443" in result.stdout
    assert "tailscale serve --bg --https=8443 http://127.0.0.1:8086" in result.stdout
    assert "PASS:" in result.stdout
    assert "tailscale funnel" not in result.stdout.lower()


def test_check_rejects_existing_serve_8443(tmp_path):
    result = run_check(tmp_path, serve_status='{"Web":{"node.ts.net:8443":{}}}')
    assert result.returncode != 0
    assert "already" in result.stderr


def test_check_rejects_funnel_8443(tmp_path):
    result = run_check(tmp_path, funnel_status="https://node.ts.net:8443")
    assert result.returncode != 0
    assert "Funnel" in result.stderr


def test_check_rejects_untrusted_hostname(tmp_path):
    result = run_check(tmp_path, fqdn="https://evil.example/")
    assert result.returncode != 0
    assert "hostname" in result.stderr


def test_check_rejects_missing_hostname(tmp_path):
    result = run_check(tmp_path, fqdn="")
    assert result.returncode != 0


def test_script_is_syntactically_valid_and_never_configures_funnel():
    subprocess.run(["bash","-n",str(SCRIPT)],check=True)
    source = SCRIPT.read_text()
    assert "tailscale funnel status" in source  # status is a read-only conflict check
    assert "tailscale funnel --bg" not in source
    assert "tailscale funnel --https" not in source
    assert "tailscale serve reset" not in source
    assert "tailscale serve off" not in source
    assert "systemctl restart" not in source
    assert "PANEL_COOKIE_SECURE" in source
    assert 'os.replace(name, target)' in source
