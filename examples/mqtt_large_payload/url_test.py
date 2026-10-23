"""The library's broker URL parsing on the PLC (UrlProbe -> MQTT.STRING_TO_URL), for the credential forms we may use.

Run from the repo root after deploy_demo.py:
    python examples/mqtt_large_payload/url_test.py --out examples/mqtt_large_payload/results/exp/validation/url.json
Each case writes UrlProbe.Input and compares the parsed user, password, host and port with what a broker should see.
The parser splits at the last '@' and the first ':' before it, so a ':' inside the user name cannot work (expected).
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from run_ide_script import execute  # noqa: E402

LONG_PASSWORD = "p" * 40 + "Q9" * 20     # 80 characters (upstream kept 32)
CASES = [
    ("plain", "plc-01:secret@192.168.50.240:1883", ("plc-01", "secret", "192.168.50.240", 1883)),
    ("user only", "plc-01@192.168.50.240:1883", ("plc-01", "", "192.168.50.240", 1883)),
    ("no credentials", "192.168.50.240:1883", ("", "", "192.168.50.240", 1883)),
    ("'@' in password", "plc-01:p@ss@192.168.50.240:1883", ("plc-01", "p@ss", "192.168.50.240", 1883)),
    ("':' in password", "plc-01:a:b:c@192.168.50.240:1883", ("plc-01", "a:b:c", "192.168.50.240", 1883)),
    ("80-char password", "plc-01:%s@192.168.50.240:1883" % LONG_PASSWORD, ("plc-01", LONG_PASSWORD, "192.168.50.240", 1883)),
    ("hostname", "plc-01:secret@tigstack.localdomain:1883", ("plc-01", "secret", "tigstack.localdomain", 1883)),
    ("mqtt:// prefix", "mqtt://plc-01:secret@192.168.50.240:1883", ("plc-01", "secret", "192.168.50.240", 1883)),
]

WRITE = """
on = session.ensure_online_application('', True)
on.set_prepared_value('UrlProbe.Input', @@VALUE@@)
on.write_prepared_values()
result = {'success': True}
"""
READ = """
on = session.ensure_online_application('', True)
def text(path):
    return str(on.read_value(path))
result = {'success': True, 'user': text('UrlProbe.User'), 'password': text('UrlProbe.Password'),
          'domain': text('UrlProbe.Domain'), 'port': int(text('UrlProbe.Port').split('#')[-1]),
          'count': int(text('UrlProbe.ParseCount').split('#')[-1])}
"""


def unquote(value: str) -> str:
    return value[1:-1] if len(value) >= 2 and value[0] == value[-1] == "'" else value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out")
    args = parser.parse_args()
    rows = []
    for name, url, expected in CASES:
        count = execute(READ, 60)["count"]
        execute(WRITE.replace("@@VALUE@@", repr("'%s'" % url.replace("$", "$$"))), 60)
        time.sleep(0.5)
        got = execute(READ, 60)
        parsed = (unquote(got["user"]), unquote(got["password"]), unquote(got["domain"]), got["port"])
        row = {"case": name, "url": url, "parsed": parsed, "expected": expected,
               "ok": got["count"] > count and parsed == expected}
        rows.append(row)
        print(json.dumps(row), flush=True)
    report = {"cases": rows, "success": all(r["ok"] for r in rows)}
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
