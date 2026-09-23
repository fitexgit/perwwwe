import json
import asyncio
from pathlib import Path
from datetime import date
from typing import Dict, Any


class Database:
    def __init__(self, path: str = "data/db.json"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        if not self.path.exists():
            self._write({"users": {}, "stats": {"total_jobs": 0, "today": {}, "premium": []}})

    def _read(self) -> dict:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"users": {}, "stats": {"total_jobs": 0, "today": {}, "premium": []}}

    def _write(self, data: dict):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    async def get_user_stats(self, user_id: int) -> Dict[str, Any]:
        async with self._lock:
            data = self._read()
            uid = str(user_id)
            users = data.setdefault("users", {})
            user = users.setdefault(uid, {
                "today_count": 0,
                "today_date": str(date.today()),
                "total": 0,
                "daily_limit": None,
                "settings": {"burn_subtitles": False},
            })
            if user.get("today_date") != str(date.today()):
                user["today_count"] = 0
                user["today_date"] = str(date.today())
                self._write(data)
            limit = user.get("daily_limit")
            if limit is None:
                limit = 20
            return {
                "today_count": user.get("today_count", 0),
                "daily_limit": limit,
                "total": user.get("total", 0),
            }

    async def increment_usage(self, user_id: int):
        async with self._lock:
            data = self._read()
            uid = str(user_id)
            users = data.setdefault("users", {})
            user = users.setdefault(uid, {
                "today_count": 0,
                "today_date": str(date.today()),
                "total": 0,
                "settings": {"burn_subtitles": False},
            })
            if user.get("today_date") != str(date.today()):
                user["today_count"] = 0
                user["today_date"] = str(date.today())
            user["today_count"] = user.get("today_count", 0) + 1
            user["total"] = user.get("total", 0) + 1
            stats = data.setdefault("stats", {"total_jobs": 0, "today": {}})
            stats["total_jobs"] = stats.get("total_jobs", 0) + 1
            today = str(date.today())
            today_map = stats.setdefault("today", {})
            today_map[today] = today_map.get(today, 0) + 1
            self._write(data)

    async def get_user_settings(self, user_id: int) -> dict:
        async with self._lock:
            data = self._read()
            uid = str(user_id)
            user = data.setdefault("users", {}).setdefault(
                uid, {"settings": {"burn_subtitles": False}}
            )
            return user.get("settings", {"burn_subtitles": False})

    async def set_user_setting(self, user_id: int, key: str, value):
        async with self._lock:
            data = self._read()
            uid = str(user_id)
            user = data.setdefault("users", {}).setdefault(uid, {"settings": {}})
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
