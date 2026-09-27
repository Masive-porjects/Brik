"""
In-memory session cache.
Phase 1: Simple dict store. Phase 2: Redis.
"""

from audiomind.models.audio import SessionData


class SessionCache:
    def __init__(self) -> None:
        self._store: dict[str, SessionData] = {}

    def get(self, session_id: str) -> SessionData | None:
        return self._store.get(session_id)

    def set(self, session_id: str, data: SessionData) -> None:
        self._store[session_id] = data

    def delete(self, session_id: str) -> bool:
        return self._store.pop(session_id, None) is not None

    def list_all(self) -> list[SessionData]:
        return list(self._store.values())

    def clear(self) -> int:
        count = len(self._store)
        self._store.clear()
        return count


# Global singleton
session_cache = SessionCache()
