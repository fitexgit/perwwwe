"""Small atomic JSON store for deployments without a database service."""
import asyncio
import json
import logging
import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _empty_data() -> dict:
    return {"users": {}, "stats": {"total_jobs": 0, "today": {}, "premium": []}}


class Database:
    def __init__(self, path: str = "/tmp/subbot_db.json", daily_limit: int = 20):
        self.path = Path(path)
        self.daily_limit = daily_limit
        self._lock = asyncio.Lock()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            probe = self.path.parent / ".subbot_write_test"
            probe.write_text("", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            fallback = Path("/tmp/subbot_db.json")
            if self.path == fallback:
                raise
            self.path = fallback
            self.path.parent.mkdir(parents=True, exist_ok=True)
            logger.warning("Database directory is not writable (%s); using %s", exc, self.path)
        if not self.path.exists():
            self._write(_empty_data())

    def _read(self) -> dict:
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                raise ValueError("database root must be an object")
            data.setdefault("users", {})
            data.setdefault("stats", {"total_jobs": 0, "today": {}, "premium": []})
            return data
        except (OSError, json.JSONDecodeError, ValueError):
            logger.exception("Could not read database file %s; starting with empty data", self.path)
            return _empty_data()

    def _write(self, data: dict):
        """Write-then-rename prevents a crash from truncating the only copy."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".subbot_db_", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass

    def _get_user(self, data: dict, user_id: int) -> dict:
        users = data.setdefault("users", {})
        user = users.setdefault(str(user_id), {})
        user.setdefault("today_count", 0)
        user.setdefault("today_date", str(date.today()))
        user.setdefault("total", 0)
        user.setdefault("daily_limit", None)
        user.setdefault("settings", {"burn_subtitles": False})
        return user

    async def get_user_stats(self, user_id: int) -> Dict[str, Any]:
        async with self._lock:
            data = self._read()
            user = self._get_user(data, user_id)
            if user.get("today_date") != str(date.today()):
                user["today_count"] = 0
                user["today_date"] = str(date.today())
                self._write(data)
            return {
                "today_count": user.get("today_count", 0),
                "daily_limit": user.get("daily_limit") or self.daily_limit,
                "total": user.get("total", 0),
            }

    async def increment_usage(self, user_id: int):
        async with self._lock:
            data = self._read()
            user = self._get_user(data, user_id)
            if user.get("today_date") != str(date.today()):
                user["today_count"] = 0
                user["today_date"] = str(date.today())
            user["today_count"] = user.get("today_count", 0) + 1
            user["total"] = user.get("total", 0) + 1
            stats = data.setdefault("stats", {})
            stats["total_jobs"] = stats.get("total_jobs", 0) + 1
            today = str(date.today())
            today_map = stats.setdefault("today", {})
            today_map[today] = today_map.get(today, 0) + 1
            self._write(data)

    async def get_user_settings(self, user_id: int) -> dict:
        async with self._lock:
            data = self._read()
            user = self._get_user(data, user_id)
            return dict(user.get("settings", {"burn_subtitles": False}))

    async def set_user_setting(self, user_id: int, key: str, value):
        async with self._lock:
            data = self._read()
            user = self._get_user(data, user_id)
            user.setdefault("settings", {})[key] = value
            self._write(data)

    async def get_global_stats(self) -> dict:
        async with self._lock:
            data = self._read()
            stats = data.get("stats", {})
            users = data.get("users", {})
            today = str(date.today())
            return {
                "total_users": len(users),
                "total_jobs": stats.get("total_jobs", 0),
                "today_jobs": stats.get("today", {}).get(today, 0),
                "premium_users": len(stats.get("premium", [])),
            }