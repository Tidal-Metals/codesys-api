"""Build the architecture redesign document from its template and the compiled skeleton sources.

Usage: python examples/plc_architecture/report/make_architecture_doc.py [output.html]
Code snippets come straight from examples/plc_architecture/st (compiled by check_compile.py); the
stylesheet is shared with the MQTT large-payload report.
"""
import html
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ST = HERE.parent / "st"
MQTT_TEMPLATE = HERE.parents[1] / "mqtt_large_payload" / "report" / "report_template.html"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "architecture.html"
MARKER = "// ---- implementation ----\n"


def source(name, part="all"):
    text = (ST / (name + ".st")).read_text(encoding="utf-8")
    if MARKER not in text:
        return text.rstrip()
    declaration, implementation = text.split(MARKER, 1)
    if part == "decl":
        return declaration.rstrip()
    if part == "impl":
        return implementation.rstrip()
    return declaration.rstrip() + "\n\n" + implementation.rstrip()


def code(title, text):
    return ('<p class="code-title"><code>%s</code></p><pre class="code"><code>%s</code></pre>'
            % (html.escape(title), html.escape(text)))


SNIPPETS = {
    "prg_control": ("PRG_Control", source("PRG_Control")),
    "st_tagconfig": ("ST_TagConfig", source("ST_TagConfig")),
    "st_tagstate": ("ST_TagState", source("ST_TagState")),
    "gvl_tags": ("GVL_Tags", source("GVL_Tags")),
    "permissives": ("PRG_Control.EvaluatePermissives", source("PRG_Control.EvaluatePermissives")),
    "write_outputs": ("PRG_Control.WriteOutputs", source("PRG_Control.WriteOutputs")),
    "receiver": ("FB_CommandReceiver.PublishReceived", source("FB_CommandReceiver.PublishReceived")),
    "queue_push": ("FB_CommandQueue.Push", source("FB_CommandQueue.Push")),
    "queue_pop": ("FB_CommandQueue.Pop", source("FB_CommandQueue.Pop")),
    "apply_commands": ("PRG_Control.ApplyCommands", source("PRG_Control.ApplyCommands")),
    "check_command": ("PRG_Control.CheckCommand", source("PRG_Control.CheckCommand")),
    "read_inputs": ("PRG_Control.ReadInputs", source("PRG_Control.ReadInputs")),
    "compute_values": ("PRG_Control.ComputeValues", source("PRG_Control.ComputeValues")),
    "evaluate_alarms": ("PRG_Control.EvaluateAlarms", source("PRG_Control.EvaluateAlarms")),
    "publish_data": ("PRG_Comms.PublishData", source("PRG_Comms.PublishData")),
    "append_tag": ("PRG_Comms.AppendTag", source("PRG_Comms.AppendTag")),
    "prg_comms": ("PRG_Comms", source("PRG_Comms")),
    "publish_acks": ("PRG_Comms.PublishAcks", source("PRG_Comms.PublishAcks")),
    "queue_decl": ("FB_CommandQueue", source("FB_CommandQueue")),
    "find_tag": ("F_FindTag", source("F_FindTag")),
    "now_ms": ("F_NowMs", source("F_NowMs")),
    "wall_clock": ("F_WallClockMs", source("F_WallClockMs")),
}


def main():
    template = (HERE / "architecture_template.html").read_text(encoding="utf-8")
    style = re.search(r"<style>.*?</style>", MQTT_TEMPLATE.read_text(encoding="utf-8"), re.S).group(0)
    style = style.replace("</style>", ".code-title { margin: 18px 0 4px; font-size: 0.85rem; color: var(--ink-2); }\n</style>")
    text = template.replace("@@style@@", style)
    for key, (title, body) in SNIPPETS.items():
        text = text.replace("@@%s@@" % key, code(title, body))
    leftover = re.findall(r"@@\w+@@", text)
    assert not leftover, "unfilled placeholders: %s" % leftover
    OUT.write_text(text, encoding="utf-8")
    print(OUT, OUT.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
