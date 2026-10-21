"""Print the TCP-layer split of measure_profile.py results: MQTT_CONTROL vs IP_CONTROL vs the socket calls.

    python examples/mqtt_large_payload/show_tcp_profile.py tcp_profile
"""
import json
import sys
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results" / "exp"


def main() -> int:
    data = json.loads((RESULTS / sys.argv[1] / "profile.json").read_text(encoding="utf-8"))["scenarios"]
    for name, scenario in data.items():
        control = scenario["meanUs"]["CONTROL"]
        tcp = scenario.get("tcp")
        print("%s: %d client calls, client call %s us, CONTROL section %s us" % (
            name, scenario["calls"], scenario["meanUs"]["TOTAL"], control))
        if not tcp:
            print("   (no TCP counters in this build)")
            continue
        ipc = tcp["ProfIpc"]
        recv, send = tcp["ProfRecv"], tcp["ProfSend"]
        per_call = lambda part: (part["meanUs"] or 0) * (part["perClientCall"] or 0)
        print("   IPC (IP_CONTROL): %s us per IPC call, %s per client call, max %s" % (ipc["meanUs"], ipc["perClientCall"], ipc["maxUs"]))
        print("   SysSock2Recv: %s us per call, %s calls per client call, max %s" % (recv["meanUs"], recv["perClientCall"], recv["maxUs"]))
        print("   SysSock2Send: %s us per call, %s calls per client call, max %s" % (send["meanUs"], send["perClientCall"], send["maxUs"]))
        print("   per client call: MQTT_CONTROL logic %.0f, IP_CONTROL logic %.0f, recv %.0f, send %.0f us" % (
            control - per_call(ipc), per_call(ipc) - per_call(recv) - per_call(send), per_call(recv), per_call(send)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
