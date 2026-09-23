FROM python:3.11-slim

WORKDIR /app

ENV HF_HOME=/tmp/hf_cache
ENV HUGGINGFACE_HUB_CACHE=/tmp/hf_cache
ENV TRANSFORMERS_CACHE=/tmp/hf_cache
ENV XDG_CACHE_HOME=/tmp
ENV TMPDIR=/tmp

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "bot.py"]
