"""Exercise the CODESYS 4 backend headlessly: one RPC call per argument, results printed as JSON.

Usage: python -I probe_rpc.py <work_dir> '<method> <json params array>' ...
Example: python -I probe_rpc.py tmp/c4/run1 'CODESYS.C4.Sdk.FileSystem.IEntryPoints.GetFsEntryPoints []'
"""
import asyncio
import json
import sys
import time

from c4_rpc import C4RpcError, C4Session


async def main(work_dir, calls):
    session = await asyncio.to_thread(C4Session.start, work_dir)
    async with session as c4:
        print(f"# session port={c4.port} user={c4.user}")
        for spec in calls:
            method, _, params = spec.partition(" ")
            started = time.perf_counter()
            try:
                result = await c4.call(method, *json.loads(params or "[]"))
                status = "ok"
            except C4RpcError as error:
                result, status = error.error, "error"
            elapsed = time.perf_counter() - started
            print(f"## {method} [{status}, {elapsed:.2f}s]")
            print(json.dumps(result, indent=1)[:6000])
        await asyncio.sleep(1)
        if c4.notifications:
            print("## notifications", json.dumps(c4.notifications, indent=1)[:4000])


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2:]))
