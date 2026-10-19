"""Build the Doc Shelf document on MQTT publish throughput from its template and the measured results.

Usage: python examples/mqtt_large_payload/report/make_throughput_doc.py [output.html]
Results come from results/throughput/ (measure_scale.py --client-calls/--budget-us, measure_idle_client.py,
verify_scale.py, the PLC_PRG copy benchmark) and results/scale/ (QoS 1). Library excerpts are quoted from
Stefan Dreyer's MQTT 1.2.0.7 and Common Helper 1.1.0.6 sources. Publish with the doc-shelf skill
(projects/codesys/mqtt-publish-throughput).
"""
import html
import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from tagvalue_section import hbar_chart  # noqa: E402

DEMO = HERE.parent
RESULTS = DEMO / "results"
THROUGHPUT = RESULTS / "throughput"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "throughput.html"
TASK_MS = 50
BUFFER_BYTES = 4095                  # OSCAT_NETWORK_TYPES.NETWORK_BUFFER_LONG_SIZE
CALL_COUNTS = [1, 2, 4, 8, 16, 32]
BUDGETS_US = [5000, 10000, 20000]


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


fixed = dict((n, load(THROUGHPUT / ("calls%d_qos0.json" % n))) for n in CALL_COUNTS)
adaptive = dict((b, load(THROUGHPUT / ("adaptive_budget%d_qos0.json" % b))) for b in BUDGETS_US)
idle = dict((run["calls"], run) for run in load(THROUGHPUT / "idle_client.json")["runs"])
copy_us = sum(load(THROUGHPUT / "copy_bench.json")["samplesUs"]) / 3.0
verify = load(THROUGHPUT / "verify_calls16.json")["byFormat"]["tagvalue"]
qos1 = load(RESULTS / "scale" / "tagvalue_per2000_qos1.json")

MESSAGE_BYTES = fixed[1]["LastPayloadLength"]
BUFFERS = math.ceil(MESSAGE_BYTES / float(BUFFER_BYTES - 30))     # header and topic take the first ~25 bytes
IDLE_CALL_US = idle[1]["meanUs"]
IDLE_PER_CALL_US = [idle[n]["meanPerCallUs"] for n in sorted(idle)]
SENDING_CALL_US = fixed[1]["MaxClientUs"]                         # with one call a scan, the worst call fills and sends
SOCKET_US = SENDING_CALL_US - IDLE_CALL_US - copy_us
# All of a message in one scan (16 calls): client time per 4 KB, including the call that frees the buffer.
PER_BUFFER_US = fixed[16]["MaxClientUs"] / float(BUFFERS)


def ms(us, digits=1):
    return ("%." + str(digits) + "f") % (us / 1000.0)


def kbps(nbytes, us):
    return "%.0f" % (nbytes / 1000.0 / (us / 1e6))


def model_scans(nbytes, budget_us):
    """Scans from send to done, as the demo counts them: the scans that move the data, plus the one that sees done.

    The loop checks the budget after each call, so a scan can run one buffer past it.
    """
    client_us = math.ceil(nbytes / float(BUFFER_BYTES - 30)) * PER_BUFFER_US
    return 1 + max(1, math.ceil(client_us / (budget_us + PER_BUFFER_US))), client_us


# ---------------------------------------------------------------- tables
def row(cells):
    return "<tr>" + "".join("<td>%s</td>" % c for c in cells) + "</tr>"


def fixed_rows():
    return "\n".join(row([n, ms(r["LastPublishUs"], 0), r["LastPublishCycles"], kbps(r["LastPayloadLength"], r["LastPublishUs"]),
                          ms(r["MaxClientUs"]), r["sentDuringWindow"], r["TimeoutCount"]]) for n, r in sorted(fixed.items()))


def adaptive_rows():
    rows = []
    for budget, r in sorted(adaptive.items()):
        scans, _ = model_scans(r["LastPayloadLength"], budget)
        rows.append(row([ms(budget, 0), ms(r["LastPublishUs"], 0), r["LastPublishCycles"], scans, ms(r["MaxClientUs"]),
                         r["MaxClientCalls"], r["TimeoutCount"]]))
    return "\n".join(rows)


def idle_rows():
    return "\n".join(row([n, ms(r["meanUs"], 2), ms(r["MaxClientUs"], 2), "%.0f" % r["meanPerCallUs"]]) for n, r in sorted(idle.items()))


def sizing_rows():
    rows = []
    for tags, nbytes in ((2000, MESSAGE_BYTES), (5000, MESSAGE_BYTES * 2.5), (10000, MESSAGE_BYTES * 5)):
        cells = ["{:,}".format(tags), "%.0f" % (nbytes / 1000.0)]
        _, client_us = model_scans(nbytes, 1)
        cells.append(ms(client_us, 0))
        cells.append("%.1f s" % ((2 * math.ceil(nbytes / float(BUFFER_BYTES - 30)) - 1) * TASK_MS / 1000.0))
        for budget in (5000, 10000):
            scans, _ = model_scans(nbytes, budget)
            cells.append("%d ms" % ((scans - 1) * TASK_MS))   # measured: send to done = (scans - 1) task intervals
        rows.append(row(cells))
    return "\n".join(rows)


# ---------------------------------------------------------------- charts
def charts():
    publish = hbar_chart("26 KB message: send to done", [
        ("%d call%s" % (n, "" if n == 1 else "s"), "s2", r["LastPublishUs"] / 1000.0,
         "%d calls per scan: %s ms, %d scans" % (n, ms(r["LastPublishUs"], 0), r["LastPublishCycles"]))
        for n, r in sorted(fixed.items())], "ms", 700, width=440, label_width=70, decimals=0)
    client = hbar_chart("Worst client time in one scan", [
        ("%d call%s" % (n, "" if n == 1 else "s"), "s1", r["MaxClientUs"] / 1000.0,
         "%d calls per scan: %s ms of client time at most" % (n, ms(r["MaxClientUs"])))
        for n, r in sorted(fixed.items())], "ms", 24, width=440, label_width=70, decimals=1)
    idle_chart = hbar_chart("Client time per scan, nothing to send", [
        ("%d call%s" % (n, "" if n == 1 else "s"), "s0", r["meanUs"] / 1000.0,
         "%d idle calls: %s ms mean, %.0f us each" % (n, ms(r["meanUs"], 2), r["meanPerCallUs"]))
        for n, r in sorted(idle.items())], "ms", 10, width=440, label_width=70, decimals=1)
    budget_chart = hbar_chart("Adaptive loop: send to done", [
        ("%s ms" % ms(b, 0), "s3", r["LastPublishUs"] / 1000.0,
         "budget %s ms: %s ms, %d scans, worst client time %s ms" % (ms(b, 0), ms(r["LastPublishUs"], 0), r["LastPublishCycles"], ms(r["MaxClientUs"])))
        for b, r in sorted(adaptive.items())], "ms", 700, width=440, label_width=70, decimals=0)
    return {"chart_publish": publish, "chart_client": client, "chart_idle": idle_chart, "chart_budget": budget_chart}


def timeline():
    """Client calls per scan for the 26 KB message: S = fills and sends a buffer, F = frees it, E = send/done edge."""
    sends = BUFFERS
    lanes = [
        ("1 call per scan", fixed[1]["LastPublishUs"],
         [["E"]] + [["S"] if s % 2 else ["F"] for s in range(1, 2 * sends)] + [["E"]]),
        ("16 calls per scan", fixed[16]["LastPublishUs"], [["E"], ["S", "F"] * sends, ["E"]]),
        ("adaptive, 5 ms budget", adaptive[5000]["LastPublishUs"],
         [["E"], ["S", "F", "S", "F", "S"], ["F", "S", "F", "S", "F"], ["S", "F", "S"], ["E"]]),
    ]
    x0, slot, scans, lane_h, gap = 200, 50, 2 * sends + 1, 56, 34
    height = 40 + len(lanes) * (lane_h + gap) + 30
    parts = ['<svg class="dg" viewBox="0 0 980 %d" role="img" aria-label="Timeline of client calls per scan">' % height,
             '<text x="%d" y="22" class="small" text-anchor="end">scan</text>' % (x0 - 6)]
    for s in range(scans):
        parts.append('<text x="%d" y="22" class="small" text-anchor="middle">%d</text>' % (x0 + s * slot + slot // 2, s))
    css = {"S": "send", "F": "free", "E": "edge"}
    for index, (label, publish_us, plan) in enumerate(lanes):
        y = 34 + index * (lane_h + gap)
        parts.append('<text x="10" y="%d" class="head">%s</text>' % (y + 24, label))
        parts.append('<text x="10" y="%d" class="time">send to done: %s ms</text>' % (y + 43, ms(publish_us, 0)))
        for s in range(scans):
            x = x0 + s * slot
            blocks = plan[s] if s < len(plan) else []
            parts.append('<rect x="%d" y="%d" width="%d" height="%d" rx="4" class="%s"/>' % (x + 1, y, slot - 2, lane_h, "wait" if blocks else "slot"))
            if len(blocks) == 1:
                width = {"S": 16, "F": 6, "E": 8}[blocks[0]]
                parts.append('<rect x="%d" y="%d" width="%d" height="%d" rx="2" class="%s"/>' % (x + 4, y + 4, width, lane_h - 8, css[blocks[0]]))
            elif blocks:
                width = (slot - 8) / float(len(blocks))
                for i, kind in enumerate(blocks):
                    parts.append('<rect x="%.1f" y="%d" width="%.1f" height="%d" rx="1.5" class="%s"/>'
                                 % (x + 4 + i * width, y + 4, max(width - 1, 1.5), lane_h - 8, css[kind]))
                parts.append('<text x="%d" y="%d" class="small" text-anchor="middle">%d calls</text>' % (x + slot // 2, y + lane_h + 13, len(blocks)))
    parts.append('<text x="%d" y="%d" class="sub">Not to scale within a scan: a sending call takes about %s ms and a freeing call about %s ms of the 50 ms.</text>'
                 % (x0, height - 8, ms(SENDING_CALL_US), ms(IDLE_CALL_US, 2)))
    parts.append("</svg>")
    return "\n".join(parts)


# ---------------------------------------------------------------- code
def code(title, text):
    return ('<p class="code-title"><code>%s</code></p><pre class="code"><code>%s</code></pre>'
            % (html.escape(title), html.escape(text.strip("\n"))))


def demo_loop():
    text = (DEMO / "st" / "PLC_PRG.st").read_text(encoding="utf-8")
    start = text.index("// The client moves one 4 KB send buffer")
    end = text.index("MaxClientCalls := MAX(MaxClientCalls, ClientCall);")
    return text[start:end].rstrip()


LIBRARY = {
    "lib_send_free": ("MQTT 1.2.0.7, MqttClient (start of every call)", """
IF MQTT_INFO.MQTT_CONNECTED THEN
	SendFree := COM.S_BUF.SIZE = 0;      // decided once, before this call sends anything
END_IF
...
SendOutData(MQTT_IN_OUT:= ADR(MQTT_IN_OUT));   // fills S_BUF only IF SendFree
...
MQTT_CONTROL(COM:= COM, INFO:=MQTT_INFO);      // hands S_BUF to the TCP layer (IP_CONTROL)
"""),
    "lib_insert": ("MQTT 1.2.0.7, InsertSplitPayload (payload into the send buffer)", """
// a payload longer than the free space is copied in pieces, one piece per buffer
bytes_to_send := UDINT_TO_UINT(MIN(size - new_pos, len - akt_pos));
MEM.MemMove(pSource:= ADR(payload[akt_pos]), pDestination:= ADR(buff[new_pos]), uiNumberOfBytes:= bytes_to_send);
akt_pos := akt_pos + bytes_to_send;
new_pos := new_pos +  bytes_to_send;
IF akt_pos + 1 >= len THEN
	state := INSERT_SPLIT_RETURN.INSERT_DONE;     // last piece: the publish is "sent"
ELSE
	state := INSERT_SPLIT_RETURN.INSERT_PENDING;  // more next time the buffer is free
END_IF
"""),
    "lib_ip_control": ("Common Helper 1.1.0.6, IP_CONTROL (TCP layer under the client)", """
IF s_done OR s_start THEN
	s_start := FALSE;
	s_cur_pos := s_cur_pos + s_cur_size;
	IF s_total > s_cur_pos THEN                  // more of this buffer to send
		s_cur_size := LIMIT(0, s_total - s_cur_pos, s_max_size);
		s_req := TRUE;
	ELSE                                         // everything sent: only now is the buffer free,
		s_req := FALSE;                          // one call after the send
		s_active := FALSE;
		S_BUF.SIZE := 0;
	END_IF;
END_IF;
IF s_req THEN
	s_done := FALSE;
	bytes_sent := TO_DINT(SysSocket2.SysSock2Send(socket, ADR(S_BUF.BUFFER[s_cur_pos]), s_cur_size, 0, ADR(pResult)));
	...                                          // > 0: s_done := TRUE; < 0: not ready, try next call
"""),
    "lib_done": ("MQTT 1.2.0.7, PublishSendDone and MQTTPublish", """
// MqttClient.PublishSendDone, when the last piece is in the buffer
CASE slot^.InDataFromFb^.MessageQoS OF
	QoS.AtMostOnce:
		slot^.InDataFromFb^.SendSucsess := TRUE;   // QoS 0: done as soon as it is handed over
	QoS.AtLeastOnce:
		slot^.step := STEPS_OUT.WAIT_PUBACK;       // QoS 1: done when the broker's PUBACK arrives
...
// MQTTPublish, next time it is called
IF MyOutData.PaketData.SendSucsess THEN
	requestToSend := FALSE;
	done := TRUE;                                  // one-call pulse
END_IF
SendTimeOutTime(IN:= requestToSend, PT:= MyConstants.SENDING_TIMEOUT);   // T#4S, a warning only
"""),
}


def fields():
    values = {
        "message_kb": "%.1f" % (MESSAGE_BYTES / 1000.0),
        "buffers": BUFFERS,
        "calls_needed": 2 * BUFFERS,
        "t1_ms": ms(fixed[1]["LastPublishUs"], 0),
        "t1_scans": fixed[1]["LastPublishCycles"],
        "t1_kbps": kbps(MESSAGE_BYTES, fixed[1]["LastPublishUs"]),
        "t8_ms": ms(fixed[8]["LastPublishUs"], 0),
        "t16_ms": ms(fixed[16]["LastPublishUs"], 0),
        "t16_kbps": kbps(MESSAGE_BYTES, fixed[16]["LastPublishUs"]),
        "c16_ms": ms(fixed[16]["MaxClientUs"]),
        "speedup": "%.0f" % (fixed[1]["LastPublishUs"] / float(fixed[16]["LastPublishUs"])),
        "qos1_ms": ms(qos1["LastPublishUs"], 0),
        "qos1_scans": qos1["LastPublishCycles"],
        "idle_ms": ms(IDLE_CALL_US, 2),
        "idle_lo": "%.0f" % min(IDLE_PER_CALL_US),
        "idle_hi": "%.0f" % max(IDLE_PER_CALL_US),
        "idle32_ms": ms(idle[32]["meanUs"]),
        "copy_ms": ms(copy_us, 2),
        "send_call_ms": ms(SENDING_CALL_US, 1),
        "socket_ms": ms(SOCKET_US, 1),
        "per_buffer_ms": ms(PER_BUFFER_US, 1),
        "cpu_message_ms": ms(PER_BUFFER_US * BUFFERS, 0),
        "kb_per_ms": "%.1f" % ((BUFFER_BYTES - 30) / PER_BUFFER_US),
        "b5_ms": ms(adaptive[5000]["LastPublishUs"], 0),
        "b5_client_ms": ms(adaptive[5000]["MaxClientUs"]),
        "b20_ms": ms(adaptive[20000]["LastPublishUs"], 0),
        "verify_messages": verify["messages"],
        "verify_values": "{:,}".format(verify["valuesChecked"]),
        "fixed_rows": fixed_rows(),
        "adaptive_rows": adaptive_rows(),
        "idle_rows": idle_rows(),
        "sizing_rows": sizing_rows(),
        "timeline": timeline(),
        "demo_loop": code("PLC_PRG (MQTT demo): the adaptive client loop", demo_loop()),
    }
    values.update(charts())
    for key, (title, text) in LIBRARY.items():
        values[key] = code(title, text)
    return values


def main():
    template = (HERE / "throughput_template.html").read_text(encoding="utf-8")
    style = re.search(r"<style>.*?</style>", (HERE / "report_template.html").read_text(encoding="utf-8"), re.S).group(0)
    style = style.replace("</style>", ".code-title { margin: 18px 0 4px; font-size: 0.85rem; color: var(--ink-2); }\n</style>")
    text = template.replace("@@style@@", style)
    for key, value in fields().items():
        text = text.replace("@@%s@@" % key, str(value))
    leftover = re.findall(r"@@\w+@@", text)
    assert not leftover, "unfilled placeholders: %s" % leftover
    OUT.write_text(text, encoding="utf-8")
    print(OUT, OUT.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
