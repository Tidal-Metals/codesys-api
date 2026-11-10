"""Compile a CODESYS 4 device application over JSON-RPC and print the compiler messages.

Usage: python compile_rpc.py <work_dir> <path to Application.iecapp> [repeat]
Prints elapsed time per compile and the messages streamed by the run/status message pools.
"""
import asyncio
import json
import sys
import time
from pathlib import Path

from c4_rpc import C4RpcError, C4Session

POOLS = ["CODESYS.C4.Modules.MessagePool.RunMessagePool", "CODESYS.C4.Modules.MessagePool.StatusMessagePool"]


async def subscribe(c4, method, *args):
    callback_id = c4.new_callback()
    try:
        await c4.call(method, callback_id, *args, timeout_s=30)
    except C4RpcError as error:
        print(f"# subscribe {method} failed: {error}")
    return callback_id


async def main(work_dir, app_path, repeat):
    app_uri = Path(app_path).resolve().as_uri()
    session = await asyncio.to_thread(C4Session.start, work_dir)
    async with session as c4:
        project_uri = app_uri.rsplit("/", 1)[0] + "/"
        print("# AddProject:", await c4.call("CODESYS.C4.Modules.WorkspaceManager.AddProject", project_uri))
        for run in range(repeat):
            started = time.perf_counter()
            try:
                result = await c4.call("CODESYS.C4.Modules.Compiler.ICompilerService.Compile", app_uri)
                status = f"ok {result!r}"
            except C4RpcError as error:
                status = f"error {error}"
            print(f"## compile {run + 1}: {status} in {time.perf_counter() - started:.2f}s")
            await asyncio.sleep(1.5)
        # Pools replay their current content to a new subscriber, so subscribe after the builds.
        categories = {pool: await subscribe(c4, f"{pool}.Categories") for pool in POOLS}
        await asyncio.sleep(1)
        subs = {}
        for pool, callback_id in categories.items():
            # onNext params arrive as [[value]]; a category value is a list of names.
            names = sorted({name for method, payload in c4.callbacks(callback_id) if method == "onNext"
                            for name in payload[0][0]})
            print(f"# {pool} categories: {names}")
            for name in names:
                subs[f"{pool}[{name}]"] = await subscribe(c4, f"{pool}.Changes", name)
        await asyncio.sleep(1)
        for pool, callback_id in subs.items():
            events = c4.callbacks(callback_id)
            print(f"## {pool}: {len(events)} events")
            for method, payload in events:
                print(f"  {method}: {json.dumps(payload)[:3000]}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 1))
