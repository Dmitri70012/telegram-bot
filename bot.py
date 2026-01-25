import os
import re
import asyncio
from aiogram import Bot, Dispatcher, types
from yt_dlp import YoutubeDL, DownloadError
from dotenv import load_dotenv

# ================== ENV ==================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

# 🔐 АДМИНЫ
ADMIN_USERS = [
    456786356,  # <-- ТВОЙ TELEGRAM ID
]

# ================== INIT ==================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ================== ДОСТУП ==================
ALLOWED_USERS = set(ADMIN_USERS)

if os.path.exists("allowed_users.txt"):
    with open("allowed_users.txt", "r", encoding="utf-8") as f:
        for line in f:
            if line.strip().isdigit():
                ALLOWED_USERS.add(int(line.strip()))

POSTED_FILE = "posted.txt"
if not os.path.exists(POSTED_FILE):
    open(POSTED_FILE, "w", encoding="utf-8").close()

# ================== REGEX ==================
YT_REGEX = r"(youtube\.com|youtu\.be)"
VK_REGEX = r"(vk\.com|vk\.ru|vkvideo\.ru)"
TT_REGEX = r"(tiktok\.com|vt\.tiktok\.com|vm\.tiktok\.com)"

# ================== HANDLER ==================
@dp.message()
async def handler(msg: types.Message):
    if msg.from_user.id not in ALLOWED_USERS:
        return

    if not msg.text:
        return

    text = msg.text.strip()

    # ---------- /start ----------
    if text.startswith("/start"):
        await msg.answer(
            "🎬 Кидай ссылку:\n"
            "• YouTube Shorts\n"
            "• VK / VK Video\n"
            "• TikTok"
        )
        return

    # ---------- Определение источника ----------
    if re.search(YT_REGEX, text):
        source = "youtube"
    elif re.search(VK_REGEX, text):
        source = "vk"
    elif re.search(TT_REGEX, text):
        source = "tiktok"
    else:
        await msg.answer("❌ Неподдерживаемая ссылка")
        return

    await msg.answer(f"⏳ Загружаю ({source})...")

    # ---------- yt-dlp (ИСПРАВЛЕННЫЕ НАСТРОЙКИ) ----------
    ydl_opts = {
        "format": "bv*[ext=mp4]+ba[ext=m4a]/mp4",
        "outtmpl": "video.mp4",
        "merge_output_format": "mp4",
        "quiet": True,
        "retries": 10,
        "fragment-retries": 10,
        "retry_sleep": 3,
        "timeout": 60,
        "nocheckcertificate": True,
        "postprocessors": [
            {
                "key": "FFmpegVideoRemuxer",
                "preferedformat": "mp4",
            }
        ],
        "postprocessor_args": [
            "-movflags", "+faststart"
        ],
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(text, download=True)
            video_id = info.get("id")

    except DownloadError as e:
        await msg.answer(f"❌ Ошибка скачивания: {e}")
        return
    except Exception as e:
        await msg.answer(f"❌ Неизвестная ошибка: {e}")
        return

    # ---------- Проверка дублей ----------
    with open(POSTED_FILE, "r", encoding="utf-8") as f:
        if video_id in f.read().splitlines():
            await msg.answer("⚠️ Это видео уже публиковалось")
            if os.path.exists("video.mp4"):
                os.remove("video.mp4")
            return

    # ---------- Публикация ----------
    try:
        caption = "😂 СМЕШНО.ТОЧКА\nПодписывайся 👇"

        await bot.send_video(
            chat_id=CHANNEL_ID,
            video=types.FSInputFile("video.mp4"),
            caption=caption,
            supports_streaming=True
        )

        with open(POSTED_FILE, "a", encoding="utf-8") as f:
            f.write(video_id + "\n")

        os.remove("video.mp4")

        await msg.answer("✅ Опубликовано")

        # 🛑 Пауза против 403 от YouTube
        await asyncio.sleep(4)

    except Exception as e:
        await msg.answer(f"❌ Ошибка при отправке в канал: {e}")
        print(e)

# ================== RUN ==================
async def main():
    while True:
        try:
            await dp.start_polling(bot)
        except Exception as e:
            print(f"[DEBUG] Telegram error: {e}")
            await asyncio.sleep(5)

asyncio.run(main())
