import os
import re
import asyncio
import aiohttp

from aiogram import Bot, Dispatcher, types
from yt_dlp import YoutubeDL, DownloadError
from dotenv import load_dotenv

# ================== ENV ==================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

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
            "• TikTok\n"
            "• VK / VK Video"
        )
        return

    # ---------- Источник ----------
    if re.search(YT_REGEX, text):
        source = "youtube"
    elif re.search(TT_REGEX, text):
        source = "tiktok"
    elif re.search(VK_REGEX, text):
        source = "vk"
    else:
        await msg.answer("❌ Неподдерживаемая ссылка")
        return

    await msg.answer(f"⏳ Загружаю ({source})...")

    # ---------- TikTok redirect ----------
    if source == "tiktok":
        text = await expand_tiktok_url(text)

    # ---------- yt-dlp options ----------
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
        # Заголовки для обхода блокировки YouTube
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        
        ydl_opts = {
            **base_opts,
            "format": "best[ext=mp4]/best",
            "merge_output_format": "mp4",
            "http_headers": {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-us,en;q=0.5",
                "Accept-Encoding": "gzip, deflate",
                "Referer": "https://www.youtube.com/",
            },
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "web"],
                    "player_skip": ["webpage", "configs"],
                }
            },
            "postprocessors": [
                {
                    "key": "FFmpegVideoRemuxer",
                    "preferedformat": "mp4",
                }
            ],
            "postprocessor_args": ["-movflags", "+faststart"],
        }
        
        # Если есть cookies файл, используем его
        cookies_file = "youtube_cookies.txt"
        if os.path.exists(cookies_file):
            ydl_opts["cookiefile"] = cookies_file

    elif source == "tiktok":
        ydl_opts = {
            **base_opts,
            "format": "mp4",
            "extractor_args": {
                "tiktok": {
                    "webpage_download_timeout": 120,
                }
            },
        }

    else:  # VK
        ydl_opts = {
            **base_opts,
            "format": "mp4",
        }

    # ---------- Download ----------
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(text, download=True)
            video_id = info.get("id")

    except DownloadError as e:
        err = str(e)

        if source == "tiktok" and "100004" in err:
            await msg.answer(
                "🚫 TikTok ограничил доступ к этому видео.\n"
                "Попробуй другое."
            )
            return

        if source == "tiktok":
            await msg.answer(
                "❌ TikTok временно не отвечает.\n"
                "Попробуй ещё раз через 10–20 секунд."
            )
        elif source == "youtube" and ("403" in err or "Forbidden" in err):
            await msg.answer(
                "🚫 YouTube заблокировал доступ.\n"
                "Попробуй:\n"
                "• Другую ссылку\n"
                "• Подождать несколько минут\n"
                "• Проверить доступность видео"
            )
        else:
            await msg.answer(f"❌ Ошибка скачивания: {e}")

        print(f"[DEBUG] yt-dlp error: {e}")
        return

    except Exception as e:
        await msg.answer(f"❌ Неизвестная ошибка: {e}")
        print(e)
        return

    # ---------- Дубликаты ----------
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

        # ⏸ паузы против блокировок
        await asyncio.sleep(4 if source == "youtube" else 6)

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
