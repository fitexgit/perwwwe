import os
from typing import List


def _int_env(name: str, default: int, *, minimum: int = 1) -> int:
    value = os.getenv(name, str(default)).strip() or str(default)
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return parsed


class Config:
    def __init__(self):
        self.BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
        if not self.BOT_TOKEN:
            raise ValueError("BOT_TOKEN is required")

        admin_ids = os.getenv("ADMIN_IDS", "")
        self.ADMIN_IDS: List[int] = [
            int(x.strip()) for x in admin_ids.split(",") if x.strip()
        ]

        self.API_ID = _int_env("API_ID", 0, minimum=0)
        self.API_HASH = os.getenv("API_HASH", "").strip()

        # Python-only PaaS deployments fetch the selected model into writable
        # temporary storage on first start.
        self.WHISPER_MODEL = os.getenv("WHISPER_MODEL", "tiny").strip()
        self.WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
        self.WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
        self.WHISPER_LANGUAGE = os.getenv("WHISPER_LANGUAGE", "en").strip()
        self.WHISPER_BEAM_SIZE = _int_env("WHISPER_BEAM_SIZE", 3)
        self.WHISPER_CPU_THREADS = _int_env("WHISPER_CPU_THREADS", 2)

        self.MAX_FILE_SIZE_MB = _int_env("MAX_FILE_SIZE_MB", 400)
        self.DAILY_LIMIT_FREE = _int_env("DAILY_LIMIT_FREE", 20)
        self.MAX_VIDEO_DURATION = _int_env("MAX_VIDEO_DURATION", 3600)
        self.DATABASE_PATH = os.getenv("DATABASE_PATH", "/tmp/subbot_db.json")
        self.MODEL_CACHE_DIR = os.getenv(
            "MODEL_CACHE_DIR", os.getenv("HF_HOME", "/tmp/hf_cache")
        )
        self.TEMP_DIR = os.getenv("TEMP_DIR", "/tmp")

        self.FONT_PATH = os.getenv(
            "FONT_PATH",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        )
        self.FONT_SIZE = _int_env("FONT_SIZE", 28)
        self.MARGIN_V = _int_env("MARGIN_V", 40, minimum=0)
        self.REDIS_URL = os.getenv("REDIS_URL", "")
