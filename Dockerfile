FROM python:3.11-slim

WORKDIR /app

ARG WHISPER_MODEL=tiny
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TMPDIR=/tmp \
    MODEL_CACHE_DIR=/app/models \
    WHISPER_MODEL=${WHISPER_MODEL} \
    WHISPER_DEVICE=cpu \
    WHISPER_COMPUTE_TYPE=int8 \
    WHISPER_CPU_THREADS=2

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake weights into the image. On PaaS/free plans the application filesystem
# may be read-only and /tmp may be too small for downloading Whisper at boot.
RUN mkdir -p /app/models && \
    HF_HOME=/app/models HUGGINGFACE_HUB_CACHE=/app/models \
    python -c "from faster_whisper import WhisperModel; import os; model=os.environ['WHISPER_MODEL']; print('Baking Whisper model:', model); WhisperModel(model, device='cpu', compute_type='int8', download_root='/app/models'); print('Model ready')"

COPY . .

CMD ["python", "bot.py"]