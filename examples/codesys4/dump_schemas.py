"""Save the JSON schemas the CODESYS 4 backend publishes for its project files.

Usage: python dump_schemas.py <work_dir> <out_dir>
"""
import asyncio
import json
import re
import sys
from pathlib import Path

from c4_rpc import C4Session


async def main(work_dir, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    session = await asyncio.to_thread(C4Session.start, work_dir)
    async with session as c4:
        callback_id = c4.new_callback()
        await c4.call("CODESYS.C4.Modules.Compiler.IJsonSchemaProvider.SchemaChanges", callback_id)
        await asyncio.sleep(3)
        events = [payload[0][0] for method, payload in c4.callbacks(callback_id) if method == "onNext"]
    (out / "_raw.json").write_text(json.dumps(events, indent=1), encoding="utf-8")
    count = 0
    for batch in events:
        for entry in batch if isinstance(batch, list) else [batch]:
            uri = entry.get("uri") or entry.get("id") or f"schema{count}"
            name = re.sub(r"[^A-Za-z0-9._-]+", "_", uri.rsplit("/", 1)[-1])[:80] or f"schema{count}"
            (out / f"{name}.json").write_text(json.dumps(entry, indent=1), encoding="utf-8")
            print(name, "| fileMatch:", entry.get("fileMatch"), "| keys:", list(entry)[:6])
            count += 1


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
