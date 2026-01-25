import os
import re
import asyncio
from aiogram import Bot, Dispatcher, types
from yt_dlp import YoutubeDL, DownloadError
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

# 🔐 Администраторы
ADMIN_USERS = [456786356]  # <-- ЗАМЕНИ НА СВОЙ ID
ALLOWED_USERS = set(ADMIN_USERS)

if os.path.exists("allowed_users.txt"):
    with open("allowed_users.txt", "r", encoding="utf-8") as f:
        for line in f:
            if line.strip().isdigit():
                ALLOWED_USERS.add(int(line.strip()))

POSTED_FILE = "posted.txt"
if not os.path.exists(POSTED_FILE):
    open(POSTED_FILE, "w", encoding="utf-8").close()

# 🔎 Регулярки для ссылок
YT_REGEX = r"(youtube\.com|youtu\.be)"
VK_REGEX = r"(vk\.com|vk\.ru|vkvideo\.ru)"
TT_REGEX = r"(tiktok\.com|vt\.tiktok\.com|vm\.tiktok\.com)"

bot = Bot(token=BOT_TOKEN, timeout=60)
dp = Dispatcher()

MAX_SIZE = 50 * 1024 * 1024  # 50 МБ для Telegram

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
            "• VK / vk.ru / vkvideo.ru клипы\n"
            "• TikTok видео"
        )
        return

    # ---------- /adduser ----------
    if text.startswith("/adduser"):
        if msg.from_user.id not in ADMIN_USERS:
            await msg.answer("❌ Нет прав")
            return
        parts = text.split()
        if len(parts) != 2 or not parts[1].isdigit():
            await msg.answer("Использование: /adduser <Telegram ID>")
            return
        new_id = int(parts[1])
        if new_id in ALLOWED_USERS:
            await msg.answer("⚠️ Пользователь уже добавлен")
            return
        ALLOWED_USERS.add(new_id)
        with open("allowed_users.txt", "a", encoding="utf-8") as f:
            f.write(str(new_id) + "\n")
        await msg.answer(f"✅ Пользователь {new_id} добавлен")
        return

    # ---------- Определяем источник ----------
    if re.search(YT_REGEX, text):
        source = "youtube"
        if "shorts/" in text:
            text = text.replace("shorts/", "watch?v=")  # Чтобы избежать 403
    elif re.search(VK_REGEX, text):
        source = "vk"
    elif re.search(TT_REGEX, text):
        source = "tiktok"
    else:
        await msg.answer(
            "❌ Принимаю только:\n"
            "• YouTube Shorts\n"
            "• VK / vk.ru / vkvideo.ru клипы\n"
            "• TikTok видео"
        )
        return

    await msg.answer(f"⏳ Загружаю ({source})...")

    # ---------- yt-dlp ----------
    if source == "youtube":
        ydl_opts = {
            "format": "bestvideo[height<=720]+bestaudio/best[height<=720]",
            "merge_output_format": "mp4",
            "outtmpl": "video.mp4",
            "quiet": True,
            "retries": 10,
            "fragment-retries": 10,
            "nocheckcertificate": True,
            "noplaylist": True,
            "ffmpeg_location": "/usr/bin/ffmpeg",
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0.0.0 Safari/537.36"
            }
        }
    else:
        ydl_opts = {
            "format": "mp4",
            "outtmpl": "video.mp4",
            "quiet": True,
            "retries": 10,
            "fragment-retries": 10,
            "nocheckcertificate": True,
        }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(text, download=True)

        video_id = info.get("id") or info.get("url")
        if not video_id:
            await msg.answer("❌ Не удалось получить ID видео")
            if os.path.exists("video.mp4"):
                os.remove("video.mp4")
            return
    except DownloadError as e:
        await msg.answer(f"❌ Ошибка скачивания: {str(e)}")
        if os.path.exists("video.mp4"):
            os.remove("video.mp4")
        return
    except Exception as e:
        await msg.answer(f"❌ Неизвестная ошибка: {str(e)}")
        if os.path.exists("video.mp4"):
            os.remove("video.mp4")
        return

    # ---------- Проверка дублей ----------
    with open(POSTED_FILE, "r", encoding="utf-8") as f:
        if video_id in f.read().splitlines():
            await msg.answer("⚠️ Это видео уже публиковалось")
            if os.path.exists("video.mp4"):
                os.remove("video.mp4")
            return

    # ---------- Проверка размера ----------
    file_size = os.path.getsize("video.mp4")
    if file_size > MAX_SIZE:
        await msg.answer("❌ Видео слишком большое для Telegram (>50 МБ)")
        os.remove("video.mp4")
        return

    # ---------- Публикация через FSInputFile ----------
    try:
        caption = "😂 СМЕШНО.ТОЧКА\nПодписывайся 👇"
        await bot.send_video(
            chat_id=CHANNEL_ID,
            video=types.FSInputFile("video.mp4"),
            caption=caption
        )
        with open(POSTED_FILE, "a", encoding="utf-8") as f_post:
            f_post.write(video_id + "\n")
        os.remove("video.mp4")
        await msg.answer("✅ Опубликовано")
    except Exception as e:
        await msg.answer(f"❌ Ошибка при отправке в канал: {str(e)}")
        if os.path.exists("video.mp4"):
            os.remove("video.mp4")

# ================== RUN ==================
async def main():
    while True:
        try:
            await dp.start_polling(bot)
        except Exception as e:
            print(f"[DEBUG] Telegram error: {e}")
            await asyncio.sleep(5)

asyncio.run(main())
