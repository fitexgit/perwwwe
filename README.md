# English Subtitle Bot v2.0

Telegram bot: video → English SRT (Whisper).

## Features
- English SRT only (no translation)
- Large files via Telethon (API_ID + API_HASH) up to 400MB
- faster-whisper (small/medium on strong servers)
- Progress updates while transcribing
- Optional hardsub burn

## Env
See `.env.example`

## Run
```bash
pip install -r requirements.txt
python bot.py
```

## Model tips
| Server | Model | Device |
|--------|-------|--------|
| Weak (1GB) | base / tiny | cpu + int8 |
| Strong CPU | small | cpu + int8 |
| GPU | medium / large-v3 | cuda + float16 |
