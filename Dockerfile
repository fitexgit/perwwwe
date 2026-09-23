FROM python:3.11-slim

WORKDIR /app

# Writable caches inside image layers (populated at build time)
ENV HF_HOME=/app/models
ENV HUGGINGFACE_HUB_CACHE=/app/models
ENV TRANSFORMERS_CACHE=/app/models
ENV XDG_CACHE_HOME=/app/models
ENV TMPDIR=/tmp

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download Whisper model into the image (avoids runtime /tmp disk limit)
# base ≈ 145MB — fits constrained hosts; override with WHISPER_MODEL at runtime only if already cached
ARG WHISPER_MODEL=base
RUN mkdir -p /app/models && python -c "\
from faster_whisper import WhisperModel;\
print('Downloading Whisper model: base');\
WhisperModel('base', device='cpu', compute_type='int8', download_root='/app/models');\
print('Model ready');\
"

COPY . .

CMD ["python", "bot.py"]
