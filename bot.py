import os
import re
import asyncio
import aiohttp
import json
import random
from pathlib import Path

from aiogram import Bot, Dispatcher, types
from yt_dlp import YoutubeDL, DownloadError
from dotenv import load_dotenv
from openai import AsyncOpenAI

# ================== ENV ==================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# ================== LLM INIT ==================
llm_client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

ADMIN_USERS = [456786356] # Ваш ID

# ================== INIT ==================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

ALLOWED_USERS = set(ADMIN_USERS)

# ================== UTILS ==================
async def expand_tiktok_url(url: str) -> str:
    if "tiktok.com" not in url: return url
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.get(url, allow_redirects=True) as resp:
                return str(resp.url)
    except: return url

# ================== CORE DOWNLOADER (ULTIMATE FIX) ==================
async def download_video(url: str, source: str):
    """
    Самая устойчивая конфигурация для загрузки YouTube Shorts в 2026 году.
    """
    video_filename = f"video_{random.randint(1000, 9999)}.mp4"
    cookies_file = "youtube_cookies.txt"
    
    # Оптимальные настройки для YouTube Shorts
    ydl_opts = {
        "outtmpl": video_filename,
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "ignoreerrors": False,
        "noplaylist": True,
        "geo_bypass": True,
        # Улучшенный формат: ищем лучший mp4 (видео+аудио), иначе просто лучший mp4, иначе любой лучший формат
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best", 
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    }

    if source == "youtube":
        ydl_opts.update({
            "extractor_args": {
                "youtube": {
                    "player_client": ["ios", "mweb", "android"],
                    "player_skip": ["webpage", "configs"],
                }
            }
        })
        
        if os.path.exists(cookies_file):
            ydl_opts["cookiefile"] = cookies_file
            print(f"[DEBUG] Куки найдены и будут использованы.")

    try:
        with YoutubeDL(ydl_opts) as ydl:
            # Выполняем блокирующую операцию в отдельном потоке
            info = await asyncio.to_thread(ydl.extract_info, url, download=True)
            return video_filename, info
    except Exception as e:
        if os.path.exists(video_filename):
            os.remove(video_filename)
        raise e

# ================== HANDLERS ==================
@dp.message()
async def handler(msg: types.Message):
    if msg.from_user.id not in ALLOWED_USERS or not msg.text:
        return

    text = msg.text.strip()
    if text.startswith("/start"):
        await msg.answer("🎬 Привет! Пришли ссылку на YouTube Shorts, TikTok или VK.")
        return

    # Простая проверка источника
    source = None
    if "youtube.com" in text or "youtu.be" in text: source = "youtube"
    elif "tiktok.com" in text: source = "tiktok"
    elif "vk.com" in text or "vkvideo.ru" in text: source = "vk"

    if not source:
        await msg.answer("❌ Неподдерживаемая ссылка.")
        return

    status_msg = await msg.answer(f"⏳ Начинаю обработку {source}...")

    try:
        # Для TikTok расширяем ссылку
        if source == "tiktok":
            text = await expand_tiktok_url(text)

        # Пытаемся скачать
        video_path, info = await download_video(text, source)
        
        await status_msg.edit_text("🚀 Видео получено! Генерирую описание и отправляю...")

        # (Здесь могла бы быть ваша логика OpenAI)
        caption = f"🎬 {info.get('title', 'Видео')}\n\n#смешно #shorts"
        
        video_file = types.FSInputFile(video_path)
        await bot.send_video(
            chat_id=CHANNEL_ID or msg.chat.id,
            video=video_file,
            caption=caption,
            supports_streaming=True
        )
        
        # Удаляем файл
        if os.path.exists(video_path):
            os.remove(video_path)
        await status_msg.delete()

    except Exception as e:
        err_str = str(e)
        print(f"[ERROR] {err_str}")
        
        # Информативные ошибки
        if "403" in err_str or "Forbidden" in err_str:
            await status_msg.edit_text("🚫 YouTube заблокировал доступ (403). Ваши куки устарели или IP сервера находится в черном списке. Попробуйте обновить 'youtube_cookies.txt'.")
        elif "Sign in" in err_str:
            await status_msg.edit_text("🚫 Требуется вход (Sign in). Это видео может быть приватным или иметь возрастные ограничения. Проверьте куки.")
        elif "format is not available" in err_str:
            await status_msg.edit_text("❌ Ошибка: Данный формат видео недоступен для скачивания. Попробуйте другую ссылку.")
        else:
            await status_msg.edit_text(f"❌ Ошибка загрузки: {err_str[:150]}")

async def main():
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
