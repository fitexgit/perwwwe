import os
from typing import List


class Config:
    def __init__(self):
        self.BOT_TOKEN = os.getenv("BOT_TOKEN", "")
        if not self.BOT_TOKEN:
            raise ValueError("BOT_TOKEN is required")

        admin_ids = os.getenv("ADMIN_IDS", "")
        self.ADMIN_IDS: List[int] = [
            int(x.strip()) for x in admin_ids.split(",") if x.strip().isdigit()
        ]

        self.API_ID = int(os.getenv("API_ID", "0") or "0")
        self.API_HASH = os.getenv("API_HASH", "")

        # Strong server defaults: small model is good balance
        self.WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
        self.WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
        self.WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
        self.WHISPER_LANGUAGE = os.getenv("WHISPER_LANGUAGE", "en")

        self.MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "400"))
        self.DAILY_LIMIT_FREE = int(os.getenv("DAILY_LIMIT_FREE", "20"))
        self.MAX_VIDEO_DURATION = int(os.getenv("MAX_VIDEO_DURATION", "3600"))

        self.FONT_PATH = os.getenv(
            "FONT_PATH",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        )
        self.FONT_SIZE = int(os.getenv("FONT_SIZE", "28"))
        self.MARGIN_V = int(os.getenv("MARGIN_V", "40"))
        self.REDIS_URL = os.getenv("REDIS_URL", "")
