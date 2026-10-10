"""Bounded cache of verified reader JSON, never native document handles.

The workspace owns authorization and byte-identity checks on every lookup.
Serialized values bound retained payload bytes and prevent caller mutations from
changing cached evidence. Cache data is session-only and is never written beside
an input PDF.
"""
from __future__ import annotations

from collections import OrderedDict
import json
import threading


class ReadCache:
    def __init__(self, *, max_bytes: int = 32 * 1024 * 1024, max_entries: int = 32):
        if max_bytes < 1 or max_entries < 1:
            raise ValueError('Reader cache limits must be positive')
        self.max_bytes = max_bytes
        self.max_entries = max_entries
        self._values: OrderedDict[tuple, bytes] = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()

    def get(self, key: tuple) -> dict | None:
        with self._lock:
            value = self._values.get(key)
            if value is None:
                return None
            self._values.move_to_end(key)
        return json.loads(value)

    def put(self, key: tuple, result: dict) -> bool:
        value = json.dumps(result, ensure_ascii=False, allow_nan=False,
                           separators=(',', ':')).encode('utf-8')
        with self._lock:
            previous = self._values.pop(key, None)
            if previous is not None:
                self._bytes -= len(previous)
            if len(value) > self.max_bytes:
                return False
            while self._values and (len(self._values) >= self.max_entries
                                    or self._bytes + len(value) > self.max_bytes):
                _, evicted = self._values.popitem(last=False)
                self._bytes -= len(evicted)
            self._values[key] = value
            self._bytes += len(value)
        return True

    def invalidate_document(self, ident: str) -> None:
        with self._lock:
            for key in [key for key in self._values if key[0] == ident]:
                self._bytes -= len(self._values.pop(key))

    def clear(self) -> None:
        with self._lock:
            self._values.clear()
            self._bytes = 0

    def stats(self) -> dict:
        with self._lock:
            return {'entries': len(self._values), 'bytes': self._bytes,
                    'max_entries': self.max_entries, 'max_bytes': self.max_bytes}
