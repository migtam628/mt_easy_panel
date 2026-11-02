"""Static safety checks: do not execute installer or contact Docker."""
from pathlib import Path
import configparser
import subprocess

ROOT = Path(__file__).resolve().parent.parent


def test_install_scripts_parse_and_help_is_inert():
    scripts = ["install-vps.sh", "vps-preflight.sh", "dev.sh", "test.sh"]
    for name in scripts:
        subprocess.run(["bash", "-n", str(ROOT / "scripts" / name)], check=True)
    out = subprocess.run(
        ["bash", str(ROOT / "scripts" / "install-vps.sh"), "--help"],
        capture_output=True, text=True, check=True,
    )
    assert "--check" in out.stdout
    assert "--install" in out.stdout
    assert "will not start or enable" in out.stdout


def test_systemd_units_split_docker_authority():
    units = {}
    for name in ["mt-panel.service", "mt-panel-agent.service"]:
        path = ROOT / "deployment" / "systemd" / name
        parser = configparser.ConfigParser(interpolation=None)
        with path.open() as fd:
            parser.read_file(fd)
        units[name] = parser
        assert parser.get("Service", "NoNewPrivileges") == "true"
        assert parser.get("Service", "ProtectHome") == "true"
        assert parser.get("Service", "EnvironmentFile") == "/etc/mt-panel/mt-panel.env"
        assert parser.get("Service", "WorkingDirectory") == "/opt/mt-panel"
        assert parser.get("Service", "UMask") == "0077"
        assert parser.get("Service", "ProtectSystem") == "strict"

    panel = units["mt-panel.service"]["Service"]
    agent = units["mt-panel-agent.service"]["Service"]
    assert panel["User"] == "mtpanel"
    assert agent["User"] == "mtpanel-agent"
    assert "SupplementaryGroups" not in panel
    assert agent["SupplementaryGroups"] == "docker"
    assert "--host 127.0.0.1 --port 8086" in panel["ExecStart"]
    assert "--host 127.0.0.1 --port 8788" in agent["ExecStart"]
    assert "ReadWritePaths" not in agent
    assert "/var/lib/mt-panel" in panel["ReadWritePaths"]


def test_first_install_does_not_touch_existing_proxy_or_containers():
    script = (ROOT / "scripts" / "install-vps.sh").read_text()
    preflight = (ROOT / "scripts" / "vps-preflight.sh").read_text()
    assert "scripts/vps-preflight.sh" in script
    assert "/etc/systemd/system/mt-panel.service" in script
    assert "systemctl daemon-reload" in script
    assert "--exclude='./.env*'" in script
    assert "--exclude='./state'" in script
    assert "systemctl enable --now" not in [
        line.strip() for line in script.splitlines()
        if not line.strip().startswith("echo ")
    ]
    assert "docker info" in preflight
    # Installer only stages new MT Panel service units and does not manage existing services.
    for forbidden in ["docker run ", "docker rm ", "docker compose up",
                      "systemctl restart docker", "systemctl restart caddy",
                      "ufw ", "iptables ", "nft "]:
        assert forbidden not in script
