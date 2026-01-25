import os
import re
import asyncio
import json
import aiohttp
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types
from yt_dlp import YoutubeDL, DownloadError
from dotenv import load_dotenv

# ================== ENV ==================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
ADMIN_USERS = [456786356]  # <-- твой Telegram ID

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ================== Доступ ==================
ALLOWED_USERS = set(ADMIN_USERS)
POSTED_FILE = "posted.txt"
SCHEDULE_FILE = "schedule.json"

if os.path.exists("allowed_users.txt"):
    with open("allowed_users.txt", "r", encoding="utf-8") as f:
        for line in f:
            if line.strip().isdigit():
                ALLOWED_USERS.add(int(line.strip()))

if not os.path.exists(POSTED_FILE):
    open(POSTED_FILE, "w", encoding="utf-8").close()

if not os.path.exists(SCHEDULE_FILE):
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump([], f)

# ================== REGEX ==================
YT_REGEX = r"(youtube\.com|youtu\.be)"
VK_REGEX = r"(vk\.com|vk\.ru|vkvideo\.ru)"
TT_REGEX = r"(tiktok\.com|vt\.tiktok\.com|vm\.tiktok\.com)"

# ================== UTILS ==================
async def expand_tiktok_url(url: str) -> str:
    if "vm.tiktok.com" not in url and "vt.tiktok.com" not in url:
        return url
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, allow_redirects=True) as resp:
                return str(resp.url)
    except Exception:
        return url

async def download_and_send(source, url):
    base_opts = {
        "outtmpl": "video.mp4",
        "quiet": True,
        "retries": 10,
        "fragment-retries": 10,
        "retry_sleep": 5,
        "timeout": 120,
        "socket_timeout": 120,
        "nocheckcertificate": True,
    }

    if source == "youtube":
        ydl_opts = {
            **base_opts,
            "format": "bv*[ext=mp4]+ba[ext=m4a]/mp4",
            "merge_output_format": "mp4",
        }
    elif source == "tiktok":
        ydl_opts = {
            **base_opts,
            "format": "mp4",
        }
        url = await expand_tiktok_url(url)
    else:  # VK
        ydl_opts = {**base_opts, "format": "mp4"}

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            video_id = info.get("id")
    except DownloadError as e:
        print(f"DownloadError: {e}")
        return False

    with open(POSTED_FILE, "r", encoding="utf-8") as f:
        if video_id in f.read().splitlines():
            print("Видео уже публиковалось")
            if os.path.exists("video.mp4"):
                os.remove("video.mp4")
            return False

    # Проверка размера видео
    if not os.path.exists("video.mp4"):
        print("[DEBUG] Файл video.mp4 не найден")
        return False
    if os.path.getsize("video.mp4") == 0:
        print("[DEBUG] Видео пустое")
        return False

    print(f"[DEBUG] Размер видео: {os.path.getsize('video.mp4')} байт")

    try:
        await bot.send_video(
            chat_id=CHANNEL_ID,
            video=types.FSInputFile("video.mp4"),
            caption="😂 СМЕШНО.ТОЧКА\nПодписывайся 👇",
            supports_streaming=True
        )
        with open(POSTED_FILE, "a", encoding="utf-8") as f:
            f.write(video_id + "\n")
        os.remove("video.mp4")
        print(f"[DEBUG] Видео успешно отправлено: {video_id}")
        return True
    except Exception as e:
        print(f"[DEBUG] Ошибка при отправке видео: {e}")
        return False

# ================== HANDLER ==================
user_pending = {}  # {user_id: {'url': ..., 'source': ...}}

@dp.message()
async def handler(msg: types.Message):
    if msg.from_user.id not in ALLOWED_USERS:
        return

    text = msg.text.strip()
    print(f"[DEBUG] Received message: {text}")
    print(f"[DEBUG] user_pending: {user_pending}")

    # ---------- /start ----------
    if text.startswith("/start"):
        await msg.answer("🎬 Кидай ссылку и я спрошу время публикации")
        return

    # ---------- Если ждём время ----------
    pending = user_pending.get(msg.from_user.id)
    if pending:
        time_text = text
        try:
            hour, minute = map(int, time_text.split(":"))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError("Invalid time range")
            now = datetime.now()
            post_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if post_time < now:
                post_time += timedelta(days=1)

            with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
                schedule = json.load(f)
            schedule.append({"url": pending['url'],
                             "source": pending['source'],
                             "time": post_time.isoformat()})
            with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
                json.dump(schedule, f)

            await msg.answer(f"✅ Запланировано на {post_time.strftime('%H:%M')}")
            user_pending.pop(msg.from_user.id)
            return
        except Exception:
            await msg.answer("❌ Неверный формат времени. Используй HH:MM")
            return

    # ---------- Проверка ссылки ----------
    if re.search(YT_REGEX, text):
        source = "youtube"
    elif re.search(TT_REGEX, text):
        source = "tiktok"
    elif re.search(VK_REGEX, text):
        source = "vk"
    else:
        await msg.answer("❌ Неподдерживаемая ссылка")
        return

    user_pending[msg.from_user.id] = {'url': text, 'source': source}
    await msg.answer("⏰ Введи время публикации (HH:MM)")

# ================== Планировщик ==================
async def scheduler():
    while True:
        await asyncio.sleep(30)
        now = datetime.now()
        with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
            schedule = json.load(f)
        new_schedule = []
        for item in schedule:
            post_time = datetime.fromisoformat(item['time'])
            if now >= post_time:
                try:
                    task = asyncio.create_task(download_and_send(item['source'], item['url']))
                    task.add_done_callback(lambda t: print(f"[DEBUG] Task result: {t.result()}"))
                except Exception as e:
                    print(f"[DEBUG] Ошибка публикации: {e}")
            else:
                new_schedule.append(item)
        with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
            json.dump(new_schedule, f)

# ================== RUN ==================
async def main():
    asyncio.create_task(scheduler())
    while True:
        try:
            await dp.start_polling(bot)
        except Exception as e:
            print(f"Telegram error: {e}")
            await asyncio.sleep(5)

asyncio.run(main())
