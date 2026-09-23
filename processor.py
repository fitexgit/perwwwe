import os
import asyncio
import logging
import tempfile
import subprocess
import shutil
from pathlib import Path
from typing import Callable, Optional, Awaitable

from faster_whisper import WhisperModel
import static_ffmpeg

from config import Config

logger = logging.getLogger(__name__)
PROCESSOR_VERSION = "2.0.3"


class SubtitleProcessor:
    def __init__(self, config: Config):
        self.config = config
        self.model = None
        self.ffmpeg_path = "ffmpeg"
        self._setup_ffmpeg()
        self._load_model()

    def _setup_ffmpeg(self):
        try:
            static_ffmpeg.add_paths()
            ffmpeg_bin = shutil.which("ffmpeg")
            if ffmpeg_bin:
                self.ffmpeg_path = ffmpeg_bin
                logger.info(f"Static ffmpeg ready at: {self.ffmpeg_path}")
            else:
                logger.warning("ffmpeg not found in PATH")
        except Exception as e:
            logger.warning(f"static-ffmpeg setup failed: {e}")

    def _load_model(self):
        # Read-only app FS — force all caches into /tmp
        cache_root = "/tmp/hf_cache"
        os.makedirs(cache_root, exist_ok=True)
        os.environ["HF_HOME"] = cache_root
        os.environ["HUGGINGFACE_HUB_CACHE"] = cache_root
        os.environ["TRANSFORMERS_CACHE"] = cache_root
        os.environ["XDG_CACHE_HOME"] = "/tmp"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

        logger.info(
            f"Loading Whisper: {self.config.WHISPER_MODEL} "
            f"device={self.config.WHISPER_DEVICE} "
            f"compute={self.config.WHISPER_COMPUTE_TYPE} (v{PROCESSOR_VERSION})"
        )
        self.model = WhisperModel(
            self.config.WHISPER_MODEL,
            device=self.config.WHISPER_DEVICE,
            compute_type=self.config.WHISPER_COMPUTE_TYPE,
            download_root=cache_root,
        )
        logger.info("Whisper model loaded successfully")

    async def process_video(
        self,
        video_path: str,
        user_id: int,
        progress_callback: Optional[Callable[[str, int], Awaitable[None]]] = None,
        burn_subtitles: bool = False,
    ) -> dict:
        temp_dir = Path(tempfile.mkdtemp(prefix=f"proc_{user_id}_"))
        result = {"srt_path": None, "video_path": None}

        try:
            if progress_callback:
                await progress_callback("Extracting audio...", 10)
            audio_path = temp_dir / "audio.wav"
            await self._extract_audio(video_path, str(audio_path))

            if progress_callback:
                await progress_callback("Speech recognition (Whisper)...", 25)

            stop_flag = {"done": False}

            async def heartbeat():
                pct = 25
                while not stop_flag["done"] and pct < 85:
                    await asyncio.sleep(12)
                    if stop_flag["done"]:
                        break
                    pct = min(pct + 5, 85)
                    if progress_callback:
                        try:
                            await progress_callback(
                                f"Transcribing... ({pct}%)", pct
                            )
                        except Exception:
                            pass

            hb = asyncio.create_task(heartbeat())
            try:
                segments = await asyncio.to_thread(self._transcribe, str(audio_path))
            finally:
                stop_flag["done"] = True
                hb.cancel()
                try:
                    await hb
                except Exception:
                    pass

            logger.info(f"Transcribed {len(segments)} segments")

            if progress_callback:
                await progress_callback("Building English SRT...", 90)

            srt_path = temp_dir / "subtitle_en.srt"
            self._write_srt(segments, str(srt_path))
            result["srt_path"] = str(srt_path)

            if burn_subtitles:
                if progress_callback:
                    await progress_callback("Burning subtitles...", 95)
                output_video = temp_dir / "output_with_sub.mp4"
                try:
                    await self._burn_subtitles(
                        video_path, str(srt_path), str(output_video)
                    )
                    result["video_path"] = str(output_video)
                except Exception as e:
                    logger.warning(f"Burn skipped: {e}")

            if progress_callback:
                await progress_callback("Done", 100)
            return result
        except Exception as e:
            logger.exception("Processing failed")
            raise e

    async def _extract_audio(self, video_path: str, audio_path: str):
        def _run():
            cmd = [
                self.ffmpeg_path, "-y", "-i", video_path,
                "-acodec", "pcm_s16le", "-ac", "1", "-ar", "16000",
                audio_path,
            ]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(f"ffmpeg extract failed: {r.stderr[:400]}")
        await asyncio.to_thread(_run)

    def _transcribe(self, audio_path: str):
        lang = self.config.WHISPER_LANGUAGE or None
        if lang in ("auto", "none", ""):
            lang = None

        segments, info = self.model.transcribe(
            audio_path,
            beam_size=5,
            language=lang,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
        )
        result = []
        for seg in segments:
            text = seg.text.strip()
            if text:
                result.append({
                    "start": seg.start,
                    "end": seg.end,
                    "text": text,
                })
        return result

    def _write_srt(self, segments: list, srt_path: str):
        def format_time(seconds: float) -> str:
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            s = int(seconds % 60)
            ms = int((seconds - int(seconds)) * 1000)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

        with open(srt_path, "w", encoding="utf-8") as f:
            for i, seg in enumerate(segments, 1):
                f.write(f"{i}\n")
                f.write(f"{format_time(seg['start'])} --> {format_time(seg['end'])}\n")
                f.write(f"{seg['text']}\n\n")

    async def _burn_subtitles(self, video_path: str, srt_path: str, output_path: str):
        style = (
            f"FontSize={self.config.FONT_SIZE},"
            f"PrimaryColour=&H00FFFFFF,"
            f"OutlineColour=&H00000000,"
            f"BorderStyle=1,Outline=2,Shadow=1,"
            f"MarginV={self.config.MARGIN_V},Alignment=2"
        )
        srt_escaped = srt_path.replace("\\", "/").replace(":", "\\:")

        def _run():
            cmd = [
                self.ffmpeg_path, "-y", "-i", video_path,
                "-vf", f"subtitles={srt_escaped}:force_style='{style}'",
                "-c:a", "copy", "-c:v", "libx264",
                "-preset", "fast", "-crf", "23",
                output_path,
            ]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(f"ffmpeg burn failed: {r.stderr[:400]}")
        await asyncio.to_thread(_run)
