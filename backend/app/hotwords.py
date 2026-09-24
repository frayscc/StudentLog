from threading import Lock

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Student


SCENE_HOTWORDS = ("午休", "静校", "练习册", "班主任", "物理", "课代表", "值日", "家长", "谈话", "作业")


class HotwordRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._cached: tuple[str, ...] | None = None

    def invalidate(self) -> None:
        with self._lock:
            self._cached = None

    def get(self, db: Session) -> list[str]:
        with self._lock:
            if self._cached is None:
                names = db.scalars(select(Student.name).where(Student.status == "active").order_by(Student.name)).all()
                self._cached = tuple(dict.fromkeys([*names, *SCENE_HOTWORDS]))
            return list(self._cached)


hotword_registry = HotwordRegistry()
