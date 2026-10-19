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

RESULTS = DEMO / "results"


def load(name):
    return json.loads((RESULTS / name).read_text())


# Production benchmarks: BCNF-style two-decimal REALs, one publish a second, no CONCAT copy.
real_qos0 = load("performance_real_qos0.json")["runs"]
real_qos1 = load("performance_real_qos1.json")["runs"]
int_qos0 = load("performance_int_qos0.json")["runs"]
production_runs = real_qos0 + real_qos1 + int_qos0
# First sweep: integers every 5 s at QoS 1, with the CONCAT control copy built in the same scan.
concat_control_runs = load("performance_with_concat_control.json")["runs"]
verify_500 = load("verify_60s.json")
verify_1100 = load("verify_1100_values_40s.json")
verify_concat_sweep = load("verify_during_concat_control_sweep.json")
verify_production = load("verify_production_sweep.json")


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
def perf_chart(runs):
    width, left, right, top, bar_h, gap = 720, 150, 30, 28, 30, 26
    scale_max = 60.0  # ms
    plot_w = width - left - right
    height = top + len(runs) * (bar_h + gap) + 40

    def x(value_ms):
        return left + plot_w * value_ms / scale_max

    parts = ['<svg class="chart" viewBox="0 0 %d %d" role="img" aria-labelledby="perf-title perf-desc">' % (width, height),
             '<title id="perf-title">Worst scan time by payload size, production settings</title>',
             '<desc id="perf-desc">Stacked bars: payload build and remaining scan work, against the 50 ms task interval.</desc>']
    for tick in range(0, int(scale_max) + 1, 10):
        tx = x(tick)
        parts.append('<line class="grid" x1="%.1f" x2="%.1f" y1="%d" y2="%d"/>' % (tx, tx, top - 6, height - 32))
        parts.append('<text class="tick" x="%.1f" y="%d" text-anchor="middle">%d ms</text>' % (tx, height - 14, tick))
    budget_x = x(50)
    parts.append('<line class="budget" x1="%.1f" x2="%.1f" y1="%d" y2="%d"/>' % (budget_x, budget_x, top - 14, height - 32))
    parts.append('<text class="budget-label" x="%.1f" y="%d">50 ms task interval</text>' % (budget_x + 6, top - 4))
    for index, run in enumerate(runs):
        y = top + 6 + index * (bar_h + gap)
        build = run["MaxLargeBuildUs"] / 1000.0
        total = run["MaxCycleUs"] / 1000.0
        rest = max(total - build, 0.0)
        label = "{:,} values".format(run["ValueCount"])
        sub = "%.1f KB" % (run["LastLargeLength"] / 1000.0)
        parts.append('<text class="cat" x="%d" y="%.1f" text-anchor="end">%s</text>' % (left - 10, y + 13, label))
        parts.append('<text class="cat-sub" x="%d" y="%.1f" text-anchor="end">%s payload</text>' % (left - 10, y + 27, sub))
        cursor = left
        segments = [("s1", "Payload build", build), ("s0", "Rest of the scan", rest)]
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


TASK_INTERVAL_MS = 50


def expected_publishes(run):
    # TON(IN := NOT Q): Q is seen one scan after it fires, IN is FALSE for that scan (reset),
    # and timing restarts the scan after, so the real period is PublishPeriod + two task intervals.
    # Confirmed on the broker: 381 messages in 420 s, one per 1.10 s.
    return round(run["seconds"] * 1000 / (run["periodMs"] + 2 * TASK_INTERVAL_MS))


def timing_cell(run):
    late = run["MaxIntervalUs"] - 50000
    if late > 2000:
        return '<span class="bad">+%.0f ms late</span>' % (late / 1000.0)
    return '<span class="good">on time</span>'


def table_row(cells):
    """cells: (text, css class) pairs; class 'num' right-aligns, 'nowrap' keeps status text on one line."""
    return "<tr>%s</tr>" % "".join("<td class='%s'>%s</td>" % (css, text) for text, css in cells)


def perf_rows(runs):
    rows = []
    for run in runs:
        expected = expected_publishes(run)
        rows.append(table_row([
            (run["format"], ""), (str(run["qos"]), "num"), ("{:,}".format(run["ValueCount"]), "num"),
            ("{:,}".format(run["LastLargeLength"]), "num"), (ms(run["MaxLargeBuildUs"]), "num"),
            (ms(run["CycleUs"]), "num"), (ms(run["MaxCycleUs"]), "num"), (ms(run["MaxIntervalUs"]), "num"),
            (timing_cell(run), "nowrap"), (ms(run["MaxClientUs"]), "num"),
            ("%.0f ms (%d scans)" % (run["MaxPublishUs"] / 1000.0, run["MaxPublishCycles"]), "num"),
            ("%d / %d" % (run["sentDuringRun"], expected), "num"), (str(run["TimeoutCount"]), "num"),
        ]))
    return "\n".join(rows)


def control_rows():
    """The first sweep (CONCAT copy in the timed scan) next to production REAL/QoS 1 at the same size."""
    rows = []
    real_by_size = dict((run["ValueCount"], run) for run in real_qos1)
    for run in concat_control_runs:
        real = real_by_size.get(run["ValueCount"])
        rows.append(table_row([
            ("{:,}".format(run["ValueCount"]), "num"), (ms(run["MaxLargeBuildUs"]), "num"),
            (ms(run["MaxConcatBuildUs"]), "num"), (ms(run["MaxCycleUs"]), "num"), (timing_cell(run), "nowrap"),
            (ms(real["MaxCycleUs"]) if real else "–", "num"), (timing_cell(real) if real else "–", "nowrap"),
        ]))
    return "\n".join(rows)


def perf_csv():
    header = ("format,qos,values,payload_bytes,build_ms,sampled_scan_ms,worst_scan_ms,max_scan_interval_ms,"
              "client_max_ms,request_to_done_ms,request_to_done_scans,sent,expected,timeouts")
    lines = [header]
    for run in production_runs:
        lines.append(",".join(str(v) for v in [
            run["format"], run["qos"], run["ValueCount"], run["LastLargeLength"], ms(run["MaxLargeBuildUs"]),
            ms(run["CycleUs"]), ms(run["MaxCycleUs"]), ms(run["MaxIntervalUs"]), ms(run["MaxClientUs"]),
            "%.0f" % (run["MaxPublishUs"] / 1000.0), run["MaxPublishCycles"], run["sentDuringRun"],
            expected_publishes(run), run["TimeoutCount"]]))
    return "\n".join(lines)


def verify_row(label, data):
    large = data["large"]
    concat = data["concat"]
    concat_cell = "%d × %s B" % (concat["messages"], "/".join(str(b) for b in concat["bytes"])) if concat["messages"] else "off"
    return ("<tr><td>%s</td><td class='num'>%d</td><td class='num'>%s</td><td class='num'>%s–%s</td><td>%s</td>"
            "<td>%s</td><td class='num'>%s</td></tr>" % (
                label, large["messages"], "{:,}".format(large["valuesChecked"]), "{:,}".format(large["bytesMin"]),
                "{:,}".format(large["bytesMax"]), '<span class="good">all correct</span>' if large["allExact"] else '<span class="bad">failures</span>',
                "none" if not large["sequenceGaps"] else ", ".join(str(g) for g in large["sequenceGaps"]), concat_cell))


ISSUES = [
    ("Demo code", "CONCAT into a STRING(8000)", "Stopped at exactly 255 characters on the PLC (LastConcatLength = 255) and on the wire (all 53 control messages were 255 B, a clean prefix of the full text).",
     "Intentional control channel. The Standard library string functions return at most 255 characters; build long text with a pointer append (AppendText) instead.", "expected"),
    ("Measurement", "First timing sweep", "Built the CONCAT control copy in the same scan as the real payload, so its worst-scan numbers (74.5 ms and a 25 ms late scan at 1,100 values) included work production would never do. It also used integers instead of BCNF's REAL formatting and published every 5 s instead of every second.",
     "Control copy now off by default (<code>IsConcatControlEnabled</code>); re-measured with BCNF-style REALs, one publish a second, QoS 0 and 1. The first sweep is kept below for comparison only.", "fixed"),
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
\tFOR Index := 0 TO ValueCount + 3 DO
\t\tBuildLine();   // Line := 'DEMO_V12:50.12$N' etc.; CONCAT is fine for one short line
\t\tIsBuildOk := IsBuildOk AND AppendText(pBuffer := ADR(LargePayload),
\t\t\tCapacity := SIZEOF(LargePayload), Text := Line, Used := LargeUsed);
\tEND_FOR
\tIsLargeRequested := IsBuildOk;
END_IF

LargePublisher(
\tTopic := ADR(LargeTopic),
\tPayloadString := ADR(LargePayload),   // pointer to the STRING(30000): no 255-character copy anywhere
\tPublishAsString := TRUE,
\tQoSIn := PublishQoS,                  // AtMostOnce (BCNF today) or AtLeastOnce
\tMRetain := FALSE,
\tsend := IsLargeRequested);

// done and SendTimeout are one-scan pulses: clear this publisher's own request on either.
IF LargePublisher.done OR LargePublisher.SendTimeout THEN
\tIsLargeRequested := FALSE;
END_IF"""

DECL_SNIPPET = """VAR
\tMqttLink : MQTT.MQTT_IN_OUT;      // not "Mqtt": that would hide the MQTT namespace
\tLargePublisher : MQTT.MQTTPublish;
\tLargePayload : STRING(30000);     // size for the largest message + margin
\tLargeUsed : UDINT;                // current length, kept so appends never rescan the buffer
\tLine : STRING(80);
END_VAR

MqttLink.ClientID := 'BENCH_MQTT_DEMO';
MqttLink.clientFB(MQTT_IN_OUT := MqttLink, ENABLE := TRUE, URL := '192.168.50.240:1883',
\tTIMEOUT := T#10S, TLS := FALSE);
// once: LargePublisher.SetMqttInOut(MQTT_IN_OUT := MqttLink);"""

BCNF_TODAY_SNIPPET = """// FB_InterlockMatrix body: runs every scan of the 50 ms task
ProcessMQTTMessage();
StringPublication();

// StringPublication action: one STRING(255) per group, built with CONCAT
BCNF_ANALOG_STRING := '[BCNF_ANALOG, ';
BCNF_ANALOG_STRING := CONCAT(BCNF_ANALOG_STRING, REAL_TO_STRING(DINT_TO_REAL(TRUNC(AIT_1508_V * 100.0 + SEL(AIT_1508_V >= 0.0, -0.5, 0.5))) / 100.0));
BCNF_ANALOG_STRING := CONCAT(BCNF_ANALOG_STRING, ', ');
BCNF_ANALOG_STRING := CONCAT(BCNF_ANALOG_STRING, REAL_TO_STRING(DINT_TO_REAL(TRUNC(FIT_1506_F * 100.0 + SEL(FIT_1506_F >= 0.0, -0.5, 0.5))) / 100.0));
// ... one CONCAT pair per value, 14 values in this group ...
BCNF_ANALOG_STRING := CONCAT(BCNF_ANALOG_STRING, ']');
// ... the same for DIGITAL (9), ALARM (43), SETPOINT_1 (26), SETPOINT_2 (6), OUTPUT_OTHER (3), STATUS (2)

fullPayload_BCNF_ANALOG_STRING := BCNF_ANALOG_STRING;       // copy 1, STRING(255)

// POU1: each group is passed by value into FirstPublish
FirstPublish(InterlockData1 := call_statemachine.fullPayload_BCNF_ANALOG_STRING, ...);   // copy 2, STRING(255) input

// FirstPublish, when its 1 s timer fires
fullPayload1 := InterlockData1;                             // copy 3, STRING(255)
publisher1(Topic := ADR('raw_data'), PayloadString := ADR(fullPayload1), PublishAsString := TRUE,
\tQoSin := MQTT.QoS.AtMostOnce, MRetain := FALSE, send := readyToSend AND (LEN(fullPayload1) > 0));
// ... publisher2 to publisher7, one per group"""

LIFECYCLE_SNIPPET = """IF PublishTimer.Q AND IsBrokerConnected THEN
\tIF IsLargeRequested THEN
\t\tSkippedBusyCount := SkippedBusyCount + 1;   // previous message still in flight: leave the buffer alone
\tELSE
\t\t// ... build into LargePayload (above) ...
\t\tIsLargeRequested := IsBuildOk;              // never publish a message that didn't fit
\tEND_IF
END_IF

LargePublisher(..., PayloadString := ADR(LargePayload), send := IsLargeRequested);

IF LargePublisher.done OR LargePublisher.SendTimeout THEN
\tIsLargeRequested := FALSE;                     // the buffer may be rebuilt from the next timer tick
END_IF"""

BCNF_EXAMPLE_OUTPUT = """[BCNF_ANALOG, 7.12, 31.5, 12.04, 1.98, 2.31, 0, 0, 640.2, 18.75, 21.4, 3.2, 44.9, 31.07, 460.0]
[BCNF_DIGITAL, 0, 1, 0, 1, 1, 0, 0, 1, 1]
[BCNF_ALARM, 0, 0, 0, 0, 0, 0, 0, 0, 0, ...]
[BCNF_SETPOINT_1, 9.5, 9.0, 6.0, 6.5, ...]
[BCNF_SETPOINT_2, ...]
[BCNF_OUTPUT_OTHER, 1, 45.0, 45.0]
[BCNF_STATUS_STRING, 18234, TRUE]"""

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
    verifications = [
        ("Production sweep: REAL, QoS 0 and 1, every second", verify_production),
        ("INT, 500 values, CONCAT control on, 60 s", verify_500),
        ("INT, 1,100 values, CONCAT control on, 40 s", verify_1100),
        ("INT sweep 50 / 500 / 1,100, CONCAT control on", verify_concat_sweep),
    ]
    payload = {
        "performanceProduction": production_runs,
        "performanceFirstSweepWithConcatControl": concat_control_runs,
        "verification": dict((label, data) for label, data in verifications),
    }
    values = dict(
        chart=perf_chart(real_qos0),
        perf_rows=perf_rows(production_runs),
        control_rows=control_rows(),
        verify_rows="\n".join(verify_row(label, data) for label, data in verifications),
        concat_messages=sum(data["concat"]["messages"] for _, data in verifications),
        issue_rows=issue_rows(),
        append_text=code(st_source("AppendText")),
        bcnf_today=code(BCNF_TODAY_SNIPPET),
        lifecycle_snippet=code(LIFECYCLE_SNIPPET),
        append_group_real=code(st_source("bcnf_style/AppendGroupReal")),
        append_group_bool=code(st_source("bcnf_style/AppendGroupBool")),
        bcnf_example=code(st_source("bcnf_style/BcnfPayloadExample")),
        bcnf_example_output=code(BCNF_EXAMPLE_OUTPUT, "text"),
        decl_snippet=code(DECL_SNIPPET),
        publish_snippet=code(PUBLISH_SNIPPET),
        build_line=code(st_source("PLC_PRG.BuildLine", "impl")),
        now_us=code(st_source("NowUs")),
        library_snippet=code(LIBRARY_SNIPPET),
        bcnf_snippet=code(BCNF_SNIPPET),
        csv_json=html.escape(json.dumps(perf_csv())),
        results_json=html.escape(json.dumps(json.dumps(payload, indent=1))),
        prompt_json=html.escape(json.dumps(PROMPT)),
        total_values="{:,}".format(sum(data["large"]["valuesChecked"] for _, data in verifications)),
        total_messages="{:,}".format(sum(data["large"]["messages"] for _, data in verifications)),
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
