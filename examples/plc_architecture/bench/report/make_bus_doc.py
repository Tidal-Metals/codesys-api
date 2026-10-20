"""Build the Doc Shelf document comparing Modbus TCP and RTU through ModbusFB and the native device tree.

Usage: python examples/plc_architecture/bench/report/make_bus_doc.py [output.html]
Reads bench/results/bus/ (measure_bus.py, verify_arch.py, sweep_block_size.py, time_gateway.py and the saved
timelines) and the MQTT report's stylesheet. Publish with the doc-shelf skill (projects/codesys/modbus-interfaces).
"""
import csv
import html
import io
import json
import re
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUS = HERE.parent / "results" / "bus"
STYLE_SOURCE = HERE.parents[2] / "mqtt_large_payload" / "report" / "report_template.html"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "modbus_interfaces.html"
DATE = "2026-10-20"


def load(name):
    return json.loads((BUS / name).read_text(encoding="utf-8"))


def verify(name):
    path = BUS / ("verify_%s.json" % name)
    return json.loads(path.read_text(encoding="utf-8"))["bus"] if path.exists() else None


def rates(run, kind, skip=()):
    return dict((int(u), r) for u, r in run["simulator"][kind]["repliesPerSecond"].items() if int(u) not in skip)


def median(values):
    return statistics.median(list(values))


run = dict((p.stem, json.loads(p.read_text(encoding="utf-8"))) for p in BUS.glob("*.json")
           if not p.stem.startswith(("verify_", "block_", "bus_task", "tcp_native_dead13")))
block_tcp = load("block_size_tcp.json")["rows"]
block_pc = load("block_size_pc.json")["rows"]
timeline = load("tcp_native_dead13_timeline.json")

# ---------------------------------------------------------------- derived numbers
SERIAL_UNITS = 10                                    # the ME31 (unit 1, not simulated) polls at the same rate
fb_tcp_sat = run["fb_saturation"]["line1.perSecond"]
fb_tcp_2ms = run["native_saturation_bus2ms"]["line1.perSecond"]
fb_rtu_sat = run["fb_saturation"]["line2.perSecond"]
native_rtu_unit = median(rates(run["native_saturation"], "serial").values())
native_rtu_sat = native_rtu_unit * SERIAL_UNITS
tcp_units = (11, 12, 13, 14, 15)
native_tcp_conn = dict((u, run["tcp_native_sat_fboff"]["simulator"]["gateway"]["repliesPerSecond"][str(u)]) for u in tcp_units)
native_tcp_total = sum(native_tcp_conn.values())
native_tcp_1s = median(run["tcp_native_1s_fboff"]["simulator"]["gateway"]["repliesPerSecond"][str(u)] for u in tcp_units)
pc_10 = next(r for r in block_pc if r["registers"] == 10)["medianMs"]


def fit(points):
    (n1, t1), (n2, t2) = points[0], points[-1]
    slope = (t2 - t1) / float(n2 - n1)
    return t1 - slope * n1, slope


tcp_fb_rows = [(r["count"], r["requests"] / r["seconds"]) for r in block_tcp]
tcp_fit = fit([(n, 1000.0 / rate) for n, rate in tcp_fb_rows])
pc_fit = fit([(r["registers"], r["medianMs"]) for r in block_pc])
# Native RTU: a round is nine simulated servers with N registers plus the ME31's 6-register request.
t6 = 1000.0 / native_rtu_sat
rtu_points = [(6, t6)]
for n, name in ((30, "native_serial_block30"), (120, "native_serial_block120")):
    per_unit = median(rates(run[name], "serial").values())
    rtu_points.append((n, (1000.0 / per_unit - t6) / 9.0))
rtu_fit = fit([rtu_points[0], rtu_points[-1]])
# ModbusFB RTU sweep: the line's request rate with nine blocks at N registers and the ME31's at 6, one each per round.
fb_rtu_sweep = load("block_size_rtu_fb.json")["rows"]
fb_t6 = next(1000.0 / (r["requests"] / r["seconds"]) for r in fb_rtu_sweep if r["count"] == 6)
fb_rtu_points = [(r["count"], fb_t6 if r["count"] == 6 else (10 * 1000.0 / (r["requests"] / r["seconds"]) - fb_t6) / 9.0)
                 for r in fb_rtu_sweep]
fb_rtu_fit = fit([fb_rtu_points[0], fb_rtu_points[-1]])
rtu_wire_6 = (8 + 5 + 2 * 6) * 10 / 9.6 + 2 * 3.5 * 10 / 9.6     # request + reply + two 3.5-character gaps, 10-bit characters


def healthy_share(dead, base, kind, skip):
    return median(rates(run[dead], kind, skip).values()) / median(rates(run[base], kind, skip).values())


dead_fb_rtu = healthy_share("fb_dead", "fb_baseline", "serial", (5,))
dead_fb_tcp = healthy_share("fb_dead", "fb_baseline", "gateway", (11, 25))
dead_native_rtu = healthy_share("native_dead", "native_baseline", "serial", (5,))
silent_windows = [w for w in timeline["windows"] if w["state"] != "restored"]
restored_windows = [w for w in timeline["windows"] if w["state"] == "restored"]
dead_native_tcp_rate = median(r for w in silent_windows[1:] for u, r in w["rates"].items() if u != "13")
dead_native_tcp = dead_native_tcp_rate / median(native_tcp_conn[u] for u in tcp_units if u != 13)


def f(value, digits=1):
    return ("{:,.%df}" % digits).format(value)


def pct(value):
    return "%d%%" % round(value * 100)


# ---------------------------------------------------------------- charts
def hbar(title, rows, unit, scale_max, width=480, label_width=170, decimals=1):
    """rows: (label, css class, value, tooltip)."""
    bar_h, gap, top = 18, 10, 30
    plot_w = width - label_width - 70
    height = top + len(rows) * (bar_h + gap)
    out = ['<svg class="chart" viewBox="0 0 %d %d" style="max-width:%dpx" role="img" aria-label="%s">' % (width, height, width, html.escape(title)),
           '<text class="mini-title" x="0" y="14">%s</text>' % html.escape(title)]
    for i, (label, css, value, tip) in enumerate(rows):
        y = top + i * (bar_h + gap)
        w = max(plot_w * min(value, scale_max) / scale_max, 1.5)
        out.append('<text class="cat-sub" x="%d" y="%.1f" text-anchor="end">%s</text>' % (label_width - 6, y + 13, html.escape(label)))
        out.append('<rect class="%s mark" x="%d" y="%d" width="%.1f" height="%d" rx="3" data-tip="%s"/>' % (css, label_width, y, w, bar_h, html.escape(tip)))
        out.append('<text class="value" x="%.1f" y="%.1f">%s %s</text>' % (label_width + w + 5, y + 13, f(value, decimals), unit))
    out.append("</svg>")
    return "\n".join(out)


def stacked(title, rows, scale_max, width=980, label_width=250):
    """rows: (label, [(css, ms, name)], note)."""
    bar_h, gap, top = 20, 14, 34
    plot_w = width - label_width - 150
    height = top + len(rows) * (bar_h + gap) + 26
    out = ['<svg class="chart" viewBox="0 0 %d %d" role="img" aria-label="%s">' % (width, height, html.escape(title)),
           '<text class="mini-title" x="0" y="14">%s</text>' % html.escape(title)]
    for tick in range(0, int(scale_max) + 1, 10):
        x = label_width + plot_w * tick / scale_max
        out.append('<line class="grid" x1="%.1f" x2="%.1f" y1="%d" y2="%d"/>' % (x, x, top - 6, height - 22))
        out.append('<text class="tick" x="%.1f" y="%d" text-anchor="middle">%d ms</text>' % (x, height - 6, tick))
    for i, (label, segments, note) in enumerate(rows):
        y = top + i * (bar_h + gap)
        x = label_width
        out.append('<text class="cat-sub" x="%d" y="%.1f" text-anchor="end">%s</text>' % (label_width - 8, y + 14, html.escape(label)))
        for css, value, name in segments:
            w = plot_w * value / scale_max
            out.append('<rect class="%s mark" x="%.1f" y="%d" width="%.1f" height="%d" data-tip="%s"/>'
                       % (css, x, y, w, bar_h, html.escape("%s: %s ms" % (name, f(value)))))
            x += w
        out.append('<text class="value" x="%.1f" y="%.1f">%s ms %s</text>' % (x + 6, y + 14, f(sum(s[1] for s in segments)), html.escape(note)))
    out.append("</svg>")
    return "\n".join(out)


REGISTER_TICKS = [(n, "%d" % n) for n in (1, 25, 50, 75, 100, 125)]


def lines(title, series, x_max, y_max, y_unit, width=480, height=260, y_step=None, x_ticks=REGISTER_TICKS,
          x_label="registers per request"):
    """series: (name, css, [(x, y, tip)][, dasharray]). Linear axes, points joined."""
    left, right, top, bottom = 52, 16, 28, 34
    pw, ph = width - left - right, height - top - bottom
    out = ['<svg class="chart" viewBox="0 0 %d %d" style="max-width:%dpx" role="img" aria-label="%s">' % (width, height, width, html.escape(title)),
           '<text class="mini-title" x="0" y="14">%s (%s)</text>' % (html.escape(title), html.escape(y_unit))]
    step = y_step or y_max / 4.0
    tick = 0.0
    while tick <= y_max + 1e-9:
        y = top + ph - ph * tick / y_max
        out.append('<line class="grid" x1="%d" x2="%d" y1="%.1f" y2="%.1f"/>' % (left, left + pw, y, y))
        out.append('<text class="tick" x="%d" y="%.1f" text-anchor="end">%s</text>' % (left - 6, y + 4, f(tick, 0)))
        tick += step
    for x_tick, label in x_ticks:
        x = left + pw * x_tick / x_max
        out.append('<text class="tick" x="%.1f" y="%d" text-anchor="middle">%s</text>' % (x, height - 16, html.escape(label)))
    out.append('<text class="tick" x="%d" y="%d" text-anchor="middle">%s</text>' % (left + pw / 2, height - 2, html.escape(x_label)))
    for name, css, points, *rest in series:
        dash = ' stroke-dasharray="%s"' % rest[0] if rest and rest[0] else ""
        coords = [(left + pw * x / x_max, top + ph - ph * min(y, y_max) / y_max, tip) for x, y, tip in points]
        out.append('<polyline fill="none" stroke="var(--%s)" stroke-width="2"%s points="%s"/>' % (css, dash, " ".join("%.1f,%.1f" % (x, y) for x, y, _ in coords)))
        for x, y, tip in coords:
            out.append('<circle class="%s mark" cx="%.1f" cy="%.1f" r="%s" data-tip="%s"/>' % (css, x, y, "3" if dash else "4.5", html.escape(tip)))
    out.append("</svg>")
    legend = '<div class="legend">%s</div>' % "".join('<span style="--c: var(--%s)">%s</span>' % (s[1], html.escape(s[0])) for s in series)
    return "\n".join(out) + legend


line_rate_chart = hbar("Requests per second, one line, polled as fast as it goes", [
    ("ModbusFB TCP, 5 ms bus task", "s1", fb_tcp_sat, "ModbusFB ClientTCP, one connection to the NA111-E, 10 registers: %s req/s" % f(fb_tcp_sat)),
    ("ModbusFB TCP, 2 ms bus task", "s1", fb_tcp_2ms, "Same line, bus task at 2 ms: %s req/s" % f(fb_tcp_2ms)),
    ("Native TCP, 5 connections", "s2", native_tcp_total, "Five native servers on the NA111-E, 2 registers, 10 ms cycles: %s req/s in total" % f(native_tcp_total)),
    ("Native TCP, per connection", "s2", median(native_tcp_conn.values()), "Median of the five connections: %s req/s" % f(median(native_tcp_conn.values()))),
    ("ModbusFB RTU 9600", "s1", fb_rtu_sat, "ModbusFB ClientSerial on COM1, 6 registers: %s req/s" % f(fb_rtu_sat)),
    ("Native RTU 9600", "s2", native_rtu_sat, "Modbus_COM master on COM1, 6 registers, 10 ms cycles: %s req/s" % f(native_rtu_sat)),
], "req/s", 340, width=560, label_width=190)

fb_overhead_5 = 1000.0 / fb_tcp_sat - pc_10
fb_overhead_2 = 1000.0 / fb_tcp_2ms - pc_10
request_chart = stacked("Time per request (10 registers on TCP, 6 on RTU)", [
    ("ModbusFB TCP, 5 ms bus task", [("s0", pc_10, "gateway + RS485 + device (PC-measured)"), ("s1", fb_overhead_5, "PLC: ModbusFB state machine across bus-task cycles")], ""),
    ("ModbusFB TCP, 2 ms bus task", [("s0", pc_10, "gateway + RS485 + device (PC-measured)"), ("s1", fb_overhead_2, "PLC: ModbusFB state machine across bus-task cycles")], ""),
    ("Native TCP, each of 5 connections", [("s2", 1000.0 / median(native_tcp_conn.values()), "one connection's request cycle (2 registers)")], "(the five overlap: one every %s ms on the RS485)" % f(1000.0 / native_tcp_total)),
    ("ModbusFB RTU 9600", [("s0", rtu_wire_6, "wire time at 9600: 25 bytes + two 3.5-character gaps"), ("s1", 1000.0 / fb_rtu_sat - rtu_wire_6, "device turnaround + PLC")], ""),
    ("Native RTU 9600", [("s0", rtu_wire_6, "wire time at 9600: 25 bytes + two 3.5-character gaps"), ("s2", t6 - rtu_wire_6, "device turnaround + PLC")], ""),
], 60)

block_regs_chart = lines("Registers per second vs block size", [
    ("ModbusFB TCP (115200 behind the NA111-E)", "s1", [(n, n * r, "%d registers: %s req/s, %s registers/s" % (n, f(r), f(n * r, 0))) for n, r in tcp_fb_rows]),
    ("ModbusFB RTU 9600", "s3", [(n, n * 1000.0 / t, "%d registers: %s ms per request, %s registers/s" % (n, f(t), f(n * 1000.0 / t, 0))) for n, t in fb_rtu_points]),
    ("Native RTU 9600", "s2", [(n, n * 1000.0 / t, "%d registers: %s ms per request, %s registers/s" % (n, f(t), f(n * 1000.0 / t, 0))) for n, t in rtu_points]),
], 125, 2800, "registers/s", y_step=700)
block_time_chart = lines("Time per request vs block size", [
    ("ModbusFB TCP", "s1", [(n, 1000.0 / r, "%d registers: %s ms" % (n, f(1000.0 / r))) for n, r in tcp_fb_rows]),
    ("PC through the gateway", "s0", [(r["registers"], r["medianMs"], "%d registers: %s ms median" % (r["registers"], f(r["medianMs"]))) for r in block_pc]),
    ("ModbusFB RTU 9600", "s3", [(n, t, "%d registers: %s ms" % (n, f(t))) for n, t in fb_rtu_points]),
    ("Native RTU 9600", "s2", [(n, t, "%d registers: %s ms" % (n, f(t))) for n, t in rtu_points]),
], 125, 300, "ms", y_step=50)

# ---------------------------------------------------------------- baud rate (ME31 parked: nine simulated units)
BAUDS = [9600, 19200, 38400, 57600, 115200]
BAUD_TICKS = [(i, "%g k" % (b / 1000.0)) for i, b in enumerate(BAUDS)]


def wire_ms(registers, baud):
    """FC03/FC04 request (8 bytes) and reply (5 + 2n) in 10-bit characters, plus two inter-frame silences
    (3.5 characters; Modbus fixes them at 1.75 ms above 19200 baud)."""
    char_ms = 10000.0 / baud
    return (13 + 2 * registers) * char_ms + 2 * (3.5 * char_ms if baud <= 19200 else 1.75)


BUS_TASK_TAGS = {5: "", 2: "_bus2ms"}                 # bus task interval -> result file suffix


def fb_baud_table(tag):
    """(baud, registers) -> ms per request, ModbusFB serial line."""
    table = {}
    for baud in BAUDS:
        name = "baud_fb_%d%s.json" % (baud, tag)
        if (BUS / name).exists():
            for row in load(name)["rows"]:
                table[(baud, row["count"])] = 1000.0 * row["seconds"] / row["requests"]
    return table


def native_baud_table(tag):
    """(baud, registers) -> ms per request, native master (nine simulated servers, replies counted by the simulator)."""
    table = {}
    for baud in BAUDS:
        for registers in (6, 120):
            name = "native_baud_%d_%d%s.json" % (baud, registers, tag)
            if (BUS / name).exists():
                total = load(name)["simulator"]["serial"]["total"]
                table[(baud, registers)] = 1000.0 / total if total else None
    return table


fb_baud, native_baud = fb_baud_table(""), native_baud_table("")
fb_baud_2, native_baud_2 = fb_baud_table("_bus2ms"), native_baud_table("_bus2ms")
native_baud_gap = native_baud_table("_bus2ms_gap2")        # TimeBetweenFrames 2 ms instead of the default 10
line_cost = dict((ms, load("line_cost_bus%dms.json" % ms)["rows"]) for ms in (5, 2))


def line_cost_us(ms):
    """Mean bus-task time per cycle: (no lines, TCP line alone, TCP + serial)."""
    rows = line_cost[ms]
    pick = lambda l1, l2: next(r["meanExecUs"] for r in rows if r["line1"] == l1 and r["line2"] == l2)
    return pick(False, False), pick(True, False), pick(True, True)


def baud_series(name, css, table, registers):
    points = [(i, table[(b, registers)], "%s, %d registers at %d baud: %s ms" % (name, registers, b, f(table[(b, registers)])))
              for i, b in enumerate(BAUDS) if table.get((b, registers))]
    return (name, css, points)


def baud_chart(registers, y_max, y_step):
    wire = dict(((b, registers), wire_ms(registers, b)) for b in BAUDS)
    series = [baud_series("ModbusFB, 5 ms bus task", "s3", fb_baud, registers),
              baud_series("ModbusFB, 2 ms bus task (dashed)", "s3", fb_baud_2, registers) + ("7 4",),
              baud_series("Native, 5 ms bus cycle", "s2", native_baud, registers),
              baud_series("Native, 2 ms bus cycle (dashed)", "s2", native_baud_2, registers) + ("7 4",),
              baud_series("Native, 2 ms cycle, 2 ms frame gap", "s1", native_baud_gap, registers),
              baud_series("Wire time (model, dotted)", "s0", wire, registers) + ("2 3",)]
    return lines("Time per %d-register request vs baud rate" % registers, [s for s in series if s[2]],
                 len(BAUDS) - 1, y_max, "ms", y_step=y_step, x_ticks=BAUD_TICKS, x_label="baud rate")


baud_charts = '<div class="multiples"><div>%s</div><div>%s</div></div>' % (baud_chart(6, 60, 10), baud_chart(120, 300, 50))
BAUD_HEAD = ["Baud", "Registers", "Wire (model)", "ModbusFB, 5 ms task", "ModbusFB, 2 ms task", "Native, 5 ms cycle",
             "Native, 2 ms cycle", "Native, 2 ms cycle, 2 ms gap"]


def cell(value, digits=1):
    return f(value, digits) if value else "-"


baud_rows = [["%d" % b, "%d" % n, cell(wire_ms(n, b)), cell(fb_baud.get((b, n))), cell(fb_baud_2.get((b, n))),
              cell(native_baud.get((b, n))), cell(native_baud_2.get((b, n))), cell(native_baud_gap.get((b, n)))]
             for n in (6, 30, 120) for b in BAUDS]
baud_rows = [r for r in baud_rows if any(c != "-" for c in r[3:])]
def gap_sentence():
    gap = native_baud_gap.get((115200, 6))
    if not gap:
        return "The run with a shorter pause is still to come."
    return ("With the pause cut to 2 ms (and the 2 ms bus cycle), native reached %s ms at 115200, within %s ms of the wire, "
            "and %s ms at 38400: the fastest serial results here. The pause gives slow devices time between requests; 2 ms "
            "suited the simulators, so check real devices before shortening it (Modbus itself only requires the 3.5-character "
            "silence)." % (f(gap), f(gap - wire_ms(6, 115200), 0), f(native_baud_gap[(38400, 6)])))


LINE_COST_HEAD = ["Bus task", "Task with no lines", "ModbusFB TCP line (NA111-E)", "ModbusFB serial line (COM1)",
                  "Both lines", "Share of the CPU, both lines"]
line_cost_rows = []
for ms in (5, 2):
    none_us, tcp_us, both_us = line_cost_us(ms)
    line_cost_rows.append(["%d ms" % ms, "%s ms" % f(none_us / 1000.0, 2), "%s ms" % f((tcp_us - none_us) / 1000.0, 2),
                           "%s ms" % f((both_us - tcp_us) / 1000.0, 2), "%s ms" % f(both_us / 1000.0, 2), pct(both_us / 1000.0 / ms)])
BAUD_CSV = ",".join(BAUD_HEAD) + "\n" + "".join(",".join(r).replace(",-", ",") + "\n" for r in baud_rows)

dead_chart = hbar("Healthy devices' poll rate while one device on the same bus is dead", [
    ("ModbusFB RTU (1 s periods)", "s1", dead_fb_rtu * 100, "Units 2-10 except 5: %s of their normal rate" % pct(dead_fb_rtu)),
    ("ModbusFB TCP (1 s periods)", "s1", dead_fb_tcp * 100, "Gateway units except 25: %s of their normal rate" % pct(dead_fb_tcp)),
    ("Native RTU (1 s cycles)", "s2", dead_native_rtu * 100, "Units 2-10 except 5: %s of their normal rate" % pct(dead_native_rtu)),
    ("Native TCP (10 ms cycles)", "s2", dead_native_tcp * 100, "Units 11-15 except 13: %s req/s instead of %s" % (f(dead_native_tcp_rate), f(median(native_tcp_conn.values())))),
], "%", 100, width=560, label_width=190, decimals=0)

# ---------------------------------------------------------------- run table
RUNS = [
    ("fb_baseline", "ModbusFB TCP + ModbusFB RTU", "1 s periods"),
    ("fb_saturation", "ModbusFB TCP + ModbusFB RTU", "periods 0 (as fast as possible)"),
    ("fb_dead", "ModbusFB TCP + ModbusFB RTU", "1 s, units 25 and 5 silent"),
    ("native_baseline", "ModbusFB TCP + native RTU", "1 s periods / cycles"),
    ("native_saturation", "ModbusFB TCP + native RTU", "periods 0 / 10 ms cycles"),
    ("native_dead_nohold", "ModbusFB TCP + native RTU", "1 s, units 25 and 5 silent, health = xError"),
    ("native_dead", "ModbusFB TCP + native RTU", "1 s, units 25 and 5 silent, 2.5 s hold-off"),
    ("native_saturation_bus2ms", "ModbusFB TCP + native RTU", "saturation, bus task 2 ms"),
    ("tcp_native_1s_fboff", "native TCP (5 servers)", "1 s cycles, ModbusFB line off"),
    ("tcp_native_1s_fbon", "native TCP + ModbusFB TCP", "1 s cycles and periods"),
    ("tcp_native_sat_fboff", "native TCP (5 servers)", "10 ms cycles, ModbusFB line off"),
    ("tcp_native_sat_fbon", "native TCP + ModbusFB TCP", "10 ms cycles, periods 0"),
]
HEAD = ["Run", "Interfaces", "Setting", "Gateway replies/s", "Serial replies/s (sim units)", "ModbusFB TCP req/s",
        "Control mean exec ms", "Control max deviation ms", "Bus task max exec ms", "Broker values (min-max match)"]
table_rows = []
for name, interfaces, setting in RUNS:
    r = run[name]
    v = verify(name)
    serial = r["simulator"]["serial"]["total"] if not name.startswith("tcp_") else None
    table_rows.append([name, interfaces, setting, f(r["simulator"]["gateway"]["total"]), f(serial) if serial is not None else "-",
                       f(r.get("line1.perSecond", 0)), f(r["control.MeanExecUs"] / 1000.0, 2), f(r["control.MaxDeviationUs"] / 1000.0, 2),
                       f(r["busTask.MaxExecUs"] / 1000.0, 2), "%d-%d of 304" % (v["minMatch"], v["maxMatch"]) if v else "-"])
NUMERIC = set(range(3, 9))


def table_html(head, rows, numeric=(), table_id=""):
    out = ['<div class="table-wrap"><table class="compact"%s><thead><tr>' % (' id="%s"' % table_id if table_id else "")]
    out += ['<th%s>%s</th>' % (' class="num"' if i in numeric else "", html.escape(h)) for i, h in enumerate(head)]
    out.append("</tr></thead><tbody>")
    for row in rows:
        out.append("<tr>" + "".join('<td%s>%s</td>' % (' class="num"' if i in numeric else "", c) for i, c in enumerate(row)) + "</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


buffer = io.StringIO()
writer = csv.writer(buffer)
writer.writerow(HEAD)
writer.writerows(table_rows)
CSV = buffer.getvalue()
BLOCK_CSV = "interface,registers,ms_per_request,registers_per_second\n" + "".join(
    ["ModbusFB TCP,%d,%.1f,%.0f\n" % (n, 1000.0 / r, n * r) for n, r in tcp_fb_rows]
    + ["PC via gateway,%d,%.1f,%.0f\n" % (r["registers"], r["medianMs"], r["registers"] * 1000.0 / r["medianMs"]) for r in block_pc]
    + ["ModbusFB RTU 9600,%d,%.1f,%.0f\n" % (n, t, n * 1000.0 / t) for n, t in fb_rtu_points]
    + ["Native RTU 9600,%d,%.1f,%.0f\n" % (n, t, n * 1000.0 / t) for n, t in rtu_points])
PROMPT = ("Plan the Modbus side of a CODESYS P2CDS-622 program from the bench rules in docs/modbus-bench.md and the "
          "Doc Shelf report projects/codesys/modbus-interfaces: one ModbusFB ClientTCP per gateway when more units sit behind "
          "it than it accepts TCP connections; native servers only where the connection count allows; RTU reads merged into "
          "blocks across gaps shorter than ~%d registers at 9600 baud; every native server's health held off %s ms after "
          "an error. List each line, its devices, blocks, periods and the expected line load against the measured limits."
          % (round(rtu_fit[0] / rtu_fit[1]), "2500"))

# ---------------------------------------------------------------- page
TOPOLOGY = """
<svg class="diagram chart" viewBox="0 0 980 360" role="img" aria-label="The four ways the PLC reaches Modbus devices">
<defs><marker id="arrowhead" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="var(--accent)"/></marker></defs>
@@PANELS@@
</svg>"""


def panel(x, y, title, plc_lines, link, middle, middle_sub, connections, devices_note):
    out = ['<g transform="translate(%d,%d)">' % (x, y),
           '<text x="0" y="16" style="font-weight:650">%s</text>' % html.escape(title),
           '<rect class="box" x="0" y="30" width="170" height="104" rx="8"/>']
    for i, text in enumerate(plc_lines):
        out.append('<text x="10" y="%d" class="%s">%s</text>' % (52 + i * 18, "" if i == 0 else "sub", html.escape(text)))
    if middle:
        offsets = [82] if connections == 1 else [50 + i * 16 for i in range(connections)]
        for off in offsets:
            out.append('<path class="arrow" d="M170,%d L238,%d"/>' % (off, off))
        out.append('<text class="sub" x="174" y="%d">%s</text>' % (145, html.escape(link)))
        out.append('<rect class="box" x="240" y="44" width="110" height="76" rx="8"/>')
        out.append('<text x="250" y="72">%s</text><text class="sub" x="250" y="92">%s</text>' % (html.escape(middle), html.escape(middle_sub)))
        bus_x = 350
    else:
        out.append('<text class="sub" x="174" y="%d">%s</text>' % (145, html.escape(link)))
        bus_x = 170
    out.append('<line x1="%d" y1="82" x2="460" y2="82" style="stroke:var(--s2);stroke-width:3"/>' % bus_x)
    for i in range(4):
        dx = bus_x + 18 + i * (440 - bus_x - 18) / 3.5
        out.append('<line x1="%.0f" y1="82" x2="%.0f" y2="100" style="stroke:var(--s2);stroke-width:2"/>' % (dx, dx))
        out.append('<rect class="cell" x="%.0f" y="100" width="20" height="16" rx="3"/>' % (dx - 10))
    out.append('<text class="sub" x="%d" y="72">RS485</text>' % (bus_x + 8))
    out.append('<text class="sub" x="%d" y="134">%s</text>' % (bus_x + 8, html.escape(devices_note)))
    out.append("</g>")
    return "\n".join(out)


panels = "\n".join([
    panel(0, 0, "ModbusFB over TCP", ["PLC bus task", "FB_BusLine", "ModbusFB.ClientTCP", "unit id per request"],
          "one TCP connection, any number of units", "Gateway", "NA111-E / NE2", 1, "units 11-40"),
    panel(500, 0, "Native over TCP", ["Device tree", "Ethernet (et1)", "Modbus_TCP_Client", "one server per unit"],
          "a TCP connection per server (NA111-E: 6)", "Gateway", "NA111-E / NE2", 5, "units 11-15"),
    panel(0, 180, "ModbusFB over RTU", ["PLC bus task", "FB_BusLine", "ModbusFB.ClientSerial", "COM1 (RJ12)"],
          "the PLC's own serial port", None, None, 1, "ME31 + units 2-10"),
    panel(500, 180, "Native over RTU", ["Device tree", "Modbus_COM (COM1)", "Modbus_Client_COM_Port", "one server per unit"],
          "the PLC's own serial port", None, None, 1, "ME31 + units 2-10"),
])

style = re.search(r"<style>.*?</style>", STYLE_SOURCE.read_text(encoding="utf-8"), re.S).group(0)
style = style.replace("</style>", "svg .s0 { fill: var(--s0); }\n.proscons { grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); }\n.verdict td:first-child { font-weight: 600; white-space: nowrap; }\n</style>")

page = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Modbus TCP and RTU on the CODESYS PLC: ModbusFB vs the native device tree</title>
@@STYLE@@
</head><body>
<header>
  <h1>Modbus TCP and RTU on the CODESYS PLC: ModbusFB vs the native device tree</h1>
  <p class="meta">@@DATE@@ · Bench measurements on the P2CDS-622 (CODESYS V3.5 SP22), NA111-E gateway, PLC RS485 port, Go RTU simulators</p>
  <p class="meta">How fast each way of reaching Modbus devices runs, what it costs the control task, what a dead device does to its neighbours, and which to use when.</p>
</header>
<nav class="toc"><ul>
  <li><a href="#summary">Summary</a></li><li><a href="#four">The four interfaces</a></li><li><a href="#speed">Line speed</a></li>
  <li><a href="#blocks">Block reads</a></li><li><a href="#baud">Baud rate</a></li><li><a href="#cycle">Cycle-time impact</a></li><li><a href="#dead">Dead devices</a></li>
  <li><a href="#limits">Device limits</a></li><li><a href="#proscons">Pros and cons</a></li><li><a href="#choose">Which to use</a></li>
  <li><a href="#data">All runs</a></li><li><a href="#method">Method</a></li>
</ul></nav>
<main>

<section id="summary">
<div class="tldr"><strong>Summary</strong><ul>
  <li><strong>On RTU, baud rate helps until the PLC's task becomes the limit.</strong> At 9600 a 6-register read takes @@T6@@-@@FB5_9600@@ ms, about @@WIRE_9600@@ ms of it on the wire, so a line carries about 20 small requests a second. Above 38400 both interfaces hit a floor set by the PLC: @@FB5_115200@@ ms (ModbusFB) and @@NAT5_115200@@ ms (native) at 115200 with a 5 ms bus task, where the wire needs @@WIRE_115200@@ ms. A 2 ms bus task brings ModbusFB down to @@FB2_115200@@ ms; native, with its 10 ms pause between requests (<code>TimeBetweenFrames</code>) cut to 2 ms as well, reached @@NATG_115200@@ ms.</li>
  <li><strong>ModbusFB over TCP is bound by the PLC's task, not the device.</strong> The gateway answers a 10-register read in @@PC10@@ ms from a PC; through ModbusFB it takes @@FB_REQ@@ ms, because each request spans about five bus-task cycles. One connection peaks at @@FB_TCP@@ req/s with a 5 ms bus task, and @@FB_TCP2@@ with a 2 ms task.</li>
  <li><strong>Native TCP is much faster per connection</strong> (@@NATIVE_CONN@@ req/s each, @@NATIVE_TCP@@/s for five), but needs one TCP connection per device. The NA111-E accepts six, so it can't reach 30 units behind one gateway.</li>
  <li><strong>Read big blocks.</strong> On TCP, a 125-register read takes less than twice as long as a 1-register read (@@BLK1@@ → @@BLK125@@ ms) and moves @@BLK_GAIN@@ times as many registers per second. On 9600 RTU, each register adds @@RTU_SLOPE@@ ms, so merge reads across gaps shorter than about @@GAP@@ registers.</li>
  <li><strong>Dead devices are where the two differ most.</strong> ModbusFB backs off a failed device: its neighbours kept @@DEAD_FB_RTU@@ (RTU) and @@DEAD_FB_TCP@@ (TCP) of their poll rate. Native retries every cycle and waits the full timeout each time: neighbours fell to @@DEAD_NATIVE_RTU@@ on RTU, and to @@DEAD_NATIVE_TCP@@ behind a gateway at 10 ms cycles. Native's <code>xError</code> also clears on every retry, so health needs a hold-off.</li>
  <li><strong>Control is safe in every run.</strong> The 50 ms, priority 1 control task's worst-case start deviation stayed under 2 ms. Native TCP at full speed raised its mean execution time from 4.1 to 4.8 ms.</li>
</ul></div>
</section>

<section id="four">
<h2>The four interfaces</h2>
<p>A device is reached over TCP (directly, or through an RS485 gateway such as the NA111-E or NE2) or over RTU on the PLC's own RS485 port. Either way, the polling can be written as application code with the ModbusFB library, as the architecture skeleton's <code>FB_BusLine</code> does, or configured in the IDE's device tree, where CODESYS polls each server's channels itself.</p>
<figure>@@TOPOLOGY@@<figcaption>The bench: 30 simulated units behind the NA111-E (RS485 115200), and the real Ebyte ME31 plus 9 simulated units on the PLC's RJ12 port (COM1, 9600 8N1). Native TCP was measured with five servers, since the ModbusFB line already holds one of the gateway's six connections.</figcaption></figure>
<p>Both styles feed the same decode table. A native server's channel is mapped word by word to a variable, and a small program in the bus task (<code>PRG_NativeSerial</code>) passes that image through <code>F_BusDecode</code>, the same decode the ModbusFB line uses. Tags, scaling, sentinels and quality are therefore identical; only the transport differs.</p>
</section>

<section id="speed">
<h2>Line speed</h2>
<p>Each line was polled as fast as it would go: ModbusFB block periods set to 0, native channel cycles to 10 ms. Rates are counted by the simulators (replies per unit per second), so both styles are measured the same way.</p>
<figure>@@LINE_RATE@@<figcaption>Native TCP read 2 registers per request and ModbusFB TCP read 10; at 1 register, ModbusFB TCP reaches @@BLK1_RATE@@ req/s, so the difference is the transport, not the block size.</figcaption></figure>
<figure>@@REQUEST@@<figcaption>Where one request's time goes. The grey part is outside the PLC: measured from a PC for TCP, computed from the wire format for RTU (10-bit characters at 9600 baud, two 3.5-character silences).</figcaption></figure>
<p><strong>ModbusFB's per-request cost is a number of task cycles.</strong> Its client and request blocks move through several states (send, wait, receive, done, and the falling edge before the next request), and each transition waits for the next call. That was about five bus-task cycles here: about @@FB_OVH5@@ ms at a 5 ms task and @@FB_OVH2@@ ms at 2 ms. The September test of one ModbusFB connection to ten units showed the same: 0.70 s per round with a 5 ms task, 4.04 s with a 50 ms task. To make a ModbusFB TCP line faster, shorten the bus task (and pay for it in CPU, see below) or split the devices over more connections.</p>
<p><strong>The native client does not wait for the application's task.</strong> Its TCP connections run in the Ethernet node's own asynchronous task. Five of them kept the gateway's RS485 side busy: @@NATIVE_TCP@@ replies a second is one every @@NATIVE_SPACING@@ ms, about the wire time of a 2-register exchange at 115200. On RTU at 9600, native was @@NATIVE_GAIN@@ faster than ModbusFB at saturation; how both behave at higher baud rates and with a faster bus task is under <a href="#baud">Baud rate</a>.</p>
<div class="callout"><strong>The bench's own adapters had to be fixed first.</strong> Both USB-RS485 adapters had the FTDI default latency timer of 16 ms, which held every short frame in the adapter, so the simulated devices answered about 16 ms late. At 1 ms (set 2026-10-20, <code>bench/set_ftdi_latency.ps1</code>) the RTU line's request time fell from 64 to 49 ms. Any PC-side Modbus simulator or tool on an FTDI adapter needs the same setting, or it measures the adapter.</div>
</section>

<section id="blocks">
<h2>Block reads</h2>
<p>A request costs a fixed amount plus a little per register. Fitting the measured points:</p>
<div class="table-wrap"><table class="compact"><thead><tr><th>Path</th><th class="num">Fixed per request</th><th class="num">Per register</th><th class="num">Merge reads across gaps shorter than</th></tr></thead><tbody>
<tr><td>ModbusFB TCP through the NA111-E (5 ms bus task)</td><td class="num">@@TCP_A@@ ms</td><td class="num">@@TCP_B@@ ms</td><td class="num">always (125 max)</td></tr>
<tr><td>PC through the NA111-E (no PLC task)</td><td class="num">@@PC_A@@ ms</td><td class="num">@@PC_B@@ ms</td><td class="num">about @@PC_GAP@@ registers</td></tr>
<tr><td>ModbusFB RTU at 9600 baud (5 ms bus task)</td><td class="num">@@FBRTU_A@@ ms</td><td class="num">@@FBRTU_B@@ ms</td><td class="num">about @@FBRTU_GAP@@ registers</td></tr>
<tr><td>Native RTU at 9600 baud</td><td class="num">@@RTU_A@@ ms</td><td class="num">@@RTU_SLOPE@@ ms</td><td class="num">about @@GAP@@ registers</td></tr>
</tbody></table></div>
<div class="multiples"><div>@@BLOCK_REGS@@</div><div>@@BLOCK_TIME@@</div></div>
<p>On TCP the per-request overhead dominates, so a block of 125 registers moves @@BLK125_REGS@@ registers a second where single-register reads move @@BLK1_RATE@@. On RTU the wire time per register is real (2 bytes, about 2.1 ms at 9600), so reading unused registers is only worth it across small gaps: a gap costs its wire time, a separate request costs about @@RTU_A@@ ms.</p>
<p>On RTU, ModbusFB and native land close together: ModbusFB is about @@FBRTU_EXTRA@@ ms slower per request at every block size. That isn't because its task overhead disappears on a slow line; it still spends about @@FB_OVH_RTU5@@ ms per request above wire time, as the <a href="#baud">baud-rate runs</a> show. Native pays a cost of its own: its master pauses 10 ms (<code>TimeBetweenFrames</code>) after every request.</p>
<ul>
  <li>Group a device's points into as few contiguous blocks as its register map allows. The generator should merge across gaps below the threshold for that line's baud rate.</li>
  <li>Check each device's limits before merging: many devices cap a read below 125 registers, and some refuse a read that touches an undefined register. The bench simulator ignored such a read entirely (no reply, a timeout), which is the worst case.</li>
  <li>Polling rate per block matters as much as size: a block every 1 s on a 9600 line takes about @@RTU_LOAD@@ of that line's time for 6 registers.</li>
  <li>In the native device tree, a channel's length and cycle are fixed at download. Changing a channel's length through the API's channel PATCH left its I/O image at the old size; that server then went silent with no error flag. Recreate the server instead (<code>modbus_device_driver_runner.py</code>).</li>
</ul>
</section>

<section id="baud">
<h2>Baud rate</h2>
<p>The serial line ran at 9600 to 115200 baud against the nine simulated units, every block polled back to back. The ME31, fixed at 9600, was parked (not polled) for these runs. ModbusFB changes rate online; native needs a download per rate. Each interface was measured with the bus task at 5 ms and at 2 ms.</p>
<figure>@@BAUD_CHARTS@@<figcaption>Time per request; lower is faster. The dotted line is the wire alone: request and reply at 10 bits per character plus the two inter-frame silences Modbus requires (3.5 characters, fixed at 1.75 ms above 19200 baud).</figcaption></figure>
<ul>
  <li><strong>Raising the baud rate pays off until the PLC becomes the limit.</strong> With a 5 ms bus task, a 6-register read falls from @@FB5_9600@@ ms at 9600 to @@FB5_57600@@ ms at 57600 and then stops: at 115200 the wire needs @@WIRE_115200@@ ms, and the request still takes @@FB5_115200@@ ms with ModbusFB and @@NAT5_115200@@ ms native.</li>
  <li><strong>Big blocks keep gaining,</strong> because their wire time is what shrinks: 120 registers take @@FB5_120_9600@@ ms at 9600 and @@FB5_120_115200@@ ms at 115200.</li>
  <li><strong>A 2 ms bus task moves ModbusFB's floor,</strong> to @@FB2_115200@@ ms at 115200, and helps at 9600 too (@@FB2_9600@@ instead of @@FB5_9600@@ ms). ModbusFB spends about @@FB_OVH_RTU5@@ ms above wire time per request with a 5 ms task and @@FB_OVH_RTU2@@ ms with 2 ms, at every baud rate: its state changes wait for task calls even while the line is slow.</li>
  <li><strong>Native has a floor of its own.</strong> The serial master pauses <code>TimeBetweenFrames</code> after every request, 10 ms by default, on top of the Modbus silence. A 2 ms bus cycle only took native from @@NAT5_115200@@ to @@NAT2_115200@@ ms at 115200. @@GAP_SENTENCE@@</li>
  <li><strong>Before raising a line's rate,</strong> every device on it has to support that rate (the ME31 here is set to 9600), and cabling and termination matter more at 115200. Past about 38400, a shorter bus task or frame pause buys more than more baud.</li>
</ul>
@@BAUD_TABLE@@
</section>

<section id="cycle">
<h2>Cycle-time impact</h2>
<p>Three tasks: control 50 ms at priority 1 (2,000 tags, the skeleton's seven steps), bus 5 ms at priority 5 (ModbusFB lines and the native decode), MQTT 50 ms at priority 10.</p>
<div class="stats">
  <div class="stat"><div class="n">&lt; 2 ms</div><div class="l">control task's worst start deviation, every run</div></div>
  <div class="stat"><div class="n">@@BUS5@@ ms</div><div class="l">bus task per cycle at 5 ms, two ModbusFB lines (@@BUS5_PCT@@ of the CPU)</div></div>
  <div class="stat warn-stat"><div class="n">@@BUS2@@ ms</div><div class="l">bus task per cycle at 2 ms, two ModbusFB lines (@@BUS2_PCT@@ of the CPU)</div></div>
  <div class="stat warn-stat"><div class="n">+15%</div><div class="l">control execution time with native TCP at full speed (4.1 → 4.8 ms)</div></div>
</div>
<ul>
  <li><strong>The control task is protected by priority,</strong> not by how the bus is polled: worst-case deviation stayed between 1.0 and 2.0 ms in all runs, against a 50 ms period.</li>
  <li><strong>The ModbusFB TCP client is the expensive part.</strong> Switching the lines off one at a time online:</li>
</ul>
@@LINE_COST_TABLE@@
<ul>
  <li><strong>A shorter bus task costs CPU almost in proportion.</strong> Each call gets a little cheaper, but there are more of them, so 2 ms takes about @@BUS2_PCT@@ of the CPU against @@BUS5_PCT@@ at 5 ms. Decoding ten native images every cycle cost about 0.1 ms; they change at most once a second, so decoding only on change would save most of that.</li>
  <li><strong>Native polling runs outside the application tasks.</strong> The TCP client runs in the Ethernet node's async task; the serial master's I/O is updated in the bus cycle task (the PLC's "bus cycle task" setting, which defaults to the shortest cyclic task). At full speed the native TCP client took visible time from the control task. Keep native cycle times as long as the process allows.</li>
  <li><strong>ModbusFB's speed is tied to the bus task interval</strong> (about five cycles per request). The native serial master's is partly: it exchanges data in the bus cycle task, and pauses <code>TimeBetweenFrames</code> after every request (see <a href="#baud">Baud rate</a>).</li>
</ul>
</section>

<section id="dead">
<h2>Dead devices</h2>
<figure>@@DEAD@@<figcaption>One silent device (no reply at all) on a line. ModbusFB: three failures make the device COMM_FAIL, then it is polled every 5 s. Native: polled every cycle; each poll waits the full 500 ms response timeout.</figcaption></figure>
<ul>
  <li><strong>Behind a gateway, separate TCP connections do not isolate devices.</strong> All units share the gateway's one RS485 port, and the gateway waits out the dead unit's timeout on every poll. With unit 13 silent, the other four native servers fell from about @@NATIVE_CONN@@ to @@DEAD_NATIVE_TCP_RATE@@ requests a second; they returned to @@RESTORED@@ as soon as unit 13 answered again.</li>
  <li><strong>Native health flaps.</strong> With auto-restart on, a dead server's <code>xError</code> clears at every retry: unit 5 was in error in @@ERROR_SHARE@@ of bus cycles, and in 40 live samples the control task saw it healthy, with its last values passing as current, about a third of the time. Treating a server as healthy only after 2.5 s without an error fixed it: in the repeat run, no published message carried a dead unit's values. ModbusFB has a smaller window of its own: three failed polls (about 3 s at a 1 s period) pass before a device goes COMM_FAIL, so the first message after a failure can still carry its last values.</li>
  <li><strong>ModbusFB knows when a reply arrived.</strong> Health follows replies (three failures, then a 5 s back-off), and each block's last good time is a real reply time. The device tree gives neither, so freshness has to be inferred from the error flag.</li>
  <li><strong>Recovery.</strong> Both recovered as soon as the device answered. Once, after a simulator restart with a unit silent, all five native TCP servers stopped for about two minutes and then resumed; the timed repeat did not show it.</li>
  <li><strong>Defaults that stop polling for good:</strong> the native serial master's <code>Auto-restart communication</code> and the TCP client's <code>AutoReconnect</code> are both FALSE by default. With them off, one timeout stops the master until the next download.</li>
</ul>
</section>

<section id="limits">
<h2>Device limits</h2>
<div class="table-wrap"><table class="compact"><thead><tr><th>Item</th><th>Limit</th><th>Consequence</th></tr></thead><tbody>
<tr><td>NA111-E gateway</td><td>6 TCP client connections; a 7th is accepted, then closed</td><td>At most 6 native TCP servers per gateway, fewer if a SCADA or a PC tool also connects. ModbusFB needs one.</td></tr>
<tr><td>NE2-D11P gateway</td><td>10 connections (5 on socket A, 5 on B)</td><td>Same rule. Its cached "configurable gateway" mode can report a silent unit's old values as valid unless keep time ≤ 1 s.</td></tr>
<tr><td>Native Modbus TCP server</td><td>One TCP connection and one unit id per server</td><td>30 units behind one gateway can't each be a native server; use ModbusFB, or several gateways.</td></tr>
<tr><td>Gateway RS485 side</td><td>One request at a time</td><td>More TCP connections fill the serial bus faster but share its time; one dead unit slows all of them.</td></tr>
<tr><td>PLC serial port</td><td>One master per port</td><td>A port is either a ModbusFB ClientSerial or a native Modbus_COM, never both. On the bench unit the terminal-block port (COM2) can't receive; the RJ12 port (COM1) works.</td></tr>
<tr><td>RS485 at 9600 baud</td><td>about 20 small requests/s; @@RTU_MAX@@ registers/s with full blocks (at 115200: @@RTU115_RATE@@ small requests/s, bound by the bus task)</td><td>10 devices at a 1 s poll use half a line. Raise the baud rate where devices allow it.</td></tr>
<tr><td>Modbus read size</td><td>125 registers (FC03/FC04)</td><td>Devices often allow less; test each one.</td></tr>
<tr><td>Native channel</td><td>Length and cycle fixed at download; one mapping per word</td><td>No online tuning. The API's mapping call covers one word (<code>leafIndex</code>); mapping a 6-word channel takes six calls.</td></tr>
<tr><td>ModbusFB request blocks</td><td>One request in flight per client; a falling edge of <code>xExecute</code> between requests</td><td>Throughput set by task cycles per request, about five here.</td></tr>
</tbody></table></div>
</section>

<section id="proscons">
<h2>Pros and cons</h2>
<div class="proscons">
<div><h3>ModbusFB over TCP</h3><ul>
  <li class="good-li">One connection for any number of units behind a gateway.</li>
  <li>Health per reply: COMM_FAIL after three failures, 5 s back-off; a dead device cost its neighbours @@DEAD_FB_TCP_LOSS@@.</li>
  <li>Periods, enable and connection settings change online.</li>
  <li>Generated from tables: no device tree, no I/O mapping.</li>
  <li><strong>Con:</strong> about five bus-task cycles per request: @@FB_TCP@@ req/s at 5 ms, @@FB_TCP2@@ at 2 ms.</li>
  <li><strong>Con:</strong> application code to own and test (scheduling, reconnection, decode).</li>
</ul></div>
<div><h3>Native over TCP</h3><ul>
  <li>Fast: @@NATIVE_CONN@@ req/s per connection, independent of the application's tasks.</li>
  <li>Visible in the device tree, with the IDE's diagnostics; no polling code.</li>
  <li><strong>Con:</strong> one connection per unit: 6 per NA111-E, 10 per NE2.</li>
  <li><strong>Con:</strong> no back-off: a dead unit behind a gateway took its neighbours to @@DEAD_NATIVE_TCP@@ at 10 ms cycles.</li>
  <li><strong>Con:</strong> <code>xError</code> describes the last poll only; needs a hold-off. <code>AutoReconnect</code> off by default.</li>
  <li><strong>Con:</strong> at full speed it took about 15% more of the control task's time.</li>
</ul></div>
<div><h3>ModbusFB over RTU</h3><ul>
  <li>Same table-driven code and health as the TCP lines.</li>
  <li>A dead device cost its neighbours @@DEAD_FB_RTU_LOSS@@.</li>
  <li>Periods change online.</li>
  <li>With a 2 ms bus task it beats native's default settings at every baud rate measured (@@FB2_115200@@ vs @@NAT2_115200@@ ms at 115200).</li>
  <li><strong>Con:</strong> with a 5 ms bus task, @@NATIVE_GAIN@@ slower than native at 9600 (@@FB_RTU@@ vs @@NATIVE_RTU@@ req/s); periods run from the end of the last reply, so a 1 s block polls every ~1.06 s.</li>
</ul></div>
<div><h3>Native over RTU</h3><ul>
  <li>Faster than ModbusFB with a 5 ms bus task: @@NATIVE_RTU@@ req/s at 9600, @@NAT5_115200@@ vs @@FB5_115200@@ ms per request at 115200.</li>
  <li><strong>Con:</strong> <code>TimeBetweenFrames</code> (10 ms by default) pauses after every request, which sets its floor at high baud rates. Cut to 2 ms with a 2 ms bus cycle, native was the fastest serial interface measured (@@NATG_115200@@ ms at 115200).</li>
  <li>Fixed-rate cycles (0.99 polls/s at 1 s).</li>
  <li>The shop's usual way; familiar in the field.</li>
  <li><strong>Con:</strong> a dead device cost its neighbours @@DEAD_NATIVE_RTU_LOSS@@ of their rate (500 ms timeout every cycle).</li>
  <li><strong>Con:</strong> health flaps without a hold-off; before the first reply the image is zero, not "no data".</li>
  <li><strong>Con:</strong> configuration is slow through the API (60 per-word mappings took about 10 minutes); <code>Auto-restart</code> off by default.</li>
</ul></div>
</div>
</section>

<section id="choose">
<h2>Which to use</h2>
<div class="table-wrap"><table class="compact verdict"><thead><tr><th>Situation</th><th>Use</th><th>Why</th></tr></thead><tbody>
<tr><td>Many units behind one RS485 gateway</td><td>ModbusFB, one connection per gateway</td><td>Native needs a connection per unit; the gateway's serial side is the real limit anyway.</td></tr>
<tr><td>A few Modbus TCP devices, each its own IP</td><td>Native</td><td>One connection each is natural; fastest polling; no code.</td></tr>
<tr><td>The PLC's own RS485 port, healthy devices</td><td>Either; native is slightly faster</td><td>Wire-bound at 9600; pick by what the team maintains.</td></tr>
<tr><td>Devices that may be absent or unpowered</td><td>ModbusFB, or native with long cycles</td><td>Back-off keeps a dead device from starving its neighbours.</td></tr>
<tr><td>A serial line above 38400 baud</td><td>Shorten the bus task (ModbusFB) or <code>TimeBetweenFrames</code> (native)</td><td>Past that rate the PLC, not the wire, sets the request time.</td></tr>
<tr><td>Polling faster than about 30 requests/s on one TCP connection</td><td>Native, or ModbusFB with a 2 ms bus task</td><td>ModbusFB's rate is set by task cycles.</td></tr>
<tr><td>Any native server</td><td>Health hold-off ≥ cycle + timeout; Auto-restart / AutoReconnect on</td><td><code>xError</code> clears at each retry; the defaults stop polling after one timeout.</td></tr>
<tr><td>Any device</td><td>Contiguous blocks, merged across short gaps</td><td>A request's fixed cost dwarfs its per-register cost, except on slow RTU.</td></tr>
</tbody></table></div>
</section>

<section id="data">
<h2>All runs</h2>
<p>60 s windows (40 s for native TCP). Gateway and serial rates are replies counted by the simulators; the serial figure excludes the real ME31. Broker values: tags checked against the simulators' known values in every MQTT message (304 bus tags; NaN where a device is dead or an ME31 channel is open).</p>
@@RUN_TABLE@@
<div class="exports">
  <button data-copy="csv">Copy runs as CSV</button>
  <button data-copy="blocks">Copy block-size data as CSV</button>
  <button data-copy="baud">Copy baud-rate data as CSV</button>
  <button data-copy="prompt">Copy as prompt: plan a program's Modbus lines</button>
  <span class="ok-msg" id="copied" aria-live="polite"></span>
</div>
</section>

<section id="method">
<h2>Method</h2>
<details><summary>Bench, tools and evidence</summary>
<ul>
  <li>PLC: AutomationDirect P2CDS-622 (CODESYS V3.5 SP22 Patch 1), the architecture skeleton with 2,000 tags, publishing every tag once a second over MQTT.</li>
  <li>Gateway line: ModbusFB <code>ClientTCP</code> to the NA111-E (192.168.50.67), RS485 115200 to a Go simulator on COM11 with units 11-40 (holding registers 0-124). Native TCP: Ethernet node on ETH1 (<code>et1</code>), <code>Modbus_TCP_Client</code>, five servers imported from the proven 2026-09-24 template (FC03, 2 registers).</li>
  <li>Serial line: the PLC's RJ12 port (COM1) at 9600 8N1, to the Ebyte ME31 (unit 1) and a Go simulator on COM12 (units 2-10, input registers 400-524). ModbusFB <code>ClientSerial</code> or native <code>Modbus_COM</code> (auto-restart on).</li>
  <li>FTDI latency timer 1 ms on both simulator adapters for every result here except the archived 16 ms set.</li>
  <li>Tools (<code>examples/plc_architecture/bench/</code>): <code>measure_bus.py</code> (PLC counters with per-read timestamps, simulator replies), <code>run_bus_series.ps1</code>, <code>verify_arch.py</code> (broker check), <code>sweep_block_size.py</code>, <code>time_gateway.py</code>, <code>set_native_cycle.py</code>, <code>add_native_serial.py</code>, <code>add_native_tcp.py</code>, <code>summarize_bus.py</code>; results in <code>bench/results/bus/</code>; this page from <code>bench/report/make_bus_doc.py</code>.</li>
  <li>Not measured: native TCP to devices with their own IP addresses (no gateway), native TCP's dependence on the bus task, and real devices above 9600 baud (the baud-rate runs used simulated units only).</li>
</ul></details>
</section>
</main>
<footer>Generated from codesys-api/examples/plc_architecture/bench/results/bus.</footer>
<div id="tip" role="tooltip"></div>
<script>
const exportsData = { csv: @@CSV@@, blocks: @@BLOCK_CSV@@, baud: @@BAUD_CSV@@, prompt: @@PROMPT@@ };
const copied = document.getElementById("copied");
document.querySelectorAll("button[data-copy]").forEach(button => {
  button.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(exportsData[button.dataset.copy]); copied.textContent = "Copied ✓"; }
    catch (error) { copied.textContent = "Copy failed"; }
    setTimeout(() => { copied.textContent = ""; }, 1800);
  });
});
const tip = document.getElementById("tip");
document.querySelectorAll("svg .mark[data-tip]").forEach(mark => {
  mark.addEventListener("mousemove", event => {
    tip.textContent = mark.dataset.tip; tip.style.left = (event.clientX + 14) + "px"; tip.style.top = (event.clientY + 14) + "px"; tip.style.opacity = 1;
  });
  mark.addEventListener("mouseleave", () => { tip.style.opacity = 0; });
});
document.querySelectorAll("#runs thead th").forEach((th, column) => {
  th.style.cursor = "pointer"; th.title = "Sort";
  th.addEventListener("click", () => {
    const tbody = th.closest("table").querySelector("tbody");
    const rows = Array.from(tbody.rows);
    const ascending = th.dataset.dir !== "asc";
    th.dataset.dir = ascending ? "asc" : "desc";
    const key = row => { const text = row.cells[column].textContent.trim(); const number = parseFloat(text.replace(/,/g, "")); return isNaN(number) ? text.toLowerCase() : number; };
    rows.sort((a, b) => (key(a) > key(b) ? 1 : key(a) < key(b) ? -1 : 0) * (ascending ? 1 : -1));
    rows.forEach(row => tbody.appendChild(row));
  });
});
</script>
</body></html>
"""

rtu_max = 125 * 1000.0 / (rtu_fit[0] + rtu_fit[1] * 125)
blk1 = tcp_fb_rows[0]
blk125 = tcp_fb_rows[-1]
fields = {
    "STYLE": style, "DATE": DATE, "TOPOLOGY": TOPOLOGY.replace("@@PANELS@@", panels),
    "T6": f(t6, 0), "FB_RTU": f(fb_rtu_sat), "NATIVE_RTU": f(native_rtu_sat), "PC10": f(pc_10), "FB_REQ": f(1000.0 / fb_tcp_sat, 0),
    "FB_TCP": f(fb_tcp_sat, 0), "FB_TCP2": f(fb_tcp_2ms, 0), "NATIVE_CONN": f(median(native_tcp_conn.values()), 0),
    "NATIVE_TCP": f(native_tcp_total, 0), "BLK1": f(1000.0 / blk1[1]), "BLK125": f(1000.0 / blk125[1]), "BLK1_RATE": f(blk1[1], 0),
    "BLK125_REGS": f(blk125[0] * blk125[1], 0), "RTU_SLOPE": f(rtu_fit[1]), "RTU_A": f(rtu_fit[0], 0), "GAP": "%d" % round(rtu_fit[0] / rtu_fit[1]),
    "TCP_A": f(tcp_fit[0]), "TCP_B": f(tcp_fit[1], 2), "PC_A": f(pc_fit[0]), "PC_B": f(pc_fit[1], 2), "PC_GAP": "%d" % round(pc_fit[0] / pc_fit[1]),
    "DEAD_FB_RTU": pct(dead_fb_rtu), "DEAD_FB_TCP": pct(dead_fb_tcp), "DEAD_NATIVE_RTU": pct(dead_native_rtu), "DEAD_NATIVE_TCP": pct(dead_native_tcp),
    "DEAD_FB_RTU_LOSS": pct(1 - dead_fb_rtu), "DEAD_FB_TCP_LOSS": pct(1 - dead_fb_tcp), "DEAD_NATIVE_RTU_LOSS": pct(1 - dead_native_rtu),
    "DEAD_NATIVE_TCP_RATE": f(dead_native_tcp_rate), "RESTORED": f(median(w["rates"]["11"] for w in restored_windows), 0),
    "ERROR_SHARE": pct(run["native_dead"]["native.ErrorShare[5]"]),
    "FB_OVH5": f(fb_overhead_5, 0), "FB_OVH2": f(fb_overhead_2, 0), "NATIVE_SPACING": f(1000.0 / native_tcp_total),
    "NATIVE_GAIN": pct(native_rtu_sat / fb_rtu_sat - 1),
    "BUS5": f(line_cost_us(5)[2] / 1000.0, 2), "BUS5_PCT": pct(line_cost_us(5)[2] / 5000.0),
    "BUS2": f(line_cost_us(2)[2] / 1000.0, 2), "BUS2_PCT": pct(line_cost_us(2)[2] / 2000.0),
    "BAUD_CHARTS": baud_charts, "BAUD_TABLE": table_html(BAUD_HEAD, baud_rows, set(range(2, 8)), "baud"),
    "LINE_COST_TABLE": table_html(LINE_COST_HEAD, line_cost_rows, set(range(1, 6))),
    "WIRE_9600": f(wire_ms(6, 9600), 0), "WIRE_115200": f(wire_ms(6, 115200)),
    "FB5_9600": f(fb_baud[(9600, 6)], 0), "FB5_57600": f(fb_baud[(57600, 6)]), "FB5_115200": f(fb_baud[(115200, 6)]),
    "FB2_9600": f(fb_baud_2[(9600, 6)]), "FB2_115200": f(fb_baud_2[(115200, 6)]),
    "NAT5_115200": f(native_baud[(115200, 6)]), "NAT2_115200": f(native_baud_2[(115200, 6)]),
    "FB5_120_9600": f(fb_baud[(9600, 120)], 0), "FB5_120_115200": f(fb_baud[(115200, 120)], 0),
    "FB_OVH_RTU5": f(median(fb_baud[(b, 6)] - wire_ms(6, b) for b in BAUDS), 0),
    "FB_OVH_RTU2": f(median(fb_baud_2[(b, 6)] - wire_ms(6, b) for b in BAUDS), 0),
    "RTU115_RATE": "%s-%s" % (f(1000.0 / fb_baud[(115200, 6)], 0), f(1000.0 / fb_baud_2[(115200, 6)], 0)),
    "GAP_SENTENCE": gap_sentence(), "BAUD_CSV": json.dumps(BAUD_CSV), "NATG_115200": f(native_baud_gap[(115200, 6)]),
    "FBRTU_A": f(fb_rtu_fit[0], 0), "FBRTU_B": f(fb_rtu_fit[1]), "FBRTU_GAP": "%d" % round(fb_rtu_fit[0] / fb_rtu_fit[1]),
    "FBRTU_EXTRA": f(median(fb - nt for (_, fb), (_, nt) in zip(sorted(p for p in fb_rtu_points if p[0] in (6, 30, 120)), rtu_points)), 0),
    "RTU_LOAD": pct(t6 / 1000.0), "BLK_GAIN": f(blk125[0] * blk125[1] / blk1[1], 0), "RTU_MAX": f(rtu_max, 0),
    "LINE_RATE": line_rate_chart, "REQUEST": request_chart, "BLOCK_REGS": block_regs_chart, "BLOCK_TIME": block_time_chart, "DEAD": dead_chart,
    "RUN_TABLE": table_html(HEAD, table_rows, NUMERIC, "runs"),
    "CSV": json.dumps(CSV), "BLOCK_CSV": json.dumps(BLOCK_CSV), "PROMPT": json.dumps(PROMPT),
}
for key, value in fields.items():
    page = page.replace("@@%s@@" % key, value)
left = re.findall(r"@@\w+@@", page)
assert not left, left
OUT.write_text(page, encoding="utf-8")
print("%s: %d bytes" % (OUT, len(page.encode("utf-8"))))
