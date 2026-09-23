# ربات زیرنویس انگلیسی — استقرار Python، بدون Docker

این نسخه برای اجرا به‌صورت برنامهٔ Python آماده شده است. در پروژه نه `Dockerfile` وجود دارد و نه تنظیمی که PXXL را مجبور به Build با Docker کند. دستور اجرا:

```bash
python -u bot.py
```

## راه‌اندازی در PXXL

1. محتوای این بسته را در **ریشهٔ پروژه** قرار دهید؛ همان‌جایی که `requirements.txt`، `Procfile` و `bot.py` دیده می‌شوند.
2. نوع Runtime/Builder را **Python 3.11** انتخاب کنید، نه Docker.
3. نصب وابستگی‌ها: `pip install -r requirements.txt`
4. Start command: `python -u bot.py` (یا اجرای `Procfile`)
5. متغیرهای محیطی را در پنل PXXL وارد کنید:

```text
BOT_TOKEN=توکن-ربات
ADMIN_IDS=شناسه-عددی-ادمین
WHISPER_MODEL=tiny
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8
WHISPER_ALLOW_RUNTIME_DOWNLOAD=1
HF_HOME=/tmp/hf_cache
HUGGINGFACE_HUB_CACHE=/tmp/hf_cache
MODEL_CACHE_DIR=/tmp/hf_cache
TEMP_DIR=/tmp
DATABASE_PATH=/tmp/subbot_db.json
PORT=3000
```

در نخستین اجرا مدل `tiny` از Hugging Face دریافت و در مسیر قابل‌نوشتن ذخیره می‌شود. اجرای بعدی تا وقتی آن فایل‌ها باقی باشند از همان cache استفاده می‌کند. لاگ قبلی خطای Docker هم به این دلیل بود که مقدار build-argument مدل در آن محیط به‌صورت `${WHISPER_MODEL}` باقی می‌ماند. در این نسخه مسیر Docker و آن build-argument حذف شده‌اند.

## محدودیت مهم فضای پلن رایگان

مدل محلی Whisper حتی در حالت `tiny` به فضای دیسک و RAM نیاز دارد. برنامه cache موقت pip را پیش از دریافت مدل پاک می‌کند و فضای لازم را بررسی می‌کند؛ اگر هنوز فضای آزاد کافی نباشد، با پیام واضح متوقف می‌شود، نه اینکه دانلود نصفه یا کانتینر خراب شود. در لاگ قبلی فقط **۶۷ مگابایت** آزاد گزارش شده بود؛ برای دریافت امن `tiny` حدود **۱۲۰ مگابایت فضای خالی** در مسیر writable لازم است. اگر بعد از پاک‌شدن cache همچنان کمتر از این مقدار دارید، باید فضای موقت/Volume سرویس را بیشتر کنید یا از پلنی با دیسک بیشتر استفاده کنید—هیچ تغییر Python نمی‌تواند نبود فضای ذخیره‌سازی برای وزن‌های مدل را دور بزند.

`/tmp` ماندگار نیست و ممکن است پس از تعویض کانتینر پاک شود. اگر PXXL Volume قابل‌نوشتن ارائه می‌کند، `HF_HOME`، `HUGGINGFACE_HUB_CACHE`، `MODEL_CACHE_DIR` و `DATABASE_PATH` را به همان Volume منتقل کنید. پلن رایگان همچنین به CPU/RAM کافی برای اجرای `faster-whisper` نیاز دارد.

## پیش‌نیازهای سرویس

- Python 3.11
- دسترسی خروجی اینترنت در اولین اجرا برای دریافت مدل از Hugging Face
- برنامه‌های سیستمی `ffmpeg` و `ffprobe` در `PATH`
- فضای writable برای مدل، فایل ورودی و صدای موقت

اگر پنل PXXL امکان نصب برنامهٔ سیستمی `ffmpeg` را نمی‌دهد، پیش از اجرا آن را از تنظیمات Buildpack/Nixpacks پلتفرم اضافه کنید؛ نصب package پایتون به‌تنهایی جای خودِ executable سیستمی را نمی‌گیرد.

## نکات

- برای دقت بیشتر می‌توان `WHISPER_MODEL=base` یا `small` گذاشت، اما فضای لازم بسیار بیشتر می‌شود؛ روی پلن رایگان این کار را پیشنهاد نمی‌کنیم.
- برای فایل‌های بزرگ‌تر از محدودیت دانلود Bot API، `API_ID` و `API_HASH` تلگرام را تنظیم کنید.
- برای ماندگاری آمار و cache مدل، از Volume استفاده کنید؛ `/tmp` ممکن است پاک شود.
- تنظیم سهمیه، سقف حجم و مدت در `.env.example` آمده است.