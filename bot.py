import os
import re
import asyncio
import aiohttp
import json
import random
import subprocess
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

def check_ffmpeg():
    """Проверяет наличие ffmpeg в системе"""
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except FileNotFoundError:
        return False

# ================== CORE DOWNLOADER ==================
async def download_video(url: str, source: str):
    video_filename = f"video_{random.randint(1000, 9999)}.mp4"
    cookies_file = "youtube_cookies.txt"
    has_ffmpeg = check_ffmpeg()
    
    # Базовые настройки
    ydl_opts = {
        "outtmpl": video_filename,
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "ignoreerrors": False,
        "noplaylist": True,
        "geo_bypass": True,
    }

    if source == "youtube":
        # Улучшенный выбор формата для Shorts: 
        # Пытаемся взять mp4, если нет - любое видео+аудио, если нет - просто лучшее.
        if has_ffmpeg:
            ydl_opts["format"] = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"
            ydl_opts["merge_output_format"] = "mp4"
        else:
            # Если FFmpeg нет, мы ограничены только форматами, где звук уже внутри видео
            ydl_opts["format"] = "best[ext=mp4]/best"
            
        ydl_opts.update({
            "extractor_args": {
                "youtube": {
                    "player_client": ["ios", "android", "mweb"],
                    "player_skip": ["webpage", "configs"],
                }
            },
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
            }
        })
        
        if os.path.exists(cookies_file):
            ydl_opts["cookiefile"] = cookies_file
    
    elif source == "tiktok":
        # Исправление ошибки status code 0: добавляем referer и более мощный User-Agent
        ydl_opts["format"] = "bestvideo+bestaudio/best"
        ydl_opts["http_headers"] = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Referer": "https://www.tiktok.com/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        }
    
    else: # VK и прочие
        ydl_opts["format"] = "best"

    try:
        with YoutubeDL(ydl_opts) as ydl:
            # Запускаем извлечение и загрузку
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
        ffmpeg_status = "✅ FFmpeg найден" if check_ffmpeg() else "⚠️ FFmpeg НЕ НАЙДЕН (скачивание Shorts может давать ошибки)"
        await msg.answer(f"🎬 Привет! Пришли ссылку.\n\n{ffmpeg_status}\n\nПоддерживаются: YouTube, TikTok, VK.")
        return

    # Определение источника
    source = None
    if any(x in text for x in ["youtube.com", "youtu.be"]): 
        source = "youtube"
    elif any(x in text for x in ["tiktok.com"]): 
        source = "tiktok"
    elif any(x in text for x in ["vk.com", "vkvideo.ru", "vk.ru"]): 
        source = "vk"

    if not source:
        await msg.answer("❌ Ссылка не распознана.")
        return

    status_msg = await msg.answer(f"⏳ Загружаю ({source})...")

    try:
        if source == "tiktok":
            text = await expand_tiktok_url(text)

        video_path, info = await download_video(text, source)
        
        await status_msg.edit_text("🚀 Видео получено! Отправляю в канал...")

        # Генерация описания (можно вернуть логику OpenAI)
        caption = f"🎬 {info.get('title', 'Видео')}\n\n#смешно #{source}"
        
        video_file = types.FSInputFile(video_path)
        await bot.send_video(
            chat_id=CHANNEL_ID or msg.chat.id,
            video=video_file,
            caption=caption,
            supports_streaming=True
        )
        
        if os.path.exists(video_path):
            os.remove(video_path)
        await status_msg.delete()

    except Exception as e:
        err_str = str(e)
        print(f"[ERROR] {err_str}")
        
        if "403" in err_str:
            await status_msg.edit_text("🚫 Ошибка 403 (YouTube): Доступ заблокирован. Попробуйте обновить файл youtube_cookies.txt.")
        elif "format is not available" in err_str:
            await status_msg.edit_text("❌ Ошибка формата: Не удалось найти подходящее MP4 видео. На сервере может отсутствовать FFmpeg.")
        elif "status code 0" in err_str or "Video not available" in err_str:
            await status_msg.edit_text("❌ Ошибка TikTok: Сервис заблокировал запрос (Status 0). Попробуйте позже или с другой ссылкой.")
        else:
            await status_msg.edit_text(f"❌ Ошибка загрузки: {err_str[:150]}")

async def main():
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
