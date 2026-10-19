"""HTML fragments for the report's tag:value, scale-test, report-by-exception and pros/cons sections.

Everything is computed from the result files in results/ and results/scale/; make_report.py fills the
template placeholders with fields().
"""
import html
import json
from pathlib import Path

RESULTS = Path(__file__).resolve().parents[1] / "results"
SCALE = RESULTS / "scale"
TAG_COUNT = 2000
TYPE_COUNTS = {"BOOL": 1000, "DINT": 500, "REAL": 500}
KIND_FILES = {"BOOL": "kind1.json", "DINT": "kind2.json", "REAL": "kind3.json"}
FULL_REFRESH_EVERY = 60        # RBE: one full message every 60 publishes (about a minute)


def load(path):
    return json.loads(Path(path).read_text())


def ms(us, digits=1):
    return ("%." + str(digits) + "f") % (us / 1000.0)


def kb(nbytes):
    return "%.1f" % (nbytes / 1000.0)


# ---------------------------------------------------------------- measured data
scale = dict(((r["format"], r["tagsPerScan"], r["qos"]), r)
             for r in (load(p) for p in sorted(SCALE.glob("*_per*_qos*.json"))))
kinds = dict((kind, load(SCALE / name)) for kind, name in KIND_FILES.items())
kind_none = load(SCALE / "kind4.json")
bcnf_tv = {0: load(RESULTS / "tag_value_qos0.json")["run"], 1: load(RESULTS / "tag_value_qos1.json")["run"]}
bcnf_every = load(RESULTS / "bcnf_every_scan.json")["windows"]["bcnfEveryScan"]
verify_scale = load(SCALE / "verify_scale.json")["byFormat"]
verify_tv = load(RESULTS / "verify_tag_value.json")

SKIP_US = kind_none["buildMeanUs"] / float(TAG_COUNT)          # per tag skipped by OnlyKind
HEADER_BYTES = kind_none["LastPayloadLength"]


def per_type_cost():
    """Measured build cost (us) and tag:value bytes per tag, by type."""
    costs = {}
    for kind, run in kinds.items():
        count = TYPE_COUNTS[kind]
        build_us = (run["buildMeanUs"] - SKIP_US * (TAG_COUNT - count)) / count
        line_bytes = (run["LastPayloadLength"] - HEADER_BYTES) / float(count)
        costs[kind] = {"us": build_us, "bytes": line_bytes}
    return costs


COSTS = per_type_cost()
DETECT_US = max(run["ChangeDetectUs"] for run in list(kinds.values()) + [kind_none])
DETECT_MAX_US = max(run["MaxChangeDetectUs"] for run in list(kinds.values()) + [kind_none])


def send_fit():
    """Least-squares fit of QoS 0 request->done time (ms) against message size (KB), from the scale runs."""
    points = [(r["LastPayloadLength"] / 1000.0, r["MaxPublishUs"] / 1000.0)
              for r in list(kinds.values()) + [kind_none] + [r for k, r in scale.items() if k[2] == 0]]
    n = float(len(points))
    mean_x = sum(x for x, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / sum((x - mean_x) ** 2 for x, _ in points)
    return mean_y - slope * mean_x, slope


SEND_A, SEND_B = send_fit()
# A publish never completes faster than this, even for a 14-byte message (two scans).
SEND_FLOOR_MS = min(r["MaxPublishUs"] for r in list(kinds.values()) + [kind_none]) / 1000.0


def send_ms(nbytes):
    return max(SEND_FLOOR_MS, SEND_A + SEND_B * nbytes / 1000.0)


# Positional (publish map) bytes per value, derived from the same runs: the value text plus ", ".
NAME_BYTES = 7.75   # average generated name length (7-9 bytes)
POSITIONAL_BYTES = {"BOOL": 3.0, "DINT": COSTS["DINT"]["bytes"] - NAME_BYTES - 2 + 2,
                    "REAL": COSTS["REAL"]["bytes"] - NAME_BYTES - 2 + 2}

SCENARIOS = [
    # name, description, change probability per publish (BOOL, DINT, REAL)
    ("Quiet", "steady operation, REAL deadband", (0.002, 0.02, 0.05)),
    ("Typical", "normal operation, REAL deadband", (0.01, 0.10, 0.20)),
    ("Busy", "start-up or upset, REAL deadband", (0.05, 0.25, 0.50)),
    ("No deadband", "typical, but every REAL sent each time", (0.01, 0.10, 1.00)),
]


def rbe_estimate(probabilities):
    """Expected per-message figures for tag:value with report-by-exception."""
    changed = dict((kind, TYPE_COUNTS[kind] * p) for kind, p in zip(("BOOL", "DINT", "REAL"), probabilities))
    nbytes = HEADER_BYTES + sum(changed[k] * COSTS[k]["bytes"] for k in changed)
    build_us = DETECT_US + SKIP_US * TAG_COUNT + sum(changed[k] * COSTS[k]["us"] for k in changed)
    # publish map with group-level RBE: a 100-value group (one type per group) goes if any value changed
    group_bytes = 0.0
    for kind, p in zip(("BOOL", "DINT", "REAL"), probabilities):
        groups = TYPE_COUNTS[kind] / 100.0
        group_bytes += groups * (1 - (1 - p) ** 100) * (100 * POSITIONAL_BYTES[kind] + 7)
    return {"tags": sum(changed.values()), "bytes": nbytes, "build_us": build_us,
            "send_ms": send_ms(nbytes), "positional_group_bytes": group_bytes + 15}


FULL_TV = scale[("tagvalue", 2000, 0)]
FULL_PM = scale[("positional", 2000, 0)]


# ---------------------------------------------------------------- charts
def hbar_chart(title, rows, unit, scale_max, width=330, label_width=104, ref=None, decimals=1):
    """Small horizontal bar chart. rows: (label, css class, value, tooltip). ref: (value, label)."""
    bar_h, gap, top = 18, 10, 38
    plot_w = width - label_width - 60
    height = top + len(rows) * (bar_h + gap) + 8
    parts = ['<svg class="chart" viewBox="0 0 %d %d" style="max-width:%dpx" role="img" aria-label="%s">'
             % (width, height, width, html.escape(title)),
             '<text class="mini-title" x="0" y="14">%s</text>' % html.escape(title)]
    if ref:
        rx = label_width + plot_w * ref[0] / scale_max
        parts.append('<line class="budget" x1="%.1f" x2="%.1f" y1="%d" y2="%d"/>' % (rx, rx, top - 6, height - 4))
        parts.append('<text class="budget-label" x="%.1f" y="%d" text-anchor="middle">%s</text>' % (rx, top - 10, html.escape(ref[1])))
    for index, (label, css, value, tip) in enumerate(rows):
        y = top + index * (bar_h + gap)
        w = max(plot_w * value / scale_max, 1.5)
        parts.append('<text class="cat-sub" x="%d" y="%.1f" text-anchor="end">%s</text>' % (label_width - 6, y + 13, html.escape(label)))
        parts.append('<rect class="%s mark" x="%d" y="%d" width="%.1f" height="%d" rx="3" data-tip="%s"/>'
                     % (css, label_width, y, w, bar_h, html.escape(tip)))
        parts.append('<text class="value" x="%.1f" y="%.1f">%s %s</text>' % (label_width + w + 5, y + 13, ("%." + str(decimals) + "f") % value, unit))
    parts.append("</svg>")
    return "\n".join(parts)


def scale_multiples():
    pm, tv = FULL_PM, FULL_TV
    pm1, tv1 = scale[("positional", 2000, 1)], scale[("tagvalue", 2000, 1)]

    def pair(metric, unit, pm_value, tv_value, scale_max, ref=None, decimals=1):
        return hbar_chart(metric, [
            ("publish_map", "s1", pm_value, "publish_map · %s: %.1f %s" % (metric, pm_value, unit)),
            ("tag:value", "s2", tv_value, "tag:value · %s: %.1f %s" % (metric, tv_value, unit)),
        ], unit, scale_max, width=440, label_width=92, ref=ref, decimals=decimals)

    period = (1100, "1.1 s publish period")
    charts = [
        pair("Message size", "KB", pm["LastPayloadLength"] / 1000.0, tv["LastPayloadLength"] / 1000.0, 30),
        pair("Build per message (PLC time)", "ms", pm["buildMeanUs"] / 1000.0, tv["buildMeanUs"] / 1000.0, 20),
        pair("Send until done, QoS 0", "ms", pm["MaxPublishUs"] / 1000.0, tv["MaxPublishUs"] / 1000.0, 1300, ref=period, decimals=0),
        pair("Send until done, QoS 1", "ms", pm1["MaxPublishUs"] / 1000.0, tv1["MaxPublishUs"] / 1000.0, 1300, ref=period, decimals=0),
    ]
    return '<div class="multiples">%s</div>' % "".join('<div>%s</div>' % c for c in charts)


def worst_scan_chart():
    rows = []
    for build_label, per in (("one scan", 2000), ("8 scans", 250)):
        for fmt, css, name in (("positional", "s1", "publish_map"), ("tagvalue", "s2", "tag:value")):
            worst = scale[(fmt, per, 0)]["MaxCycleUs"] / 1000.0
            rows.append(("%s · %s" % (build_label, name), css, worst,
                         "%s, build in %s: worst scan %.1f ms" % (name, build_label, worst)))
    return hbar_chart("Worst scan, QoS 0 (whole program)", rows, "ms", 55, width=560, label_width=160,
                      ref=(50, "50 ms task interval"))


def rbe_chart():
    rows = [("publish_map, full", "s1", FULL_PM["LastPayloadLength"] / 1000.0, "publish_map, every value: %s KB measured" % kb(FULL_PM["LastPayloadLength"])),
            ("tag:value, full", "s2", FULL_TV["LastPayloadLength"] / 1000.0, "tag:value, every value: %s KB measured" % kb(FULL_TV["LastPayloadLength"]))]
    for name, _, probabilities in SCENARIOS:
        estimate = rbe_estimate(probabilities)
        rows.append(("RBE, %s" % name.lower(), "s3", estimate["bytes"] / 1000.0,
                     "tag:value with report-by-exception, %s: about %s KB (estimate)" % (name.lower(), kb(estimate["bytes"]))))
    return hbar_chart("Message size, KB (RBE rows are estimates)", rows, "KB", 30, width=560, label_width=160)


# ---------------------------------------------------------------- tables
def cell_row(cells):
    return "<tr>%s</tr>" % "".join("<td class='%s'>%s</td>" % (css, text) for text, css in cells)


def scale_rows():
    rows = []
    order = [("positional", 2000, 0), ("tagvalue", 2000, 0), ("positional", 250, 0), ("tagvalue", 250, 0),
             ("positional", 2000, 1), ("tagvalue", 2000, 1)]
    for key in order:
        r = scale[key]
        rows.append(cell_row([
            ("publish_map" if key[0] == "positional" else "tag:value", ""), ("1" if key[1] == 2000 else "8", "num"),
            (str(key[2]), "num"), ("{:,}".format(r["LastPayloadLength"]), "num"),
            ("%s (%s)" % (ms(r["buildMeanUs"]), ms(r["MaxBuildUs"])), "num"), (ms(r["MaxBuildScanUs"]), "num"),
            (ms(r["MaxCycleUs"]), "num"), (ms(r["MaxIntervalUs"]), "num"), (ms(r["MaxClientUs"]), "num"),
            ("%.0f ms (%d scans)" % (r["MaxPublishUs"] / 1000.0, r["MaxPublishCycles"]), "num"),
            (str(r["TimeoutCount"]), "num"),
        ]))
    return "\n".join(rows)


def per_type_rows():
    rows = []
    for kind in ("BOOL", "DINT", "REAL"):
        c = COSTS[kind]
        example = {"BOOL": "<code>TT-1001:1</code>", "DINT": "<code>XV-2001:-4321</code>", "REAL": "<code>FT-2503B:-123.45</code>"}[kind]
        rows.append(cell_row([(kind, ""), ("{:,}".format(TYPE_COUNTS[kind]), "num"), ("%.1f µs" % c["us"], "num"),
                              ("%.1f" % c["bytes"], "num"), (example, "")]))
    return "\n".join(rows)


def rbe_rows():
    rows = [cell_row([("<strong>publish_map, every value</strong> (measured)", ""), ("2,000", "num"),
                      (kb(FULL_PM["LastPayloadLength"]), "num"), (ms(FULL_PM["buildMeanUs"]), "num"),
                      ("%.0f" % (FULL_PM["MaxPublishUs"] / 1000.0), "num"), ("–", "num")]),
            cell_row([("<strong>tag:value, every value</strong> (measured)", ""), ("2,000", "num"),
                      (kb(FULL_TV["LastPayloadLength"]), "num"), (ms(FULL_TV["buildMeanUs"]), "num"),
                      ("%.0f" % (FULL_TV["MaxPublishUs"] / 1000.0), "num"), ("–", "num")])]
    for name, description, probabilities in SCENARIOS:
        e = rbe_estimate(probabilities)
        rows.append(cell_row([
            ("%s: %s<br><span class='muted'>BOOL %g%%, DINT %g%%, REAL %g%% change per publish</span>"
             % (name, description, probabilities[0] * 100, probabilities[1] * 100, probabilities[2] * 100), ""),
            ("{:,}".format(int(round(e["tags"]))), "num"), (kb(e["bytes"]), "num"), ("%.1f" % (e["build_us"] / 1000.0), "num"),
            ("%.0f" % e["send_ms"], "num"), (kb(e["positional_group_bytes"]), "num"),
        ]))
    return "\n".join(rows)


def scale_csv():
    lines = ["format,builds_over_scans,qos,payload_bytes,build_mean_ms,build_max_ms,max_build_scan_ms,worst_scan_ms,"
             "longest_scan_gap_ms,client_max_ms,request_to_done_ms,request_to_done_scans,timeouts"]
    for key, r in sorted(scale.items()):
        lines.append(",".join(str(v) for v in [
            "publish_map" if key[0] == "positional" else "tag:value", 1 if key[1] == 2000 else 8, key[2],
            r["LastPayloadLength"], ms(r["buildMeanUs"], 2), ms(r["MaxBuildUs"], 2), ms(r["MaxBuildScanUs"], 2),
            ms(r["MaxCycleUs"], 2), ms(r["MaxIntervalUs"], 2), ms(r["MaxClientUs"], 2),
            "%.0f" % (r["MaxPublishUs"] / 1000.0), r["MaxPublishCycles"], r["TimeoutCount"]]))
    return "\n".join(lines)


def fields():
    typical = rbe_estimate(SCENARIOS[1][2])
    no_deadband = rbe_estimate(SCENARIOS[3][2])
    tv, pm = FULL_TV, FULL_PM
    return {
        "scale_multiples": scale_multiples(),
        "scale_worst_chart": worst_scan_chart(),
        "scale_rows": scale_rows(),
        "per_type_rows": per_type_rows(),
        "rbe_chart": rbe_chart(),
        "rbe_rows": rbe_rows(),
        "scale_csv_json": html.escape(json.dumps(scale_csv())),
        "tv_bytes_kb": kb(tv["LastPayloadLength"]),
        "pm_bytes_kb": kb(pm["LastPayloadLength"]),
        "bytes_ratio": "%.1f" % (tv["LastPayloadLength"] / float(pm["LastPayloadLength"])),
        "tv_build_ms": ms(tv["buildMeanUs"]),
        "pm_build_ms": ms(pm["buildMeanUs"]),
        "build_extra_pct": "%.0f" % (100.0 * (tv["buildMeanUs"] - pm["buildMeanUs"]) / pm["buildMeanUs"]),
        "tv_send_ms": "%.0f" % (tv["MaxPublishUs"] / 1000.0),
        "pm_send_ms": "%.0f" % (pm["MaxPublishUs"] / 1000.0),
        "tv_send1_ms": "%.0f" % (scale[("tagvalue", 2000, 1)]["MaxPublishUs"] / 1000.0),
        "pm_send1_ms": "%.0f" % (scale[("positional", 2000, 1)]["MaxPublishUs"] / 1000.0),
        "tv_worst_one_ms": ms(max(tv["MaxCycleUs"], scale[("tagvalue", 2000, 1)]["MaxCycleUs"])),
        "tv_worst_spread_ms": ms(scale[("tagvalue", 250, 0)]["MaxCycleUs"]),
        "pm_worst_spread_ms": ms(scale[("positional", 250, 0)]["MaxCycleUs"]),
        "scale_values_checked": "{:,}".format(sum(v["valuesChecked"] for v in verify_scale.values())),
        "scale_messages": "{:,}".format(sum(v["messages"] for v in verify_scale.values())),
        "bool_us": "%.1f" % COSTS["BOOL"]["us"], "dint_us": "%.1f" % COSTS["DINT"]["us"], "real_us": "%.1f" % COSTS["REAL"]["us"],
        "detect_ms": ms(DETECT_US, 2), "detect_max_ms": ms(DETECT_MAX_US, 2),
        "send_b_ms_per_kb": "%.0f" % SEND_B, "send_floor_ms": "%.0f" % SEND_FLOOR_MS,
        "rbe_typical_kb": kb(typical["bytes"]), "rbe_typical_tags": "{:,}".format(int(round(typical["tags"]))),
        "rbe_typical_build_ms": "%.1f" % (typical["build_us"] / 1000.0), "rbe_typical_send_ms": "%.0f" % typical["send_ms"],
        "rbe_typical_pm_kb": kb(typical["positional_group_bytes"]),
        "rbe_nodb_kb": kb(no_deadband["bytes"]),
        "refresh_every": str(FULL_REFRESH_EVERY),
        "bcnf_tv_bytes": "{:,}".format(bcnf_tv[0]["LastTagValueLength"]),
        "bcnf_tv_build_ms": ms(bcnf_tv[0]["tagValueBuildMeanUs"]),
        "bcnf_tv_build_max_ms": ms(bcnf_tv[0]["MaxTagValueBuildUs"]),
        "bcnf_tv_send0_ms": "%.0f" % (bcnf_tv[0]["MaxTagValuePublishUs"] / 1000.0),
        "bcnf_tv_send1_ms": "%.0f" % (bcnf_tv[1]["MaxTagValuePublishUs"] / 1000.0),
        "bcnf_tv_lines": "{:,}".format(verify_tv["linesChecked"]),
        "bcnf_tv_messages": str(verify_tv["messages"]),
        "bcnf_pos_build_ms": ms(bcnf_every["bcnfBuildMeanUs"]),
        "bcnf_pos_build_max_ms": ms(bcnf_every["MaxBcnfBuildUs"]),
    }
