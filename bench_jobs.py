"""Asynchronous jobs for long IDE operations.

The persistent session runs one script at a time, so jobs run on a single
FIFO worker: submission order is execution order, and a job can be
cancelled while it is still queued. A running CODESYS script cannot be
interrupted. Each state change is written to ``<job_dir>/<id>.json`` so
results survive an API restart.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
import traceback
import uuid
from typing import Any, Callable

from server_config import logger

QUEUED, RUNNING, SUCCEEDED, FAILED, CANCELLED = "queued", "running", "succeeded", "failed", "cancelled"
FINISHED_STATES = (SUCCEEDED, FAILED, CANCELLED)
MAX_JOB_TIMEOUT_SECONDS = 3600
HISTORY_LIMIT = 200


class JobError(Exception):
    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


class JobManager:
    def __init__(self, job_dir: str, status_reader: Callable[[], dict] | None = None):
        self.job_dir = job_dir
        self.status_reader = status_reader or (lambda: {})
        self.jobs: dict[str, dict[str, Any]] = {}
        self.runners: dict[str, Callable[[dict], dict]] = {}
        self.queue: queue.Queue[str] = queue.Queue()
        self.lock = threading.Lock()
        os.makedirs(job_dir, exist_ok=True)
        self.worker = threading.Thread(target=self._work, name="bench-job-worker", daemon=True)
        self.worker.start()

    def submit(self, kind: str, label: str, runner: Callable[[dict], dict], timeout_seconds: int,
               holder: str = "") -> dict[str, Any]:
        """Queue runner(job) -> result dict; returns the public job record."""
        job = {
            "id": uuid.uuid4().hex[:16],
            "kind": kind,
            "label": label,
            "holder": holder,
            "state": QUEUED,
            "timeoutSeconds": timeout_seconds,
            "requestId": str(uuid.uuid4()),
            "createdAt": time.time(),
            "startedAt": None,
            "finishedAt": None,
            "result": None,
            "error": None,
        }
        with self.lock:
            self.jobs[job["id"]] = job
            self.runners[job["id"]] = runner
            self._trim()
        self._persist(job)
        self.queue.put(job["id"])
        return self.describe(job)

    def get(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            job = self.jobs.get(job_id)
            job = dict(job) if job else None
        if job is None:
            job = self._load(job_id)
            if job is not None and job["state"] not in FINISHED_STATES:
                # On disk but unknown in memory: the API restarted mid-job.
                job.update(state=FAILED, error="API restarted before this job finished; "
                                               "its script may still have run")
        if job is None:
            raise JobError(f"Job {job_id} not found", 404)
        return self.describe(job)

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.lock:
            jobs = sorted(self.jobs.values(), key=lambda j: j["createdAt"], reverse=True)[:limit]
            jobs = [dict(j) for j in jobs]
        return [self.describe(j, include_result=False) for j in jobs]

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise JobError(f"Job {job_id} not found", 404)
            if job["state"] == RUNNING:
                raise JobError("A running CODESYS script cannot be interrupted; wait for it to finish", 409)
            if job["state"] == QUEUED:
                job.update(state=CANCELLED, finishedAt=time.time())
                self.runners.pop(job_id, None)
            snapshot = dict(job)
        self._persist(snapshot)
        return self.describe(snapshot)

    def counts(self) -> dict[str, int]:
        with self.lock:
            states = [j["state"] for j in self.jobs.values()]
        return {state: states.count(state) for state in (QUEUED, RUNNING)}

    def describe(self, job: dict[str, Any], include_result: bool = True) -> dict[str, Any]:
        out = {k: v for k, v in job.items() if include_result or k not in ("result",)}
        if job["state"] == RUNNING:
            status = self.status_reader() or {}
            request = status.get("request") or {}
            if request.get("id") == job["requestId"]:
                out["progress"] = status.get("progress")
                out["sessionHeartbeatAt"] = status.get("timestamp")
        return out

    def _work(self) -> None:
        while True:
            job_id = self.queue.get()
            with self.lock:
                job = self.jobs.get(job_id)
                runner = self.runners.pop(job_id, None)
                if job is None or runner is None or job["state"] != QUEUED:
                    continue
                job.update(state=RUNNING, startedAt=time.time())
                snapshot = dict(job)
            self._persist(snapshot)
            try:
                result = runner(snapshot)
                failed = not (isinstance(result, dict) and result.get("success", False))
                update = {"state": FAILED if failed else SUCCEEDED, "result": result,
                          "error": result.get("error") if failed and isinstance(result, dict) else None}
            except Exception as exc:  # a runner bug must not kill the worker
                logger.error("Job %s crashed: %s", job_id, traceback.format_exc())
                update = {"state": FAILED, "error": f"{type(exc).__name__}: {exc}"}
            with self.lock:
                job.update(update, finishedAt=time.time())
                snapshot = dict(job)
            self._persist(snapshot)

    def _trim(self) -> None:
        finished = sorted((j for j in self.jobs.values() if j["state"] in FINISHED_STATES),
                          key=lambda j: j["createdAt"])
        for job in finished[:max(0, len(self.jobs) - HISTORY_LIMIT)]:
            del self.jobs[job["id"]]

    def _persist(self, job: dict[str, Any]) -> None:
        path = os.path.join(self.job_dir, job["id"] + ".json")
        try:
            with open(path + ".tmp", "w", encoding="utf-8") as handle:
                json.dump(job, handle, indent=2, default=str)
            os.replace(path + ".tmp", path)
        except OSError as exc:
            logger.warning("Could not persist job %s: %s", job["id"], exc)

    def _load(self, job_id: str) -> dict[str, Any] | None:
        if not all(c in "0123456789abcdef" for c in job_id):
            return None
        path = os.path.join(self.job_dir, job_id + ".json")
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, ValueError):
            return None
