"""Builds report/mixed.html (Doc Shelf: projects/codesys/mqtt-qos-mixed-rate) from results/exp/qos_mixed.

    python examples/mqtt_large_payload/report/make_mixed_doc.py
Style from report_template.html, like the split and throughput reports.
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "results" / "exp" / "qos_mixed"
OUT = HERE / "mixed.html"
SPLIT_URL = "https://docs.local.tidalmetals.org/documents/projects/codesys/mqtt-message-size-vs-count/latest/"
THROUGHPUT_URL = "https://docs.local.tidalmetals.org/documents/projects/codesys/mqtt-publish-throughput/latest/"
# (result file, short name); column order of the headline table follows COLUMNS
SETUPS = [("task100_budget4", "100 ms task, 4 ms client budget"),
          ("task100_budget8", "100 ms task, 8 ms client budget"),
          ("task50_budget4", "50 ms task, 4 ms client budget")]
COLUMNS = [("task100_budget4", 0), ("task100_budget4", 1), ("task100_budget8", 1), ("task50_budget4", 0),
           ("task50_budget4", 1)]
LAYOUTS = [("consolidated", "1 message per stream"), ("grouped100", "100 tags per message"),
           ("small25", "25 tags per message")]
STREAMS = {"S": "slow (1/s)", "F": "fast (10/s)"}


def load():
    return {name: json.loads((DATA / (name + ".json")).read_text(encoding="utf-8")) for name, _ in SETUPS}


def find(reports, setup, layout, qos):
    return next((r for r in reports[setup]["rows"] if r["layout"] == layout and r["qos"] == qos), None)


def kept_pill(percent):
    kind = "good" if percent >= 99.5 else "warn" if percent >= 95 else "bad"
    return '<span class="pill %s">%s %%</span>' % (kind, format(percent, "g"))


def headline(reports):
    head = "".join("<th class=\"num\">%s<br>QoS %d</th>" % (dict(SETUPS)[s].replace(", ", ",<br>"), q) for s, q in COLUMNS)
    body = []
    for layout, name in LAYOUTS:
        cells = []
        for setup, qos in COLUMNS:
            row = find(reports, setup, layout, qos)
            if row is None:
                cells.append('<td class="num muted">not run</td>')
                continue
            fast, scan = row["plc"]["F"], row["plc"]["scan"]
            cells.append('<td class="num">%s<br><span class="muted">%d skipped &middot; load %.1f %%</span></td>'
                         % (kept_pill(fast["keptUpPercent"]), fast["skipped"], scan["taskLoadPercent"]))
        body.append("<tr><th>%s</th>%s</tr>" % (name, "".join(cells)))
    return ('<div class="table-wrap"><table class="compact headline"><thead><tr><th>Layout</th>%s</tr></thead>'
            "<tbody>%s</tbody></table></div>" % (head, "".join(body)))


def stream_rows(report):
    rows = []
    for row in report["rows"]:
        for key in ("S", "F"):
            plc, broker = row["plc"][key], row["broker"][key]
            age, gap = broker["messageAgeMs"] or {}, broker["roundGapMs"] or {}
            rows.append(
                "<tr><td>%s</td><td class=\"num\">%d</td><td>%s</td><td class=\"num\">%d &times; %s B</td>"
                "<td class=\"num\">%d / %d</td><td class=\"num\">%d</td><td class=\"num\">%s</td>"
                "<td class=\"num\">%.1f / %.1f</td><td class=\"num\">%.0f / %.0f (%s / %d)</td>"
                "<td class=\"num\">%.0f / %.0f</td><td class=\"num\">%.0f</td><td class=\"num\">%d / %d / %d</td></tr>"
                % (dict(LAYOUTS)[row["layout"]], row["qos"], STREAMS[key], plc["messagesPerRound"],
                   format(plc["bytesPerRound"] // plc["messagesPerRound"], ","), plc["roundsStarted"], plc["periodsDue"],
                   plc["skipped"], kept_pill(plc["keptUpPercent"]), plc["buildMs"], plc["maxBuildMs"], plc["sendMs"],
                   plc["maxSendMs"], format(plc["sendScans"], "g"), plc["maxSendScans"], age.get("p50", 0),
                   age.get("p99", 0), gap.get("max", 0), broker["partsMissing"], broker["partsDuplicated"],
                   broker["partsBad"]))
    return ('<div class="table-wrap"><table class="compact"><thead><tr><th>Layout</th><th class="num">QoS</th><th>Stream</th>'
            '<th class="num">Messages &times; size</th><th class="num">Rounds / due</th><th class="num">Skipped</th>'
            '<th class="num">Kept up</th><th class="num">Build ms avg / max</th>'
            '<th class="num">Send ms avg / max (scans)</th><th class="num">Age at broker ms p50 / p99</th>'
            '<th class="num">Worst gap ms</th><th class="num">Missing / dup / bad</th></tr></thead><tbody>%s</tbody>'
            "</table></div>" % "".join(rows))


def scan_rows(report):
    rows = []
    for row in report["rows"]:
        scan = row["plc"]["scan"]
        rows.append("<tr><td>%s</td><td class=\"num\">%d</td><td class=\"num\">%.1f / %.1f</td>"
                    "<td class=\"num\">%.1f / %.1f</td><td class=\"num\">%.1f</td><td class=\"num\">%.1f %%</td>"
                    "<td class=\"num\">%d</td></tr>"
                    % (dict(LAYOUTS)[row["layout"]], row["qos"], scan["cycleMs"], scan["maxCycleMs"], scan["clientMs"],
                       scan["maxClientMs"], scan["clientCallsPerScan"], scan["taskLoadPercent"],
                       row["plc"]["reconnects"]))
    return ('<div class="table-wrap"><table class="compact"><thead><tr><th>Layout</th><th class="num">QoS</th>'
            '<th class="num">Scan ms avg / max</th><th class="num">Client ms avg / max</th>'
            '<th class="num">Client calls a scan</th><th class="num">Task load</th><th class="num">Reconnects</th>'
            "</tr></thead><tbody>%s</tbody></table></div>" % "".join(rows))


def details(reports):
    out = []
    for name, title in SETUPS:
        report = reports[name]
        out.append('<details%s><summary>%s (%s)</summary><h3>Per stream</h3>%s<h3>Per scan</h3>%s</details>'
                   % (" open" if name == "task100_budget4" else "", title, report["started"][:10],
                      stream_rows(report), scan_rows(report)))
    return "".join(out)


def flat_rows(reports):
    rows = []
    for name, title in SETUPS:
        for row in reports[name]["rows"]:
            scan = row["plc"]["scan"]
            for key in ("S", "F"):
                plc, broker = row["plc"][key], row["broker"][key]
                rows.append({
                    "setup": title, "layout": row["layout"], "qos": row["qos"], "stream": STREAMS[key],
                    "seconds": row["seconds"], "messagesPerRound": plc["messagesPerRound"],
                    "bytesPerRound": plc["bytesPerRound"], "periodsDue": plc["periodsDue"],
                    "roundsStarted": plc["roundsStarted"], "skipped": plc["skipped"],
                    "keptUpPercent": plc["keptUpPercent"], "buildMs": plc["buildMs"], "maxBuildMs": plc["maxBuildMs"],
                    "sendMs": plc["sendMs"], "maxSendMs": plc["maxSendMs"], "sendScans": plc["sendScans"],
                    "timeouts": plc["timeouts"], "ageP50Ms": (broker["messageAgeMs"] or {}).get("p50"),
                    "ageP99Ms": (broker["messageAgeMs"] or {}).get("p99"),
                    "maxGapMs": (broker["roundGapMs"] or {}).get("max"), "partsMissing": broker["partsMissing"],
                    "partsDuplicated": broker["partsDuplicated"], "partsBad": broker["partsBad"],
                    "valuesChecked": broker["valuesChecked"], "scanMs": scan["cycleMs"], "maxScanMs": scan["maxCycleMs"],
                    "clientMs": scan["clientMs"], "maxClientMs": scan["maxClientMs"],
                    "taskLoadPercent": scan["taskLoadPercent"], "reconnects": row["plc"]["reconnects"]})
    return rows


def csv(rows):
    keys = list(rows[0])
    return "\n".join([",".join(keys)] + [",".join('"%s"' % r[k] if k == "setup" else str(r[k]) for k in keys)
                                         for r in rows])


def totals(rows):
    """Checks the claims the summary makes for every cell."""
    return {
        "cells": len(rows) // 2,
        "values": sum(r["valuesChecked"] for r in rows),
        "errors": sum(r["partsMissing"] + r["partsDuplicated"] + r["partsBad"] for r in rows),
        "timeouts": sum(r["timeouts"] for r in rows),
        "reconnects": sum(r["reconnects"] for r in rows) // 2,
        "slowSkips": sum(r["skipped"] for r in rows if r["stream"].startswith("slow")),
    }


def main():
    reports = load()
    rows = flat_rows(reports)
    total = totals(rows)
    assert total["errors"] == 0 and total["timeouts"] == 0 and total["reconnects"] == 0 and total["slowSkips"] == 0, total
    style = re.search(r"<style>.*?</style>", (HERE / "report_template.html").read_text(encoding="utf-8"), re.S).group(0)
    style = style.replace("</style>", EXTRA_STYLE + "</style>")
    replacements = {
        "style": style, "headline": headline(reports), "details": details(reports), "cells": str(total["cells"]),
        "values": format(total["values"], ","), "split": SPLIT_URL, "throughput": THROUGHPUT_URL,
        "csv": json.dumps(csv(rows)), "json": json.dumps(json.dumps(rows, indent=1)),
    }
    text = TEMPLATE
    for key, value in replacements.items():
        text = text.replace("@@%s@@" % key, value)
    leftover = re.findall(r"@@\w+@@", text)
    assert not leftover, "unfilled placeholders: %s" % leftover
    OUT.write_text(text, encoding="utf-8")
    print(OUT, OUT.stat().st_size, "bytes")


EXTRA_STYLE = """
table.headline td, table.headline th { vertical-align: middle; }
table.headline thead th { vertical-align: bottom; font-size: 0.82rem; }
table.headline .pill { font-size: 0.9rem; }
details > summary { cursor: pointer; font-weight: 600; margin: 16px 0 4px; }
svg.timeline { max-width: 900px; }
svg.timeline .lane { fill: var(--ink); font-size: 13px; font-weight: 600; }
svg.timeline .scan { fill: var(--s0); }
svg.timeline .client { fill: var(--s1); }
svg.timeline .build { fill: var(--s2); }
svg.timeline .note { fill: var(--ink-2); font-size: 11.5px; }
svg.timeline .note.bad { fill: var(--bad); font-weight: 600; }
svg.timeline .note.good { fill: var(--good); font-weight: 600; }
svg.timeline .ack { stroke: var(--s3); stroke-width: 2; fill: none; }
svg.timeline .axis { stroke: var(--axis); stroke-width: 1; }
.legend span.s1c::before { background: var(--s1); } .legend span.s2c::before { background: var(--s2); }
.legend span.s0c::before { background: var(--s0); }
.exports button { font: inherit; padding: 6px 12px; margin-right: 8px; border-radius: 6px; border: 1px solid var(--axis);
  background: var(--surface); color: var(--ink); cursor: pointer; }
.exports .done { color: var(--good); margin-left: 6px; }
@media print { nav.toc, .exports { display: none; } }
"""

# Scan boxes are 20 ms wide (2 px per ms on the 100 ms lane, the same scale on the 50 ms lane).
TIMELINE = """
<figure>
<figcaption>Why a 10/s stream at QoS 1 skips once a second on a 100 ms task, and not on a 50 ms task. Each grey
box is one scan (about 13 ms, drawn to scale); blue is the client loop, orange the formatting of the 500 REALs.</figcaption>
<div class="legend"><span class="s0c">scan</span><span class="s1c">client loop (4 ms budget)</span><span class="s2c">build the fast message (8 ms)</span></div>
<svg class="timeline" viewBox="0 0 860 250" role="img" aria-label="Timeline of scans for a 100 ms and a 50 ms task">
<line class="axis" x1="130" x2="850" y1="112" y2="112"/>
<text class="lane" x="0" y="60">100 ms task</text><text class="note" x="0" y="76">QoS 1, when the</text><text class="note" x="0" y="90">slow message goes</text>
<g>
<rect class="scan" x="130" y="50" width="26" height="22" rx="3"/><rect class="client" x="130" y="50" width="8" height="22"/><rect class="build" x="140" y="50" width="16" height="22"/>
<text class="note" x="130" y="40">fast round due: built, queued</text>
<rect class="scan" x="330" y="50" width="26" height="22" rx="3"/><rect class="client" x="330" y="50" width="8" height="22"/>
<text class="note" x="330" y="40">loop sends 8 KB fast + 18 KB slow;</text>
<text class="note" x="330" y="88">budget spent before the PUBACK</text>
<text class="note bad" x="330" y="102">next fast period: still busy, skipped</text>
<rect class="scan" x="530" y="50" width="26" height="22" rx="3"/><rect class="client" x="530" y="50" width="8" height="22"/>
<text class="note" x="530" y="40">PUBACK read, round done</text>
<text class="note good" x="530" y="88">next round starts (200 ms gap)</text>
<rect class="scan" x="730" y="50" width="26" height="22" rx="3"/>
<text class="tick" x="130" y="126">0 ms</text><text class="tick" x="330" y="126">100</text><text class="tick" x="530" y="126">200</text><text class="tick" x="730" y="126">300</text>
</g>
<line class="axis" x1="130" x2="850" y1="232" y2="232"/>
<text class="lane" x="0" y="180">50 ms task</text><text class="note" x="0" y="196">same load, QoS 1</text>
<g>
<rect class="scan" x="130" y="170" width="26" height="22" rx="3"/><rect class="client" x="130" y="170" width="8" height="22"/><rect class="build" x="140" y="170" width="16" height="22"/>
<text class="note" x="130" y="160">built, queued</text>
<rect class="scan" x="230" y="170" width="26" height="22" rx="3"/><rect class="client" x="230" y="170" width="8" height="22"/>
<text class="note" x="230" y="160">sent; ack late</text>
<rect class="scan" x="330" y="170" width="26" height="22" rx="3"/><rect class="client" x="330" y="170" width="8" height="22"/><rect class="build" x="340" y="170" width="16" height="22"/>
<text class="note" x="330" y="160">PUBACK read, done</text>
<text class="note good" x="330" y="208">next round on time</text>
<rect class="scan" x="430" y="170" width="26" height="22" rx="3"/><rect class="scan" x="530" y="170" width="26" height="22" rx="3"/>
<rect class="scan" x="630" y="170" width="26" height="22" rx="3"/><rect class="scan" x="730" y="170" width="26" height="22" rx="3"/>
<text class="tick" x="130" y="246">0 ms</text><text class="tick" x="230" y="246">50</text><text class="tick" x="330" y="246">100</text><text class="tick" x="430" y="246">150</text><text class="tick" x="530" y="246">200</text><text class="tick" x="630" y="246">250</text><text class="tick" x="730" y="246">300</text>
</g>
</svg>
</figure>
"""

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MQTT on the PLC: QoS 0 vs QoS 1 at mixed rates</title>
@@style@@
</head>
<body>
<header>
<h1>MQTT on the PLC: QoS 0 vs QoS 1 at mixed rates</h1>
<p class="meta">Bench P2CDS-622, MQTT library 1.3.0.0 (Tidal Metals fork), HQ broker, 2026-11-09. Can a PLC keep up
publishing at QoS 1 as it does at QoS 0? 2,000 tags with full values: 75 % once a second, the 500 analog values ten
times a second, sent as large, medium and small messages.</p>
</header>
<nav class="toc"><ul>
<li><a href="#summary">Summary</a></li><li><a href="#recommendations">Recommendations</a></li>
<li><a href="#results">Results</a></li><li><a href="#why">Why QoS 1 skips on a 100 ms task</a></li>
<li><a href="#cpu">Where the CPU goes</a></li><li><a href="#all">All results</a></li><li><a href="#method">Method</a></li>
<li><a href="#data">Data</a></li></ul></nav>
<main>

<section id="summary" class="tldr">
<strong>Summary</strong>
<ul>
<li><strong>On a 50 ms comms task, QoS 1 keeps up as well as QoS 0, at the same CPU cost.</strong> Every 10/s update
went out (99.9 % with 25-tag messages), at 16-20 % task load for both QoS levels.</li>
<li><strong>On a 100 ms task with the recommended 4 ms client budget, QoS 1 skips about 10 % of the 10/s updates</strong>
(13 % with 25-tag messages); QoS 0 skips under 1 %. An 8 ms budget fixes it at about 5 points more task load.</li>
<li><strong>The cause is timing, not throughput.</strong> A 10/s stream on a 100 ms task must finish in the next scan.
At QoS 1 that includes the broker's acknowledgement, which misses the scan's client time once a second, when the
18 KB slow message goes out in the same scan.</li>
<li><strong>The message layout hardly matters</strong> for keeping up: one message, 100-tag or 25-tag messages all
behave alike. Smaller messages cost 2-4 points more task load.</li>
<li><strong>Formatting the values costs more than QoS 1</strong>: 8 ms to build 500 REALs, 8 % of the CPU at 10/s.</li>
<li>All @@cells@@ cells: every one of @@values@@ values checked at the broker. None missing, duplicated or wrong; no
timeouts, no reconnects. The once-a-second stream never skipped.</li>
</ul>
</section>

<h2 id="recommendations">Recommendations</h2>
<ol class="prose">
<li><strong>QoS 1 is safe for periodic data</strong> where the comms task runs at least twice per period of the
fastest stream: a 50 ms task for 10/s data. On a 100 ms task with 10/s data, use QoS 0 or raise
<code>ClientBudgetUs</code> to 8000.</li>
<li><strong>Keep the comms task at 50 ms</strong> (the architecture default). On this load it costs 16-20 % task load at
either QoS, with worst scans of 20-27 ms, inside the 50 ms period.</li>
<li><strong>Send each stream as one message, or a few large ones.</strong> Small messages bought nothing here and cost
CPU; see the <a href="@@split@@">message size report</a> for the rules on splitting.</li>
<li><strong>Re-arm a publisher in the scan it reports <code>done</code></strong> and give it the next message at once,
as in the recommended pattern. A stream that cannot start a round on time should skip it, not queue it, and count the
skips: that count is the keep-up metric used here.</li>
<li><strong>Library improvement worth making:</strong> while a message is in flight the client loop runs to its full
budget at either QoS, because <code>MQTTPublish.done</code> is only seen after the loop. A client output for "nothing
left to send or acknowledge" would let the loop stop early and save 3-4 ms in every scan with a message in flight.</li>
</ol>

<h2 id="results">Results: did the 10/s stream keep up?</h2>
<p>Share of the fast (10/s) stream's periods that went out on time, the number skipped, and the PLC task load
(<code>PLC_PRG</code> time over wall time) for the whole load. 90 s per cell, about 925 periods. The slow (1/s) stream
went out on time in every cell.</p>
@@headline@@
<p class="muted">Green: 99.5 % or more. Amber: 95-99.5 %. Red: under 95 %. QoS 0 was not rerun with the 8 ms budget
because it already kept up with 4 ms.</p>

<h2 id="why">Why QoS 1 skips on a 100 ms task</h2>
<p>A stream is due every 100 ms. When it falls due, the PLC formats all its values into the messages and hands them to
the publishers. The client loop at the start of the next scan sends them. If the round is not finished when the next
period falls due, that period is skipped.</p>
<ul class="prose">
<li>At QoS 0 a message is <code>done</code> once it is written to the socket: within the next scan's client loop.</li>
<li>At QoS 1 it is <code>done</code> when the broker's PUBACK has been read. On the LAN that comes back in under a
millisecond, so it usually arrives within the same 4 ms loop.</li>
<li>Once a second the slow stream's 18 KB goes out in that same loop. Sending 26 KB fills the 4 ms budget (the client moves 4 KB
per two calls), and the PUBACK is read one scan later. The fast round is still busy when its next period falls due, so
it is skipped: 93 skips in 93 seconds with one message or 100-tag messages, one per slow round (124 with 25-tag
messages, whose slow round spans several scans).</li>
<li>On a 50 ms task a 100 ms period spans two scans, so a PUBACK one scan late still makes it. With an 8 ms budget the
loop has time left for the PUBACK in the same scan.</li>
</ul>
@@timeline@@

<h2 id="cpu">Where the CPU goes</h2>
<div class="stats">
<div class="stat"><div class="n">8 ms</div><div class="l">to format 500 REALs into one 8 KB message (7 ms for the 1,500
BOOL and DINT); the same at both QoS levels</div></div>
<div class="stat"><div class="n">3-4 ms</div><div class="l">client time in every scan with a message in flight: the loop
runs to its budget</div></div>
<div class="stat"><div class="n">16-20 %</div><div class="l">task load on a 50 ms task, QoS 0 and QoS 1 within 0.5
points of each other</div></div>
<div class="stat"><div class="n">20-30 ms</div><div class="l">worst scan in every setup (a fast and a slow build in the
same scan); 20-27 ms with the 4 ms budget</div></div>
</div>
<p>At 10/s the formatting alone is 8 % of the CPU. That is where an optimisation would pay first (formatting fewer
digits, or sending only the values that changed), before QoS. Task load was slightly lower at QoS 1 than at QoS 0 on the
100 ms task only because it sent about 10 % fewer fast rounds.</p>

<h2 id="all">All results</h2>
<p>Per stream: rounds started against periods due; build and send time on the PLC (send: from handing the messages to
the publishers to the last <code>done</code>, and how many scans that took); age at the broker (from the PLC's UTC
timestamp in the message to its arrival, PC clock corrected by SNTP); the longest gap between rounds at the broker;
and the broker's count of missing, duplicated and wrong messages.</p>
@@details@@

<h2 id="method">Method</h2>
<ul class="prose">
<li>PLC: P2CDS-622 (32-bit, runtime 3.5.19); MQTT library 1.3.0.0 (fork). Broker: mochi 2.7.9 in the HQ bridge,
192.168.50.240:1883. Comms task 100 ms or 50 ms.</li>
<li>Client setup as recommended: up to 32 client calls a scan within <code>ClientBudgetUs</code> (4 ms, or 8 ms) while a
message is in flight, a second call of up to 2 ms at the end of the scan, publishers re-armed in the scan they report
<code>done</code>.</li>
<li>Load: the 2,000 tags of the scale test (7-9 character names), every value sent every period, not by exception.
Slow stream: 1,000 BOOL + 500 DINT once a second (17.9 KB). Fast stream: 500 REAL ten times a second (8.1 KB). Values
change every round. Each message is a header with stream, round, part and UTC time, then one <code>tag:value</code>
line per tag.</li>
<li>Layouts: one message per stream (1 + 1 publisher); 100 tags per message (15 + 5 messages, 8 + 5 publishers); 25
tags per message (60 + 20 messages, 16 + 20 publishers).</li>
<li>Scheduling on a fixed time grid. When a period falls due while the stream's previous round is still in flight,
the period is counted as skipped; a stream never queues rounds.</li>
<li>At the broker, a subscriber (QoS 1) checks every line of every message: name, value for that round, order, and
whether any part is missing or duplicated.</li>
<li>90 s per cell. Reproduce: <code>codesys-api/examples/mqtt_large_payload/mixed_rate_test.py</code> (driver and
checker), <code>show_mixed.py</code> (tables), <code>st/mixed/</code> (PLC side: <code>MixedTest</code>,
<code>FB_MixedStream</code>); results in <code>results/exp/qos_mixed/</code>. Throughput of a single full refresh is
in the <a href="@@throughput@@">publish throughput report</a>.</li>
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
""".replace("@@timeline@@", TIMELINE)


if __name__ == "__main__":
    main()
