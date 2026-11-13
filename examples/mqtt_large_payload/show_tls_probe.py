"""One line per case from tls_probe.py output (its JSON lines on stdout, or the --out file's "cases")."""
import json
import sys


def cases(path):
    text = open(path, encoding="utf-8").read()
    if text.lstrip().startswith("{") and '"cases"' in text[:200]:
        yield from json.loads(text)["cases"]
        return
    for line in text.splitlines():
        if line.startswith("{"):
            yield json.loads(line)
        elif line.strip():
            print(line)


for case in cases(sys.argv[1]):
    callback = case.get("callback", {})
    alt = ""
    if callback.get("calls"):
        types = [callback.get("AltTypes[%d]" % i) for i in range(2)]
        ips = [callback.get("AltIps[%d]" % i) for i in range(2)]
        alt = " cb calls=%s chain=%s return=%s by=%s check=%s alts=%s types=%s ips=%s dns=%s,%s match=%s" % (
            callback["calls"], callback.get("LastVerifyResult"), callback.get("LastReturn"), callback.get("CheckedBy"),
            callback.get("LastHostCheckResult"),
            callback.get("LastAltNameCount"), types, ips, callback.get("AltDns[0]"), callback.get("AltDns[1]"),
            callback.get("IsHostMatched"))
    elif "callback" in case:
        alt = " cb calls=0"
    print("%-20s %-17s results=%s handshake=%sms maxcall=%sus main=%sms close=%sus rx=%s%s" % (
        case["case"], case["Outcome"], case["connect_results"], case["HandshakeMs"], case["MaxConnectCallUs"],
        case["main_task_max_gap_ms"], case["CloseUs"], case["received"], alt))
