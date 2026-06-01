from __future__ import annotations

import threading

from outbound_agent.models import Session


class MemorySessionStore:
    def __init__(self) -> None:
        self._items: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(
        self,
        task_id: str,
        variables: dict[str, str],
        mode: str = "rule",
        llm_config: dict[str, str] | None = None,
    ) -> Session:
        session = Session(
            task_id=task_id,
            variables=variables,
            mode=mode,
            llm_config=llm_config or {},
        )
        with self._lock:
            self._items[session.id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        with self._lock:
            return self._items.get(session_id)
