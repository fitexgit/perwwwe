import os
import asyncio
import logging
import tempfile
import subprocess
import shutil
import glob
from pathlib import Path
from typing import Callable, Optional, Awaitable

from faster_whisper import WhisperModel

from config import Config

logger = logging.getLogger(__name__)
PROCESSOR_VERSION = "2.1.0"


class SubtitleProcessor:
    def __init__(self, config: Config):
        self.config = config
        self.model = None
        self.ffmpeg_path = "ffmpeg"
        self._setup_ffmpeg()
        self._load_model()

    def _setup_ffmpeg(self):
        ffmpeg_bin = shutil.which("ffmpeg")
        if not ffmpeg_bin:
            raise RuntimeError("ffmpeg is missing from PATH; install the system ffmpeg package.")
        if not shutil.which("ffprobe"):
            raise RuntimeError("ffprobe is missing from PATH; install the system ffmpeg package.")
        self.ffmpeg_path = ffmpeg_bin
        logger.info("System ffmpeg ready at: %s", self.ffmpeg_path)

    def _load_model(self):
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        cache_root = Path(self.config.MODEL_CACHE_DIR)
        repo_cache = cache_root / f"models--Systran--faster-whisper-{self.config.WHISPER_MODEL}"
        snapshots = sorted(glob.glob(str(repo_cache / "snapshots" / "*")))
        local_models = [
            Path(path) for path in snapshots
            if (Path(path) / "model.bin").is_file()
        ]
        direct_model = cache_root / self.config.WHISPER_MODEL
        model_source = str(local_models[-1]) if local_models else (
            str(direct_model) if (direct_model / "model.bin").is_file() else None
        )

        logger.info(
            f"Loading Whisper: {self.config.WHISPER_MODEL} "
            f"device={self.config.WHISPER_DEVICE} "
            f"compute={self.config.WHISPER_COMPUTE_TYPE} "
            f"source={'baked model' if model_source else 'runtime download'} "
            f"(v{PROCESSOR_VERSION})"
        )
        if model_source is None:
            if os.getenv("WHISPER_ALLOW_RUNTIME_DOWNLOAD", "0").lower() not in ("1", "true", "yes"):
                raise RuntimeError(
                    f"Whisper model '{self.config.WHISPER_MODEL}' is not included in this image. "
                    "Set WHISPER_MODEL=tiny (the free-tier default) or rebuild with "
                    "WHISPER_MODEL set to the desired model. Runtime downloads are disabled."
                )
            download_root = Path(self.config.TEMP_DIR) / "hf_cache"
            download_root.mkdir(parents=True, exist_ok=True)
            available_mb = shutil.disk_usage(download_root).free / (1024 * 1024)
            required_mb = {
                "tiny": 100, "base": 200, "small": 600, "medium": 1800,
                "large-v2": 3200, "large-v3": 3200,
            }.get(self.config.WHISPER_MODEL, 1200)
            if available_mb < required_mb:
                raise RuntimeError(
                    f"Not enough writable disk for Whisper '{self.config.WHISPER_MODEL}': "
                    f"{available_mb:.0f} MB free, approximately {required_mb} MB required. "
                    "Bake the model into the image instead."
                )
            model_source = self.config.WHISPER_MODEL
            download_root = str(download_root)
        else:
            download_root = None

        kwargs = {
            "device": self.config.WHISPER_DEVICE,
            "compute_type": self.config.WHISPER_COMPUTE_TYPE,
            "cpu_threads": self.config.WHISPER_CPU_THREADS,
            "num_workers": 1,
        }
        if download_root:
            kwargs["download_root"] = download_root
        self.model = WhisperModel(
            model_source,
            **kwargs,
        )
        logger.info("Whisper model loaded successfully")

    async def process_video(
        self,
        video_path: str,
        user_id: int,
        progress_callback: Optional[Callable[[str, int], Awaitable[None]]] = None,
        burn_subtitles: bool = False,
    ) -> dict:
        temp_dir = Path(tempfile.mkdtemp(prefix=f"proc_{user_id}_", dir=self.config.TEMP_DIR))
        result = {"srt_path": None, "video_path": None, "work_dir": str(temp_dir)}

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
        except Exception:
            logger.exception("Processing failed")
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise

    async def _extract_audio(self, video_path: str, audio_path: str):
        def _run():
            probe = subprocess.run(
                [
                    "ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1", video_path,
                ],
                capture_output=True, text=True, timeout=30,
            )
            if probe.returncode == 0 and probe.stdout.strip():
                duration = float(probe.stdout.strip())
                if duration > self.config.MAX_VIDEO_DURATION:
                    raise RuntimeError(
                        f"Video is {duration / 60:.1f} minutes; maximum allowed is "
                        f"{self.config.MAX_VIDEO_DURATION / 60:.0f} minutes."
                    )
                # 16 kHz, mono, signed 16-bit PCM is ~1.83 MiB/minute.
                audio_required_mb = duration * 32000 / (1024 * 1024) + 12
                free_mb = shutil.disk_usage(Path(audio_path).parent).free / (1024 * 1024)
                if free_mb < audio_required_mb:
                    raise RuntimeError(
                        f"Not enough temporary disk for extracted audio: {free_mb:.0f} MB "
                        f"free, about {audio_required_mb:.0f} MB required. "
                        "Use a shorter video or allocate more writable storage."
                    )
            cmd = [
                self.ffmpeg_path, "-y", "-i", video_path,
                "-vn",
                "-acodec", "pcm_s16le", "-ac", "1", "-ar", "16000",
                audio_path,
            ]
            r = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=self.config.MAX_VIDEO_DURATION + 180,
            )
            if r.returncode != 0:
                raise RuntimeError(f"ffmpeg extract failed: {r.stderr[:400]}")
        await asyncio.to_thread(_run)

    def _transcribe(self, audio_path: str):
        lang = self.config.WHISPER_LANGUAGE or None
        if lang in ("auto", "none", ""):
            lang = None

        segments, info = self.model.transcribe(
            audio_path,
            beam_size=self.config.WHISPER_BEAM_SIZE,
            language=lang,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=400),
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
            r = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=self.config.MAX_VIDEO_DURATION * 2 + 300,
            )
            if r.returncode != 0:
                raise RuntimeError(f"ffmpeg burn failed: {r.stderr[:400]}")
        await asyncio.to_thread(_run)
