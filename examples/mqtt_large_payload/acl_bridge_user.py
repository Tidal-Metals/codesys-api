"""Add (or remove) acl_test.py's broker user on the VM dev bridge (mochi in mqtt_bridge), then restart the bridge.

    python examples/mqtt_large_payload/acl_bridge_user.py add      # backs up mqtt_auth.yaml once, adds the user
    python examples/mqtt_large_payload/acl_bridge_user.py restore  # puts the backup back
The bridge does not reload its auth file, so each step restarts mqtt-bridge.service (a few seconds without the dev
broker); ask before using it on a bridge others rely on. The user may read and write raw_data_demo/# only. Its
password is generated into tmp/mochi_test_user.txt (git-ignored) and goes over ssh stdin, never on a command line;
restore deletes it.
"""
import secrets
import subprocess
import sys
from pathlib import Path

PASSWORD_FILE = Path(__file__).resolve().parents[2] / "tmp" / "mochi_test_user.txt"

VM = "ktritz@192.168.50.142"
AUTH = "/opt/mqtt-bridge/config/mqtt_auth.yaml"
BACKUP = AUTH + ".bak-mqtt-bench"
USER = "plc-bench-mqtt-test"

ADD = r"""
set -e
pw=$(cat)
sudo test -f %(backup)s || sudo cp -p %(auth)s %(backup)s
sudo grep -q '^  %(user)s:' %(auth)s && { echo "user already present"; exit 0; }
block=$(printf '  %(user)s:\n    password: "%%s"\n    acl:\n      "raw_data_demo/#": readwrite\n\n' "$pw")
sudo awk -v block="$block" '/^anonymous:/ && !done { print block; done=1 } { print }' %(auth)s | sudo tee %(auth)s.new >/dev/null
sudo mv %(auth)s.new %(auth)s
sudo chown root:root %(auth)s; sudo chmod 644 %(auth)s
sudo systemctl restart mqtt-bridge.service
sleep 3
systemctl is-active mqtt-bridge.service
""" % {"auth": AUTH, "backup": BACKUP, "user": USER}

RESTORE = r"""
set -e
sudo test -f %(backup)s
sudo cp -p %(backup)s %(auth)s
sudo rm %(backup)s
sudo systemctl restart mqtt-bridge.service
sleep 3
systemctl is-active mqtt-bridge.service
sudo grep -c '%(user)s' %(auth)s || true
""" % {"auth": AUTH, "backup": BACKUP, "user": USER}


def main() -> int:
    action = sys.argv[1]
    if action == "add" and not PASSWORD_FILE.exists():
        PASSWORD_FILE.parent.mkdir(exist_ok=True)
        PASSWORD_FILE.write_text(secrets.token_urlsafe(12))
    password = PASSWORD_FILE.read_text().strip() if action == "add" else ""
    script = ADD if action == "add" else RESTORE
    result = subprocess.run(["ssh", "-o", "BatchMode=yes", VM, script], input=password,
                            capture_output=True, text=True, timeout=60)
    print(result.stdout.strip(), result.stderr.strip())
    if action == "restore" and result.returncode == 0:
        PASSWORD_FILE.unlink(missing_ok=True)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
