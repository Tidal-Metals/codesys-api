"""Short-lived bench reservations so agents sharing the PLC and adapters don't collide.

A reservation claims scopes such as ``plc``, ``adapter:BG01GGR2`` or
``gateway:B0-CB-D8-4E-88-BB`` (``bench`` claims everything). Mutating
endpoints call ``check`` with the scopes they touch: an unreserved scope is
open to everyone, a reserved one only to the holder's token. Tokens are
stored as SHA-256 hashes.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import uuid
from typing import Any

BENCH_SCOPE = "bench"
DEFAULT_TTL_SECONDS = 1800
MAX_TTL_SECONDS = 4 * 3600
TOKEN_PREFIX = "br_"


class ReservationError(Exception):
    """A reservation request was invalid or conflicts with another holder."""

    def __init__(self, message: str, status: int, conflicts: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.status = status
        self.conflicts = conflicts or []


def normalize_scope(scope: str) -> str:
    text = str(scope).strip()
    kind, _, value = text.partition(":")
    kind = kind.lower()
    if kind in (BENCH_SCOPE, "plc") and not value:
        return kind
    if kind == "adapter" and value:
        return "adapter:" + normalize_adapter_serial(value)
    if kind == "gateway" and value:
        return "gateway:" + value.upper().replace(":", "-")
    raise ReservationError(
        f"Invalid scope {scope!r}; use bench, plc, adapter:<USB serial> or gateway:<MAC>", 400)


def normalize_adapter_serial(serial: str) -> str:
    """FTDI reports BG01GGR2A in Windows for base serial BG01GGR2; key on the base."""
    text = str(serial).strip().upper()
    if len(text) == 9 and text.endswith("A"):
        return text[:-1]
    return text


def scopes_overlap(first: str, second: str) -> bool:
    return first == second or BENCH_SCOPE in (first, second)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class ReservationManager:
    def __init__(self, path: str, clock=time.time):
        self.path = path
        self.clock = clock
        self.lock = threading.Lock()

    def _load(self) -> list[dict[str, Any]]:
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return []
        now = self.clock()
        return [r for r in data.get("reservations", []) if r.get("expiresAt", 0) > now]

    def _save(self, reservations: list[dict[str, Any]]) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump({"reservations": reservations}, handle, indent=2)
        os.replace(tmp, self.path)

    @staticmethod
    def public(reservation: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in reservation.items() if k != "tokenHash"}

    def list(self) -> list[dict[str, Any]]:
        with self.lock:
            return [self.public(r) for r in self._load()]

    def create(self, holder: str, purpose: str, scopes: list[str], ttl_seconds: int | None) -> dict[str, Any]:
        if not str(holder or "").strip():
            raise ReservationError("holder is required", 400)
        if not isinstance(scopes, list) or not scopes:
            raise ReservationError("scope must be a non-empty list", 400)
        wanted = sorted({normalize_scope(s) for s in scopes})
        ttl = self._ttl(ttl_seconds)
        with self.lock:
            reservations = self._load()
            conflicts = [self.public(r) for r in reservations
                         if any(scopes_overlap(w, s) for w in wanted for s in r["scope"])]
            if conflicts:
                raise ReservationError("Scope already reserved", 409, conflicts)
            token = TOKEN_PREFIX + secrets.token_urlsafe(24)
            now = self.clock()
            reservation = {
                "id": uuid.uuid4().hex[:12],
                "holder": str(holder).strip(),
                "purpose": str(purpose or "").strip(),
                "scope": wanted,
                "createdAt": now,
                "expiresAt": now + ttl,
                "tokenHash": _hash_token(token),
            }
            reservations.append(reservation)
            self._save(reservations)
        return dict(self.public(reservation), token=token)

    def renew(self, reservation_id: str, token: str, ttl_seconds: int | None) -> dict[str, Any]:
        ttl = self._ttl(ttl_seconds)
        with self.lock:
            reservations = self._load()
            reservation = self._owned(reservations, reservation_id, token)
            reservation["expiresAt"] = self.clock() + ttl
            self._save(reservations)
            return self.public(reservation)

    def release(self, reservation_id: str, token: str) -> dict[str, Any]:
        with self.lock:
            reservations = self._load()
            reservation = self._owned(reservations, reservation_id, token)
            reservations.remove(reservation)
            self._save(reservations)
            return self.public(reservation)

    def check(self, scopes: list[str], token: str | None) -> None:
        """Raise 423 if any scope is reserved by someone other than token's holder."""
        wanted = [normalize_scope(s) for s in scopes]
        token_hash = _hash_token(token) if token else None
        with self.lock:
            blocking = [self.public(r) for r in self._load()
                        if any(scopes_overlap(w, s) for w in wanted for s in r["scope"])
                        and not (token_hash and hmac.compare_digest(token_hash, r["tokenHash"]))]
        if blocking:
            raise ReservationError("Reserved by another holder; send its X-Bench-Reservation token or wait",
                                   423, blocking)

    def holder_for_token(self, token: str | None) -> str:
        """The holder of the active reservation matching token, or ''."""
        if not token:
            return ""
        token_hash = _hash_token(token)
        with self.lock:
            for reservation in self._load():
                if hmac.compare_digest(token_hash, reservation["tokenHash"]):
                    return reservation["holder"]
        return ""

    def _owned(self, reservations, reservation_id, token):
        for reservation in reservations:
            if reservation["id"] == reservation_id:
                if not token or not hmac.compare_digest(_hash_token(token), reservation["tokenHash"]):
                    raise ReservationError("Token does not match this reservation", 403)
                return reservation
        raise ReservationError(f"Reservation {reservation_id} not found or expired", 404)

    @staticmethod
    def _ttl(ttl_seconds) -> int:
        if ttl_seconds is None:
            return DEFAULT_TTL_SECONDS
        try:
            ttl = int(ttl_seconds)
        except (TypeError, ValueError):
            raise ReservationError("ttlSeconds must be an integer", 400)
        if not 10 <= ttl <= MAX_TTL_SECONDS:
            raise ReservationError(f"ttlSeconds must be 10-{MAX_TTL_SECONDS}", 400)
        return ttl
