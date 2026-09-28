"""Process-wide bench services shared by every request handler."""

from __future__ import annotations

import json
import os
import time
from typing import Any

from bench_jobs import JobManager
from bench_reservations import ReservationManager
from server_config import SCRIPT_DIR, STATUS_FILE

JOB_DIR = os.path.join(SCRIPT_DIR, "logs", "jobs")
RESERVATIONS_PATH = os.path.join(SCRIPT_DIR, "bench_reservations.json")


def read_session_status() -> dict[str, Any]:
    """The persistent session's own status file, plus how old it is."""
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as handle:
            status = json.load(handle)
        status["fileAgeSeconds"] = round(time.time() - os.path.getmtime(STATUS_FILE), 1)
        return status
    except (OSError, ValueError):
        return {"state": "unknown"}


class BenchServices:
    def __init__(self, jobs: JobManager, reservations: ReservationManager):
        self.jobs = jobs
        self.reservations = reservations

    @classmethod
    def create(cls) -> "BenchServices":
        return cls(JobManager(JOB_DIR, read_session_status), ReservationManager(RESERVATIONS_PATH))
