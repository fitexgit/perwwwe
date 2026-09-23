"""Download large Telegram files via MTProto (Telethon)."""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)
_client = None


async def get_telethon_client(api_id: int, api_hash: str, bot_token: str):
    global _client
    if _client is not None and _client.is_connected():
        return _client

    from telethon import TelegramClient
    from telethon.sessions import StringSession

    _client = TelegramClient(StringSession(), api_id, api_hash)
    await _client.start(bot_token=bot_token)
    logger.info("Telethon MTProto client started")
    return _client


async def download_media_mtproto(
    api_id: int,
    api_hash: str,
    bot_token: str,
    chat_id: int,
    message_id: int,
    dest_path: str,
) -> str:
    client = await get_telethon_client(api_id, api_hash, bot_token)
    message = await client.get_messages(chat_id, ids=message_id)
    if not message or not message.media:
        raise RuntimeError("Message or media not found (Telethon)")
    path = await client.download_media(message, file=dest_path)
    if not path or not Path(path).exists():
        raise RuntimeError("Telethon download failed")
    size_mb = Path(path).stat().st_size / 1024 / 1024
    logger.info(f"Downloaded via MTProto: {path} ({size_mb:.1f} MB)")
    return str(path)


async def close_client():
    global _client
    if _client is not None:
        try:
            await _client.disconnect()
        except Exception:
            pass
        _client = None
