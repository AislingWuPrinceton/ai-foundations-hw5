"""Append-only audit trail kept as one valid JSON array in output/audit_trail.json.

Each append re-reads the file, adds one entry, and atomically replaces the file
(write to a temp file, then os.replace), so the file is valid JSON after every
step and existing entries are never dropped. If the existing file is not a JSON
array, nothing is written and AuditLogError is raised rather than risk
overwriting someone's records.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CLIP_CHARS = 1500
REDACTED_CUSTOMER = "[customer]"
REDACTED_SECRET = "[secret]"


class AuditLogError(RuntimeError):
    pass


def clip(value: Any, limit: int = CLIP_CHARS) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= limit else text[:limit] + f"… (+{len(text) - limit} chars)"


class Redactor:
    """Replaces secrets and customer names in anything headed for the audit trail."""

    def __init__(self) -> None:
        self._secrets: set[str] = set()
        self._customers: set[str] = set()
        self._name_parts: set[str] = set()
        key = os.getenv("PORTKEY_API_KEY", "").strip()
        if key:
            self._secrets.add(key)

    def add_customer(self, name: str | None, *, person: bool = False) -> None:
        if name and name.strip():
            self._customers.add(name.strip())
            if person:  # a private person: also catch a greeting with part of the name ("Hi Tauhid")
                self._name_parts.update(p for p in re.split(r"\W+", name) if len(p) >= 3)

    def text(self, value: str) -> str:
        for s in self._secrets:
            value = value.replace(s, REDACTED_SECRET)
        for name in sorted(self._customers, key=len, reverse=True):
            value = value.replace(name, REDACTED_CUSTOMER)
        for part in self._name_parts:
            value = re.sub(rf"\b{re.escape(part)}\b", REDACTED_CUSTOMER, value)
        return value

    def __call__(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {k: (REDACTED_CUSTOMER if k == "requester" and v in self._customers else self(v))
                    for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self(v) for v in value]
        return value


class AuditLog:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def read(self) -> list[dict]:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise AuditLogError(f"{self.path} is not valid JSON; refusing to overwrite it ({exc}).") from exc
        if not isinstance(data, list):
            raise AuditLogError(f"{self.path} must hold a JSON array of entries; refusing to overwrite it.")
        return data

    def append(self, entry: dict) -> dict:
        entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), **entry}
        with self._lock:
            entries = self.read()
            entries.append(entry)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".audit_", suffix=".json")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(entries, f, indent=2, default=str)
                    f.write("\n")
                os.replace(tmp, self.path)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
        return entry
