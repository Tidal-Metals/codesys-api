"""Builds report/split.html (Doc Shelf: projects/codesys/mqtt-message-size-vs-count) from results/exp/split.

    python examples/mqtt_large_payload/report/make_split_doc.py
Style from report_template.html, like the throughput report.
"""
import html
import json
import math
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "results" / "exp" / "split" / "split.json"
OUT = HERE / "split.html"
THROUGHPUT_URL = "https://docs.local.tidalmetals.org/documents/projects/codesys/mqtt-publish-throughput/latest/"
PUBLISHERS = [1, 8, 32]
SERIES = {1: "--s1", 8: "--s2", 32: "--s3"}
ALLOWANCE_NAMES = {"call1": "one client call per scan", "budget5": "5 ms client budget"}


def find(rows, parts, publishers, qos, allowance):
    return next((r for r in rows if r["parts"] == parts and r["publishers"] == min(publishers, parts)
                 and r["qos"] == qos and r["allowance"] == allowance), None)


def number(value, digits=0):
    return format(value, ",.%df" % digits)


def table(rows, qos, allowance):
    parts = sorted({r["parts"] for r in rows})
    head = "".join("<th>%d publisher%s</th>" % (p, "" if p == 1 else "s") for p in PUBLISHERS)
    body = []
    for count in parts:
        sample = find(rows, count, 1, qos, allowance) or find(rows, count, 8, qos, allowance)
        cells = []
        for p in PUBLISHERS:
            r = find(rows, count, p, qos, allowance)
            if r is None:
                cells.append('<td class="none">not run</td>')
                continue
            scans = format(r["roundScans"], "g")
            cells.append('<td><span class="t">%s ms</span> <span class="s">%s scan%s</span><br>'
                         '<span class="c">worst %s ms</span></td>'
                         % (number(r["roundMs"]), scans, "" if scans == "1" else "s", format(r["maxScanClientMs"], ".1f")))
        body.append("<tr><th>%d</th><td class=\"num\">%s</td>%s</tr>" % (count, number(sample["partBytes"]), "".join(cells)))
    return ('<table class="split"><thead><tr><th>Messages</th><th>Bytes each</th>%s</tr></thead><tbody>%s</tbody></table>'
            % (head, "".join(body)))


def chart(rows, qos):
    """Delivery time against message count, log-log, one line per publisher count (one call per scan)."""
    width, height, left, right, top, bottom = 330, 250, 52, 44, 14, 40
    xs = [1, 1625]
    ys = [50, 50000]
    def x(v):
        return left + (math.log10(v) - math.log10(xs[0])) / (math.log10(xs[1]) - math.log10(xs[0])) * (width - left - right)
    def y(v):
        return top + (1 - (math.log10(v) - math.log10(ys[0])) / (math.log10(ys[1]) - math.log10(ys[0]))) * (height - top - bottom)
    out = ['<svg viewBox="0 0 %d %d" role="img" aria-label="QoS %d: time to deliver 26 KB against the number of messages">'
           % (width, height, qos)]
    for tick in (100, 1000, 10000):
        out.append('<line class="grid" x1="%d" x2="%d" y1="%.1f" y2="%.1f"/>' % (left, width - right, y(tick), y(tick)))
        out.append('<text class="tick" x="%d" y="%.1f" text-anchor="end">%s</text>'
                   % (left - 6, y(tick) + 4, {100: "0.1 s", 1000: "1 s", 10000: "10 s"}[tick]))
    for tick in (1, 10, 100, 1000):
        out.append('<text class="tick" x="%.1f" y="%d" text-anchor="middle">%s</text>' % (x(tick), height - bottom + 16, number(tick)))
    out.append('<line class="axis" x1="%d" x2="%d" y1="%d" y2="%d"/>' % (left, width - right, height - bottom, height - bottom))
    out.append('<text class="label" x="%d" y="%d" text-anchor="middle">messages (log)</text>' % ((left + width - right) // 2, height - 6))
    for p in PUBLISHERS:
        points = sorted((r["parts"], r["roundMs"], r) for r in rows if r["qos"] == qos and r["allowance"] == "call1"
                        and r["publishers"] == min(p, r["parts"]) and r["roundMs"])
        if not points:
            continue
        path = " ".join("%s%.1f,%.1f" % ("M" if i == 0 else "L", x(c), y(t)) for i, (c, t, _) in enumerate(points))
        out.append('<path class="line" d="%s" style="stroke: var(%s)"/>' % (path, SERIES[p]))
        for count, ms, r in points:
            tip = "%d messages of %s B, %d publisher%s: %s ms (%s scans), worst scan client time %.1f ms" % (
                count, number(r["partBytes"]), p, "" if p == 1 else "s", number(ms), format(r["roundScans"], "g"),
                r["maxScanClientMs"])
            out.append('<circle class="dot" cx="%.1f" cy="%.1f" r="4" style="fill: var(%s)"><title>%s</title></circle>'
                       % (x(count), y(ms), SERIES[p], html.escape(tip)))
        last_count, last_ms, _ = points[-1]
        out.append('<text class="direct" x="%.1f" y="%.1f">%d</text>' % (x(last_count) + 7, y(last_ms) + 4, p))
    out.append("</svg>")
    return "".join(out)


def csv(rows):
    keys = ["parts", "partBytes", "publishers", "qos", "allowance", "rounds", "roundMs", "maxRoundMs", "roundScans",
            "maxScanClientMs", "messagesPerSecond", "timeouts", "brokerMissing", "brokerDuplicates", "brokerBad", "ok"]
    lines = [",".join(keys)] + [",".join(str(r.get(k, "")) for k in keys) for r in rows]
    return "\n".join(lines)


def main():
    rows = json.loads(DATA.read_text(encoding="utf-8"))["rows"]
    style = re.search(r"<style>.*?</style>", (HERE / "report_template.html").read_text(encoding="utf-8"), re.S).group(0)
    style = style.replace("</style>", EXTRA_STYLE + "</style>")
    tables = []
    for allowance in ("call1", "budget5"):
        group = "".join("<h3>QoS %d, %s</h3>%s" % (qos, ALLOWANCE_NAMES[allowance], table(rows, qos, allowance))
                        for qos in (0, 1, 2))
        tables.append('<details%s><summary>%s (QoS 0, 1, 2)</summary>%s</details>'
                      % (" open" if allowance == "call1" else "", ALLOWANCE_NAMES[allowance].capitalize(), group))
    charts = "".join('<figure><figcaption>QoS %d</figcaption>%s</figure>' % (q, chart(rows, q)) for q in (0, 1, 2))
    legend = "".join('<span><i style="background: var(%s)"></i>%d publisher%s</span>' % (SERIES[p], p, "" if p == 1 else "s")
                     for p in PUBLISHERS)
    failed = sum(1 for r in rows if not r["ok"])
    text = TEMPLATE.replace("@@style@@", style).replace("@@charts@@", charts).replace("@@legend@@", legend)
    text = text.replace("@@tables@@", "".join(tables)).replace("@@cells@@", str(len(rows)))
    text = text.replace("@@failed@@", str(failed)).replace("@@throughput@@", THROUGHPUT_URL)
    text = text.replace("@@csv@@", json.dumps(csv(rows))).replace("@@json@@", json.dumps(json.dumps(rows, indent=1)))
    leftover = re.findall(r"@@\w+@@", text)
    assert not leftover, "unfilled placeholders: %s" % leftover
    OUT.write_text(text, encoding="utf-8")
    print(OUT, OUT.stat().st_size, "bytes")


EXTRA_STYLE = """
table.split { border-collapse: collapse; margin: 8px 0 20px; font-variant-numeric: tabular-nums; width: 100%; max-width: 820px; }
table.split th, table.split td { border-bottom: 1px solid var(--grid); padding: 6px 10px; text-align: right; vertical-align: top; }
table.split thead th { position: sticky; top: 38px; background: var(--page); font-weight: 600; }
table.split tbody tr:hover { background: var(--surface); }
table.split .s, table.split .c { color: var(--ink-2); font-size: 0.85em; }
table.split .t { font-weight: 600; }
table.split .none { color: var(--muted); font-size: 0.85em; }
.charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px; margin: 8px 0; }
.charts figure { margin: 0; background: var(--surface); border: 1px solid var(--grid); border-radius: 8px; padding: 8px; }
.charts figcaption { font-weight: 600; font-size: 0.9rem; margin: 0 0 2px 6px; }
.charts svg { width: 100%; height: auto; display: block; }
.charts .grid { stroke: var(--grid); stroke-width: 1; }
.charts .axis { stroke: var(--axis); stroke-width: 1; }
.charts .tick, .charts .label { fill: var(--muted); font-size: 11px; }
.charts .line { fill: none; stroke-width: 2; }
.charts .dot { stroke: var(--surface); stroke-width: 2; }
.charts .dot:hover { r: 6; }
.charts .direct { fill: var(--ink-2); font-size: 11px; }
.legend { display: flex; gap: 18px; font-size: 0.9rem; color: var(--ink-2); margin: 10px 0 4px; }
.legend i { display: inline-block; width: 14px; height: 3px; border-radius: 2px; margin-right: 6px; vertical-align: middle; }
.exports button { font: inherit; padding: 6px 12px; margin-right: 8px; border-radius: 6px; border: 1px solid var(--axis);
  background: var(--surface); color: var(--ink); cursor: pointer; }
.exports .done { color: var(--good); margin-left: 6px; }
details > summary { cursor: pointer; font-weight: 600; margin: 16px 0 4px; }
@media print { nav.toc, .exports { display: none; } }
"""

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MQTT on the PLC: one large message or many small ones</title>
@@style@@
</head>
<body>
<header>
<h1>MQTT on the PLC: one large message or many small ones</h1>
<p class="meta">Bench P2CDS-622, MQTT library 1.3.0.0 (Tidal Metals fork), 2026-10-22. The same 26 KB sent as 1 to 1,625
messages at QoS 0, 1 and 2: what it costs in time and scan load, and how to send our data.</p>
</header>
<nav class="toc"><ul>
<li><a href="#summary">Summary</a></li><li><a href="#recommendations">Recommendations</a></li>
<li><a href="#chart">Chart</a></li><li><a href="#tables">All results</a></li><li><a href="#method">Method</a></li>
<li><a href="#data">Data</a></li></ul></nav>
<main>

<section id="summary" class="tldr">
<strong>Summary</strong>
<ul>
<li><strong>The number of messages sets the time, not the bytes.</strong> An <code>MQTTPublish</code> instance finishes at
most one message per scan, so the delivery time is about <em>messages &divide; publishers</em> scans: at most about
10 messages per second per instance at a 100 ms task. Below a few KB the payload size makes no difference.</li>
<li><strong>2,000 tags as one message: 1 scan (0.1 s). As one message per tag: 5 s with 32 publishers, 20 s with 8.</strong></li>
<li><strong>Splitting does not lighten the scan.</strong> One 26 KB message costs 3.7 ms of client time in its one scan;
eight of 3.2 KB cost about 4 ms in each of two. Small messages lower the per-scan cost only by spreading it over many scans.</li>
<li><strong>QoS cost depends on the client calls.</strong> With one call per scan QoS 1 adds a scan and QoS 2 two
(two round trips). With a client budget the acknowledgements come back within the scan: QoS 1 and 2 then cost
nothing extra for a few messages.</li>
<li>All @@cells@@ cells delivered every message once and byte-exact at the broker, with no timeouts (@@failed@@ failed).</li>
</ul>
</section>

<h2 id="recommendations">Recommendations</h2>
<ol class="prose">
<li><strong>Full refresh: one message</strong> (1 scan at QoS 0). If command acknowledgements must not wait behind it
(the TCP stream sends a message whole, so an acknowledgement queued during a 26 KB send waits for it), send it as
<strong>3-4 messages of 6-8 KB, each through its own <code>MQTTPublish</code></strong>: same 2 scans, worst scan about 4 ms.</li>
<li><strong>Never one message per tag.</strong> Report-by-exception with many changes goes out as one message of
<code>tag:value</code> lines.</li>
<li><strong>One <code>MQTTPublish</code> per message that must be in flight at once</strong>, and
<code>COM_CONFIG.CountSlotsOut</code> at least that many. A steady stream of small messages (events, alarms) needs
publishers &divide; scan time &ge; messages per second.</li>
<li><strong>Re-arm in the same scan:</strong> on <code>done</code>, call the publisher once with
<code>send := FALSE</code>, then give it the next message with <code>send := TRUE</code>. Otherwise each instance sends
only every other scan (<code>send</code> is edge-triggered).</li>
<li><strong>QoS:</strong> 0 for periodic data, 1 for commands and acknowledgements. 2 only where a duplicate is harmful
and the receiver cannot de-duplicate, and then with a client budget so it costs no extra scans.</li>
<li><strong>Client budget 4 ms, not 5.</strong> The budget is checked after each call, so the last call overshoots it:
a 5 ms budget gave worst scans of 5.2-5.8 ms, and 6.6 ms at QoS 2 with 32 publishers.</li>
<li><strong>In slots &ge; the broker's inflight window</strong> (<code>COM_CONFIG.CountSlotsIn := 20</code> for mosquitto's
default <code>max_inflight_messages</code> 20) for a PLC that subscribes at QoS 1 or 2 (from the QoS work in the same fork).</li>
</ol>
<p>Earlier measurements of the full refresh itself (buffer sizes, calls per scan, budgets) are in the
<a href="@@throughput@@">MQTT publish throughput report</a>.</p>

<h2 id="chart">Delivery time against the number of messages</h2>
<p>One client call per scan. Both axes logarithmic; hover a point for its numbers. Up to 8 messages, 8 and 32
publishers are the same run (one publisher per message), so the lines lie on top of each other. One publisher was
run up to 64 messages (1,625 would take minutes).</p>
<div class="legend">@@legend@@</div>
<div class="charts">@@charts@@</div>

<h2 id="tables">All results</h2>
<p>Each cell: time from the first request to the last message done (scans), and the most client time in one scan.
With fewer messages than publishers, each message had its own publisher, so those cells repeat.</p>
@@tables@@

<h2 id="method">Method</h2>
<ul class="prose">
<li>PLC: P2CDS-622 (32-bit, runtime 3.5.19), 100 ms comms task; MQTT library 1.3.0.0 with the QoS fixes; 20 in slots,
40 out slots (so 32 messages can be in flight; the recommended setup uses 8). Broker: mosquitto on 192.168.50.240.</li>
<li><code>SplitTest</code> on the PLC sends 26,000 bytes as N messages through P <code>MQTTPublish</code> instances,
re-armed in the same scan, and times each round from the first request to the last <code>done</code> (QoS 0: written to
the socket; QoS 1: PUBACK; QoS 2: PUBCOMP). The data is prepared before the round; building payloads is not timed.</li>
<li>Scan allowance: <em>one client call per scan</em> (at the start of the scan) or a <em>5 ms client budget</em>
(more calls while a message is in flight); both with the reply call after the publishers when the first calls took
under 2 ms.</li>
<li>At the broker, a subscriber checks every message: header digits (round, part, count), length, and every byte of the
pattern; it counts missing, duplicate and corrupt messages.</li>
<li>3 or more rounds per cell; the table shows the mean round, the worst client time over all of them.</li>
<li>Reproduce: <code>codesys-api/examples/mqtt_large_payload/split_test.py</code> (driver and checker),
<code>show_split.py split</code> (tables), <code>st/split/SplitTest.st</code> (PLC side); results in
<code>results/exp/split/split.json</code>.</li>
</ul>

<h2 id="data">Data</h2>
<p class="exports"><button data-copy="csv">Copy as CSV</button><button data-copy="json">Copy as JSON</button><span class="done" hidden>Copied &#10003;</span></p>
</main>
<script>
const DATA = {csv: @@csv@@, json: @@json@@};
window.addEventListener("beforeprint", () => document.querySelectorAll("details").forEach(d => { d.open = true; }));
document.querySelectorAll("[data-copy]").forEach(button => button.addEventListener("click", async () => {
  await navigator.clipboard.writeText(DATA[button.dataset.copy]);
  const done = document.querySelector(".exports .done");
  done.hidden = false;
  setTimeout(() => { done.hidden = true; }, 1600);
}));
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
