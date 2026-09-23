import os
import asyncio
import logging
import tempfile
import shutil
from pathlib import Path

from dotenv import load_dotenv
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, InputFile,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters, ConversationHandler,
)
from telegram.constants import ParseMode, ChatAction

from processor import SubtitleProcessor, PROCESSOR_VERSION
from database import Database
from config import Config
from downloader import download_media_mtproto

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

WAITING_VIDEO = 1
BOT_VERSION = "2.0.4"


def progress_bar(percent: int) -> str:
    percent = max(0, min(100, int(percent)))
    filled = percent // 10
    return "█" * filled + "░" * (10 - filled) + f" {percent}%"


def main_menu_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🎬 Generate English Subtitles"), KeyboardButton("📊 My Status")],
            [KeyboardButton("ℹ️ Help"), KeyboardButton("⚙️ Settings")],
        ],
        resize_keyboard=True,
    )


def admin_panel_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📈 Stats", callback_data="admin_stats")],
            [InlineKeyboardButton("« Back", callback_data="back_main")],
        ]
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    config: Config = context.bot_data["config"]
    text = (
        f"👋 Hi {user.first_name}!\n\n"
        f"**English Subtitle Bot** `v{BOT_VERSION}`\n"
        f"Engine: Whisper `{config.WHISPER_MODEL}` ({PROCESSOR_VERSION})\n\n"
        "Send a video and get an **English SRT** file.\n"
        f"Max size: **{config.MAX_FILE_SIZE_MB} MB**\n\n"
        "Use the buttons below or just send a video."
    )
    await update.message.reply_text(
        text, parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu_keyboard()
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    config: Config = context.bot_data["config"]
    text = (
        "📖 **Help**\n\n"
        "1. Send a video (or document video)\n"
        "2. Wait for processing\n"
        "3. Receive `subtitle_en.srt`\n\n"
        f"• Max file: {config.MAX_FILE_SIZE_MB} MB\n"
        f"• Model: `{config.WHISPER_MODEL}` on `{config.WHISPER_DEVICE}`\n"
        f"• Language: `{config.WHISPER_LANGUAGE}`\n"
        "• Output: English SRT only (no translation)\n\n"
        "For files > 20MB, API_ID + API_HASH must be set."
    )
    await update.message.reply_text(
        text, parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu_keyboard()
    )


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db: Database = context.bot_data["db"]
    config: Config = context.bot_data["config"]
    stats = await db.get_user_stats(user.id)
    text = (
        f"📊 **Your status**\n\n"
        f"Today: {stats['today_count']} / {stats.get('daily_limit', config.DAILY_LIMIT_FREE)}\n"
        f"Total jobs: {stats['total']}"
    )
    await update.message.reply_text(
        text, parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu_keyboard()
    )


async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db: Database = context.bot_data["db"]
    settings = await db.get_user_settings(user.id)
    burn = settings.get("burn_subtitles", False)
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"Burn subtitles: {'ON ✅' if burn else 'OFF ❌'}",
                    callback_data="toggle_burn",
                )
            ],
            [InlineKeyboardButton("« Back", callback_data="back_main")],
        ]
    )
    await update.message.reply_text(
        "⚙️ **Settings**\n\n"
        "Burn subtitles = hardsub video (slower, larger file).\n"
        "Default: only SRT file.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard,
    )


async def request_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 Send a video file now.",
        reply_markup=main_menu_keyboard(),
    )
    return WAITING_VIDEO


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.message
    db: Database = context.bot_data["db"]
    config: Config = context.bot_data["config"]
    processor: SubtitleProcessor = context.bot_data["processor"]

    stats = await db.get_user_stats(user.id)
    if stats.get("today_count", 0) >= stats.get("daily_limit", config.DAILY_LIMIT_FREE):
        await message.reply_text(
            "⚠️ Daily limit reached.",
            reply_markup=main_menu_keyboard(),
        )
        return ConversationHandler.END

    video = message.video or message.document
    if not video:
        await message.reply_text("Please send a valid video file.")
        return WAITING_VIDEO

    file_size_mb = (video.file_size or 0) / (1024 * 1024)
    use_mtproto = bool(config.API_ID and config.API_HASH)
    limit_mb = config.MAX_FILE_SIZE_MB if use_mtproto else min(config.MAX_FILE_SIZE_MB, 19)

    if file_size_mb > limit_mb:
        await message.reply_text(
            f"❌ File too large ({file_size_mb:.1f} MB). Limit: {limit_mb} MB.\n"
            + (
                "Set API_ID and API_HASH for larger files."
                if not use_mtproto
                else "Compress the video or send a shorter clip."
            ),
            reply_markup=main_menu_keyboard(),
        )
        return ConversationHandler.END

    status_msg = await message.reply_text(
        f"⏳ Starting...\n{progress_bar(5)}\n📦 Size: {file_size_mb:.1f} MB",
        parse_mode=ParseMode.MARKDOWN,
    )

    settings = await db.get_user_settings(user.id)
    burn = settings.get("burn_subtitles", False)
    temp_dir = None

    try:
        await context.bot.send_chat_action(
            chat_id=user.id, action=ChatAction.UPLOAD_DOCUMENT
        )
        temp_dir = Path(tempfile.mkdtemp(prefix="subbot_"))
        input_path = temp_dir / f"input_{user.id}.mp4"

        # Download
        if use_mtproto and file_size_mb > 15:
            await status_msg.edit_text(
                f"📥 Downloading via MTProto...\n{progress_bar(10)}",
                parse_mode=ParseMode.MARKDOWN,
            )
            await download_media_mtproto(
                api_id=config.API_ID,
                api_hash=config.API_HASH,
                bot_token=config.BOT_TOKEN,
                chat_id=message.chat_id,
                message_id=message.message_id,
                dest_path=str(input_path),
            )
        else:
            try:
                file = await context.bot.get_file(video.file_id)
                await file.download_to_drive(str(input_path))
            except Exception as e:
                err = str(e).lower()
                if ("too big" in err or "file is too big" in err) and use_mtproto:
                    await status_msg.edit_text(
                        f"📥 Downloading via MTProto...\n{progress_bar(10)}",
                        parse_mode=ParseMode.MARKDOWN,
                    )
                    await download_media_mtproto(
                        api_id=config.API_ID,
                        api_hash=config.API_HASH,
                        bot_token=config.BOT_TOKEN,
                        chat_id=message.chat_id,
                        message_id=message.message_id,
                        dest_path=str(input_path),
                    )
                else:
                    raise

        async def progress_callback(stage: str, percent: int):
            try:
                await status_msg.edit_text(
                    f"🔄 **{stage}**\n{progress_bar(percent)}",
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                pass

        result = await processor.process_video(
            str(input_path),
            user_id=user.id,
            progress_callback=progress_callback,
            burn_subtitles=burn,
        )

        await status_msg.edit_text(f"✅ Done!\n{progress_bar(100)}")

        if result.get("srt_path") and Path(result["srt_path"]).exists():
            with open(result["srt_path"], "rb") as f:
                await message.reply_document(
                    document=InputFile(f, filename="subtitle_en.srt"),
                    caption="📄 English subtitle (SRT)\nLoad this in your player",
                )
        else:
            await message.reply_text("❌ SRT was not created.")

        if result.get("video_path") and Path(result["video_path"]).exists():
            with open(result["video_path"], "rb") as f:
                await message.reply_video(
                    video=InputFile(f, filename="video_with_sub.mp4"),
                    caption="🎬 Video with burned-in subtitles",
                )

        await db.increment_usage(user.id)

    except Exception as e:
        logger.exception("Error processing video")
        try:
            await status_msg.edit_text(
                f"❌ Error:\n`{str(e)[:250]}`",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            await message.reply_text(f"❌ Error: {str(e)[:250]}")
    finally:
        if temp_dir and Path(temp_dir).exists():
            shutil.rmtree(temp_dir, ignore_errors=True)

    await message.reply_text(
        "You can send another video.",
        reply_markup=main_menu_keyboard(),
    )
    return ConversationHandler.END


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    config: Config = context.bot_data["config"]
    if user.id not in config.ADMIN_IDS:
        await update.message.reply_text("Access denied.")
        return
    await update.message.reply_text(
        "🛠 **Admin panel**",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=admin_panel_keyboard(),
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = query.from_user
    db: Database = context.bot_data["db"]
    config: Config = context.bot_data["config"]

    if data == "back_main":
        await query.edit_message_text("✅ Back to main menu. Use buttons below.")
        return

    if data == "toggle_burn":
        settings = await db.get_user_settings(user.id)
        new_val = not settings.get("burn_subtitles", False)
        await db.set_user_setting(user.id, "burn_subtitles", new_val)
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        f"Burn subtitles: {'ON ✅' if new_val else 'OFF ❌'}",
                        callback_data="toggle_burn",
                    )
                ],
                [InlineKeyboardButton("« Back", callback_data="back_main")],
            ]
        )
        await query.edit_message_text(
            f"⚙️ Settings\n\nBurn subtitles: **{'ON' if new_val else 'OFF'}**",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard,
        )
        return

    if data == "admin_stats" and user.id in config.ADMIN_IDS:
        stats = await db.get_global_stats()
        text = (
            f"📈 **Stats**\n\n"
            f"Users: {stats.get('total_users', 0)}\n"
            f"Total jobs: {stats.get('total_jobs', 0)}\n"
            f"Today: {stats.get('today_jobs', 0)}"
        )
        await query.edit_message_text(
            text, parse_mode=ParseMode.MARKDOWN, reply_markup=admin_panel_keyboard()
        )


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text in ("🎬 Generate English Subtitles", "Generate English Subtitles"):
        return await request_video(update, context)
    if text in ("📊 My Status", "My Status"):
        return await status_cmd(update, context)
    if text in ("ℹ️ Help", "Help"):
        return await help_cmd(update, context)
    if text in ("⚙️ Settings", "Settings"):
        return await settings_cmd(update, context)
    await update.message.reply_text(
        "Send a video or use the menu.",
        reply_markup=main_menu_keyboard(),
    )


def start_health_server():
    """Minimal HTTP server so Railway/platform healthcheck on PORT succeeds."""
    import threading
    from http.server import HTTPServer, BaseHTTPRequestHandler

    port = int(os.environ.get("PORT", "3000"))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, format, *args):
            return  # silence access logs

    def run():
        try:
            server = HTTPServer(("0.0.0.0", port), Handler)
            logger.info(f"Health server listening on 0.0.0.0:{port}")
            server.serve_forever()
        except Exception as e:
            logger.warning(f"Health server failed: {e}")

    t = threading.Thread(target=run, daemon=True)
    t.start()


def main():
    # Prefer image-baked model dir; /tmp only as fallback
    os.environ.setdefault("HF_HOME", "/app/models")
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", "/app/models")
    os.environ.setdefault("TRANSFORMERS_CACHE", "/app/models")

    config = Config()
    db = Database()
    processor = SubtitleProcessor(config)

    # Platform expects an open TCP port (healthcheck)
    start_health_server()

    app = Application.builder().token(config.BOT_TOKEN).build()
    app.bot_data["config"] = config
    app.bot_data["db"] = db
    app.bot_data["processor"] = processor

    conv = ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.VIDEO | filters.Document.VIDEO | filters.Document.ALL,
                handle_video,
            ),
            MessageHandler(
                filters.Regex("^(🎬 Generate English Subtitles|Generate English Subtitles)$"),
                request_video,
            ),
        ],
        states={
            WAITING_VIDEO: [
                MessageHandler(
                    filters.VIDEO | filters.Document.VIDEO | filters.Document.ALL,
                    handle_video,
                ),
            ],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("settings", settings_cmd))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    logger.info(f"Bot starting... version {BOT_VERSION}")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
