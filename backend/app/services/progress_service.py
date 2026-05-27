from __future__ import annotations

from datetime import datetime, timedelta
from threading import Lock
from typing import Any


class ProgressService:
    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}
        self._lock = Lock()

    def update(
        self,
        request_id: str | None,
        *,
        stage: str,
        label: str,
        detail: str | None = None,
        keywords: list[str] | None = None,
        active: bool = True,
    ) -> None:
        if not request_id:
            return
        self._cleanup()
        with self._lock:
            self._items[request_id] = {
                "request_id": request_id,
                "stage": stage,
                "label": label,
                "detail": detail,
                "keywords": keywords or [],
                "active": active,
                "updated_at": datetime.utcnow().isoformat(),
            }

    def get(self, request_id: str) -> dict[str, Any]:
        self._cleanup()
        with self._lock:
            return self._items.get(
                request_id,
                {
                    "request_id": request_id,
                    "stage": "waiting",
                    "label": "요청을 준비하고 있습니다.",
                    "detail": None,
                    "keywords": [],
                    "active": True,
                    "updated_at": datetime.utcnow().isoformat(),
                },
            )

    def finish(self, request_id: str | None) -> None:
        self.update(
            request_id,
            stage="done",
            label="답변을 정리했습니다.",
            detail=None,
            keywords=[],
            active=False,
        )

    def _cleanup(self) -> None:
        cutoff = datetime.utcnow() - timedelta(minutes=10)
        with self._lock:
            expired = [
                request_id
                for request_id, item in self._items.items()
                if datetime.fromisoformat(item["updated_at"]) < cutoff
            ]
            for request_id in expired:
                self._items.pop(request_id, None)


progress_service = ProgressService()
