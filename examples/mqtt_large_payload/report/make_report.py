"""Generate the Doc Shelf report for the MQTT large-payload demo from the sources and result files.

Usage: python examples/mqtt_large_payload/report/make_report.py [output.html]
Publish the output with the doc-shelf skill (projects/codesys/mqtt-large-payload).
"""
import html
import json
import sys
from pathlib import Path

DEMO = Path(__file__).resolve().parents[1]
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else DEMO / "report" / "report.html"

runs = json.loads((DEMO / "results" / "performance_sweep.json").read_text())["runs"]
verify_500 = json.loads((DEMO / "results" / "verify_60s.json").read_text())
verify_1100 = json.loads((DEMO / "results" / "verify_1100_values_40s.json").read_text())
verify_sweep = json.loads((DEMO / "results" / "verify_during_sweep.json").read_text())


def st_source(name, part="all"):
    text = (DEMO / "st" / (name + ".st")).read_text(encoding="utf-8")
    declaration, implementation = text.split("// ---- implementation ----\n", 1)
    if part == "decl":
        return declaration.rstrip()
    if part == "impl":
        return implementation.rstrip()
    return declaration.rstrip() + "\n\n" + implementation.rstrip()


def code(text, lang="iecst"):
    return '<pre class="code" data-lang="%s"><code>%s</code></pre>' % (lang, html.escape(text))


def ms(us):
    return "%.1f" % (us / 1000.0)


# ---------- performance chart (inline SVG, horizontal stacked bars) ----------
def perf_chart():
    width, left, right, top, bar_h, gap = 720, 150, 30, 28, 30, 26
    scale_max = 80.0  # ms
    plot_w = width - left - right
    height = top + len(runs) * (bar_h + gap) + 40

    def x(value_ms):
        return left + plot_w * value_ms / scale_max

    parts = ['<svg class="chart" viewBox="0 0 %d %d" role="img" aria-labelledby="perf-title perf-desc">' % (width, height),
             '<title id="perf-title">Worst scan time by payload size</title>',
             '<desc id="perf-desc">Stacked bars: payload build, CONCAT comparison copy and remaining scan work, against the 50 ms task interval.</desc>']
    for tick in range(0, 81, 10):
        tx = x(tick)
        parts.append('<line class="grid" x1="%.1f" x2="%.1f" y1="%d" y2="%d"/>' % (tx, tx, top - 6, height - 32))
        parts.append('<text class="tick" x="%.1f" y="%d" text-anchor="middle">%d ms</text>' % (tx, height - 14, tick))
    budget_x = x(50)
    parts.append('<line class="budget" x1="%.1f" x2="%.1f" y1="%d" y2="%d"/>' % (budget_x, budget_x, top - 14, height - 32))
    parts.append('<text class="budget-label" x="%.1f" y="%d">50 ms task interval</text>' % (budget_x + 6, top - 4))
    for index, run in enumerate(runs):
        y = top + 6 + index * (bar_h + gap)
        build = run["MaxLargeBuildUs"] / 1000.0
        concat = run["MaxConcatBuildUs"] / 1000.0
        total = run["MaxCycleUs"] / 1000.0
        rest = max(total - build - concat, 0.0)
        label = "%d values" % run["ValueCount"]
        sub = "%.1f KB" % (run["LastLargeLength"] / 1000.0)
        parts.append('<text class="cat" x="%d" y="%.1f" text-anchor="end">%s</text>' % (left - 10, y + 13, label))
        parts.append('<text class="cat-sub" x="%d" y="%.1f" text-anchor="end">%s payload</text>' % (left - 10, y + 27, sub))
        cursor = left
        segments = [("s1", "Payload build (pointer append)", build), ("s2", "CONCAT comparison copy (demo only)", concat),
                    ("s0", "Rest of the scan", rest)]
        for css, name, value in segments:
            seg_w = plot_w * value / scale_max
            draw_w = max(seg_w - 2, 0.8)  # 2px surface gap between fills
            tip = "%s · %s: %.1f ms (worst scan %.1f ms)" % (label, name, value, total)
            parts.append('<rect class="%s mark" x="%.1f" y="%.1f" width="%.1f" height="%d" rx="3" data-tip="%s"/>'
                         % (css, cursor, y, draw_w, bar_h, html.escape(tip)))
            cursor += seg_w
        parts.append('<text class="value" x="%.1f" y="%.1f">%.1f ms</text>' % (cursor + 6, y + 20, total))
    parts.append("</svg>")
    return "\n".join(parts)


def perf_rows():
    rows = []
    for run in runs:
        late = run["MaxIntervalUs"] - 50000
        late_cell = '<span class="bad">+%.0f ms late</span>' % (late / 1000.0) if late > 2000 else '<span class="good">on time</span>'
        rows.append("<tr><td class='num'>%d</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td>"
                    "<td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='nowrap'>%s</td><td class='num'>%s</td><td class='num'>%s (%d scans)</td>"
                    "<td class='num'>%d</td></tr>" % (
                        run["ValueCount"], "{:,}".format(run["LastLargeLength"]), ms(run["MaxLargeBuildUs"]),
                        ms(run["MaxConcatBuildUs"]), ms(run["CycleUs"]), ms(run["MaxCycleUs"]), ms(run["MaxIntervalUs"]), late_cell,
                        ms(run["MaxClientUs"]), "%.0f ms" % (run["MaxPublishUs"] / 1000.0), run["MaxPublishCycles"],
                        run["TimeoutCount"]))
    return "\n".join(rows)


def perf_csv():
    header = "values,payload_bytes,build_ms,concat_copy_ms,normal_scan_ms,worst_scan_ms,max_scan_interval_ms,client_max_ms,send_to_puback_ms,send_to_puback_scans,timeouts"
    lines = [header]
    for run in runs:
        lines.append(",".join(str(v) for v in [
            run["ValueCount"], run["LastLargeLength"], ms(run["MaxLargeBuildUs"]), ms(run["MaxConcatBuildUs"]),
            ms(run["CycleUs"]), ms(run["MaxCycleUs"]), ms(run["MaxIntervalUs"]), ms(run["MaxClientUs"]),
            "%.0f" % (run["MaxPublishUs"] / 1000.0), run["MaxPublishCycles"], run["TimeoutCount"]]))
    return "\n".join(lines)


def verify_row(label, data):
    large = data["large"]
    concat = data["concat"]
    return ("<tr><td>%s</td><td class='num'>%d</td><td class='num'>%s</td><td class='num'>%s–%s</td><td>%s</td>"
            "<td>%s</td><td class='num'>%d × %s B</td></tr>" % (
                label, large["messages"], "{:,}".format(large["valuesChecked"]), "{:,}".format(large["bytesMin"]),
                "{:,}".format(large["bytesMax"]), '<span class="good">all exact</span>' if large["allExact"] else '<span class="bad">failures</span>',
                "none" if not large["sequenceGaps"] else large["sequenceGaps"], concat["messages"],
                "/".join(str(b) for b in concat["bytes"])))


ISSUES = [
    ("Demo code", "CONCAT into a STRING(8000)", "Stopped at exactly 255 characters on the PLC (LastConcatLength = 255) and on the wire (33/33 messages of 255 B, a clean prefix of the full text).",
     "Intentional control channel. The Standard library string functions return at most 255 characters; build long text with a pointer append (AppendText) instead.", "expected"),
    ("Demo code", "Local variable named <code>Mqtt</code>", "\"'QoS' is no component of 'MQTT_IN_OUT'\": ST names are case-insensitive, so the variable hid the <code>MQTT</code> library namespace.",
     "Renamed to <code>MqttLink</code>.", "fixed"),
    ("Project setup", "Application dynamic memory off", "22 × \"No memory for dynamic object creation defined for application\". The library allocates with __NEW.",
     "Application Properties › Build › dynamic memory = 100000 bytes (BCNF already has 50000). Not exposed to scripting; set through the object manager.", "fixed"),
    ("Project setup", "SysTimeGetUs from the SysTime library", "\"Identifier 'SysTimeGetUs' not defined\", \"Unknown type SYSTIME\".",
     "Add SysTimeCore and call <code>SysTimeCore.SysTimeGetUs(pUsTime := ulint)</code> qualified.", "fixed"),
    ("Tooling", "Headless build reported exit 1", "The build itself succeeded; IronPython's json failed on a euro sign in an OSCAT compiler message, and <code>__file__</code> is undefined under --runscript.",
     "ASCII-safe message text, source folder passed in an environment variable, report rewritten after every step.", "fixed"),
    ("Tooling", "Editing the project while logged in", "\"Cannot add an object because it affects a device you are currently logged into.\"",
     "Log out first; the PLC keeps running the old application meanwhile.", "fixed"),
    ("Tooling", "API <code>/plc/deploy</code>", "Logs in with OnlineChangeOption.Keep, which is meant to keep the running application, so it may not replace a different one. Not tried; the proven bench scripts do a full download instead.",
     "Used <code>login(OnlineChangeOption.Never, True)</code> (full download, delete foreign apps), then start and create the boot application.", "workaround"),
    ("Tooling", "API <code>/project/open</code>", "Refuses while another project is open; Windows backslash paths broke the JSON body from Git Bash.",
     "Close first; use forward slashes.", "workaround"),
    ("BCNF (found, not changed)", "FirstPublish completion logic", "<code>MQTTPublish.done</code> is TRUE for one scan only. FirstPublish waits for all seven pulses in the same scan; if one lands a scan later, <code>send</code> stays TRUE, no new edge is generated and publishing stops.",
     "Clear each publisher's request on its own <code>done</code> or <code>SendTimeout</code> (as the demo does).", "open"),
    ("Library warnings", "OSCAT string constant warnings", "6 warnings about an HTML-entity table too long for STRING(253) inside OSCAT.", "Harmless; not in demo code.", "expected"),
]


def issue_rows():
    labels = {"fixed": ("good", "fixed"), "workaround": ("warn", "workaround"), "expected": ("muted", "expected"), "open": ("bad", "open in BCNF")}
    rows = []
    for area, what, symptom, fix, status in ISSUES:
        css, text = labels[status]
        rows.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td><span class='pill %s'>%s</span></td></tr>" % (area, what, symptom, fix, css, text))
    return "\n".join(rows)


PUBLISH_SNIPPET = """// Rebuild only when the previous publish has finished:
// the library reads the payload through its pointer over several scans.
IF PublishTimer.Q AND MqttLink.BROKER_CONNECTED AND NOT IsLargeRequested THEN
\tLargeUsed := 0;
\tLargePayload := '';
\tIsBuildOk := TRUE;
\tFOR Index := 0 TO ValueCount + 2 DO
\t\tBuildLine();   // Line := 'DEMO_V12:5012$N' etc.; CONCAT is fine for one short line
\t\tIsBuildOk := IsBuildOk AND AppendText(pBuffer := ADR(LargePayload),
\t\t\tCapacity := SIZEOF(LargePayload), Text := Line, Used := LargeUsed);
\tEND_FOR
\tIsLargeRequested := IsBuildOk;
END_IF

LargePublisher(
\tTopic := ADR(LargeTopic),
\tPayloadString := ADR(LargePayload),   // pointer to the STRING(20000): no 255-character copy anywhere
\tPublishAsString := TRUE,
\tQoSIn := MQTT.QoS.AtLeastOnce,
\tMRetain := FALSE,
\tsend := IsLargeRequested);

// done and SendTimeout are one-scan pulses: clear this publisher's own request on either.
IF LargePublisher.done OR LargePublisher.SendTimeout THEN
\tIsLargeRequested := FALSE;
END_IF"""

DECL_SNIPPET = """VAR
\tMqttLink : MQTT.MQTT_IN_OUT;      // not "Mqtt": that would hide the MQTT namespace
\tLargePublisher : MQTT.MQTTPublish;
\tLargePayload : STRING(20000);     // size for the largest message + margin
\tLargeUsed : UDINT;                // current length, kept so appends never rescan the buffer
\tLine : STRING(80);
END_VAR

MqttLink.ClientID := 'BENCH_MQTT_DEMO';
MqttLink.clientFB(MQTT_IN_OUT := MqttLink, ENABLE := TRUE, URL := '192.168.50.240:1883',
\tTIMEOUT := T#10S, TLS := FALSE);
// once: LargePublisher.SetMqttInOut(MQTT_IN_OUT := MqttLink);"""

LIBRARY_SNIPPET = """// MqttPublish (MQTT 1.2.0.7), string payloads:
MyOutData.PaketData.MqttPayloadLength := CommonTypesAndFunctions.LEN(PayloadString);
MyOutData.PaketData.MqttPayload := PayloadString;

// CommonTypesAndFunctions.len: counts bytes up to the terminating zero, no 255 limit
pt := str;
WHILE pt[k] <> 0 DO
\tk := k + 1;
END_WHILE
len := k;

// MqttClient.BuildPublishPaket copies the payload into the TCP buffer in pieces
InsertSplitPayload(payload := PaketData^.MqttPayload, len := PaketData^.MqttPayloadLength, ...);"""

BCNF_SNIPPET = """FUNCTION_BLOCK FirstPublish
VAR_INPUT
\tInterlockData1 : STRING(255);   // every payload passes through a 255-character copy
\t...
// FB_InterlockMatrix.StringPublication
BCNF_ANALOG_STRING := CONCAT(BCNF_ANALOG_STRING, REAL_TO_STRING(...));   // CONCAT caps at 255"""

PROMPT = """Apply the MQTT large-payload pattern from examples/mqtt_large_payload (codesys-api repo) to the BCNF PLC project (PLC_BCNF_4_16_26.project):
1. Add the AppendText function and replace the CONCAT-built BCNF_*_STRING payloads with one STRING(n) buffer per message built by AppendText.
2. Pass ADR(buffer) to MQTT.MQTTPublish (PublishAsString := TRUE); remove the STRING(255) inputs of FirstPublish.
3. Clear each publisher's request on its own done or SendTimeout instead of waiting for all done pulses in one scan.
4. Move the payload build and publish into a separate lower-priority task (e.g. 100 ms) that copies a snapshot of the values first.
5. Verify on the bench with verify_payloads.py and measure with the PLC_PRG performance counters before deploying to site."""


def build_html():
    s500, s1100 = verify_500, verify_1100
    payload = {
        "performance": runs,
        "verification": {"500_values_60s": s500, "1100_values_40s": s1100, "sweep_170s": verify_sweep},
    }
    values = dict(
        chart=perf_chart(),
        perf_rows=perf_rows(),
        verify_rows="\n".join([
            verify_row("500 values, 60 s", s500),
            verify_row("1,100 values, 40 s", s1100),
            verify_row("Sweep 50 / 500 / 1,100, 170 s", verify_sweep),
        ]),
        issue_rows=issue_rows(),
        append_text=code(st_source("AppendText")),
        decl_snippet=code(DECL_SNIPPET),
        publish_snippet=code(PUBLISH_SNIPPET),
        build_line=code(st_source("PLC_PRG.BuildLine", "impl")),
        now_us=code(st_source("NowUs")),
        library_snippet=code(LIBRARY_SNIPPET),
        bcnf_snippet=code(BCNF_SNIPPET),
        csv_json=html.escape(json.dumps(perf_csv())),
        results_json=html.escape(json.dumps(json.dumps(payload, indent=1))),
        prompt_json=html.escape(json.dumps(PROMPT)),
        total_values="{:,}".format(s500["large"]["valuesChecked"] + s1100["large"]["valuesChecked"] + verify_sweep["large"]["valuesChecked"]),
        total_messages=s500["large"]["messages"] + s1100["large"]["messages"] + verify_sweep["large"]["messages"],
    )
    text = TEMPLATE
    for key, value in values.items():
        text = text.replace("@@%s@@" % key, str(value))
    assert "@@" not in text, "unfilled placeholder"
    return text


TEMPLATE = (Path(__file__).resolve().parent / "report_template.html").read_text(encoding="utf-8")

if __name__ == "__main__":
    OUT.write_text(build_html(), encoding="utf-8")
    print(OUT, OUT.stat().st_size, "bytes")
