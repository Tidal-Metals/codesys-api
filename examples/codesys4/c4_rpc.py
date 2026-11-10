"""Minimal headless client for the CODESYS 4 IDE backend (JSON-RPC 2.0 over WebSocket).

`c4-cli standalone-session` starts the backend and hands a URL `http://localhost:<port>/index.html#<token>`
to a browser. We pass a fake browser that records the URL, exchange the one-shot token for a session
cookie (`GET /api/UserSessions` with header `InitToken`), then open `ws://localhost:<port>/api/JsonRpc`
with the matching Origin and a `tab.<uuid>` subprotocol. Method names are the ones the UI uses, see
`docs/codesys4/rpc-methods.txt`.

Usage as a library:
    async with C4Session.start(work_dir) as c4:
        result = await c4.call("CODESYS.C4.Modules.WorkspaceManager.GetOpenProjects")
"""
import asyncio
import json
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path

from websockets.asyncio.client import connect

C4_CLI = r"C:\Program Files\CODESYS-4\c4-cli.exe"
CALLBACK_CALL = "_c4-callback/call"


class C4RpcError(Exception):
    def __init__(self, method, error):
        self.method, self.error = method, error
        super().__init__(f"{method}: {error.get('message')} ({error.get('data', {}).get('type')})")


class C4Session:
    def __init__(self, process, port, token, log_path):
        self.process, self.port, self.token, self.log_path = process, port, token, log_path
        self.ws = None
        self._next_id = 1
        self._pending = {}
        self._callbacks = {}  # callbackId -> list of (method, params) received
        self.notifications = []
        self._reader = None

    @classmethod
    def start(cls, work_dir, timeout_s=90):
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        url_file = work_dir / "session_url.txt"
        url_file.unlink(missing_ok=True)
        browser = work_dir / "record_url.cmd"
        browser.write_text(f'@echo %~1> "{url_file}"\r\n', encoding="ascii")
        log_path = work_dir / "session.log"
        process = subprocess.Popen(
            [C4_CLI, "standalone-session", "--log-level=information", "--with-browser", str(browser)],
            stdin=subprocess.DEVNULL, stdout=open(log_path, "w"), stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic() + timeout_s
        while not url_file.exists() or not url_file.read_text().strip():
            if process.poll() is not None or time.monotonic() > deadline:
                process.kill()
                raise RuntimeError(f"standalone-session gave no URL; see {log_path}")
            time.sleep(0.5)
        url = url_file.read_text().strip().strip('"')
        port = int(url.split("localhost:")[1].split("/")[0])
        return cls(process, port, url.split("#", 1)[1], log_path)

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *exc):
        await self.close()

    def _login_cookie(self):
        request = urllib.request.Request(f"http://localhost:{self.port}/api/UserSessions",
                                         headers={"InitToken": self.token})
        with urllib.request.urlopen(request, timeout=30) as response:
            cookies = response.headers.get_all("Set-Cookie") or []
            body = response.read().decode()
        return "; ".join(c.split(";", 1)[0] for c in cookies), body

    async def connect(self):
        cookie, self.user = await asyncio.to_thread(self._login_cookie)
        origin = f"http://localhost:{self.port}"
        self.ws = await connect(f"ws://localhost:{self.port}/api/JsonRpc", origin=origin,
                                subprotocols=[f"tab.{uuid.uuid4()}"],
                                additional_headers={"Cookie": cookie}, max_size=None)
        self._reader = asyncio.create_task(self._read_loop())

    async def _read_loop(self):
        async for raw in self.ws:
            message = json.loads(raw)
            if "method" in message:
                await self._on_server_call(message)
            elif message.get("id") in self._pending:
                self._pending.pop(message["id"]).set_result(message)

    async def _on_server_call(self, message):
        params = message.get("params") or []
        if message["method"] == CALLBACK_CALL and len(params) >= 2:
            self._callbacks.setdefault(params[0], []).append((params[1], params[2:]))
        else:
            self.notifications.append(message)
        if "id" in message:
            await self.ws.send(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": True}))

    def new_callback(self):
        """Return a callback id to pass where the API expects an observer; events land in callbacks()."""
        callback_id = str(uuid.uuid4())
        self._callbacks[callback_id] = []
        return callback_id

    def callbacks(self, callback_id):
        return self._callbacks.get(callback_id, [])

    async def call(self, method, *params, timeout_s=300):
        request_id = self._next_id
        self._next_id += 1
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        await self.ws.send(json.dumps({"jsonrpc": "2.0", "method": method, "params": list(params),
                                       "id": request_id}))
        reply = await asyncio.wait_for(future, timeout_s)
        if "error" in reply:
            raise C4RpcError(method, reply["error"])
        return reply.get("result")

    async def close(self):
        if self.ws is not None:
            await self.ws.close()
        if self._reader is not None:
            self._reader.cancel()
        self.process.terminate()
        try:
            self.process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.process.kill()
