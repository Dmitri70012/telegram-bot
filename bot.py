import os
import re
import asyncio
import aiohttp
import json
import random
import datetime
from pathlib import Path

from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
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

ADMIN_USERS = [
    456786356,  # <-- ТВОЙ TELEGRAM ID
]

# ================== STATES ==================
class PostStates(StatesGroup):
    waiting_for_time = State()

# ================== INIT ==================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ================== FILES & STORAGE ==================
# Определяем путь к папке со скриптом, чтобы файлы всегда были рядом
BASE_DIR = Path(__file__).parent
ALLOWED_USERS = set(ADMIN_USERS)
FILES = ["allowed_users.txt", "posted.txt", "posted_links.txt", "post_counter.txt", "scheduled_tasks.json"]

for file_name in FILES:
    file_path = BASE_DIR / file_name
    if not file_path.exists():
        with open(file_path, "w", encoding="utf-8") as f:
            if file_name == "post_counter.txt": f.write("0")
            elif file_name == "scheduled_tasks.json": f.write("[]")
            else: f.write("")
        print(f"[INIT] Создан файл: {file_path.absolute()}")
    else:
        print(f"[INIT] Файл найден: {file_path.absolute()}")

# Загрузка разрешенных пользователей
allowed_users_path = BASE_DIR / "allowed_users.txt"
with open(allowed_users_path, "r", encoding="utf-8") as f:
    for line in f:
        if line.strip().isdigit():
            ALLOWED_USERS.add(int(line.strip()))

# ================== UTILS ==================
def get_scheduled_tasks():
    tasks_path = BASE_DIR / "scheduled_tasks.json"
    with open(tasks_path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_scheduled_tasks(tasks):
    tasks_path = BASE_DIR / "scheduled_tasks.json"
    with open(tasks_path, "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=4)

async def expand_tiktok_url(url: str) -> str:
    if "tiktok.com" not in url: return url
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.get(url, allow_redirects=True) as resp:
                return str(resp.url)
    except: return url

def normalize_url(url: str, source: str) -> str:
    url = url.strip()
    if source == "youtube":
        match = re.search(r"(?:v=|be/|shorts/|embed/)([a-zA-Z0-9_-]+)", url)
        return f"youtube:{match.group(1)}" if match else url
    elif source == "tiktok":
        match = re.search(r"(tiktok\.com/[^?]+)", url)
        return f"tiktok:{match.group(1)}" if match else url
    elif source == "vk":
        match = re.search(r"(vk\.(?:com|ru|video\.ru)/[^?]+)", url)
        return f"vk:{match.group(1)}" if match else url
    return url

def is_link_posted(normalized_url: str) -> bool:
    posted_links_path = BASE_DIR / "posted_links.txt"
    with open(posted_links_path, "r", encoding="utf-8") as f:
        return normalized_url in [line.strip() for line in f]

# ================== CORE LOGIC ==================
async def download_video(url, source):
    """Скачивает видео и возвращает инфо"""
    filename = f"video_{random.randint(1000, 9999)}.mp4"
    file_path = BASE_DIR / filename
    ydl_opts = {
        "outtmpl": str(file_path),
        "quiet": True,
        "format": "best[height<=1080][ext=mp4]/best[ext=mp4]/best"
    }
    
    if source == "youtube":
        cookies_path = BASE_DIR / "youtube_cookies.txt"
        ydl_opts["cookiefile"] = str(cookies_path) if cookies_path.exists() else None
        
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return str(file_path), info
    except Exception as e:
        if file_path.exists(): os.remove(file_path)
        raise e

async def generate_caption(info, source):
    """Генерация подписи"""
    if not llm_client:
        return {"title": "🔥 СМЕШНО.ТОЧКА", "caption": "Типичная ситуация 😂", "question": "Жиза?", "hashtags": "#мемы #юмор"}
    
    return {
        "title": f"🤣 {info.get('title', 'Прикол')[:30]}",
        "caption": "Когда всё пошло не по плану",
        "question": "У вас такое бывало?",
        "hashtags": "#смешно #юмор #видео"
    }

# ================== HANDLERS ==================
@dp.message(F.text.startswith("/"))
async def cmd_handler(msg: types.Message):
    if msg.from_user.id not in ADMIN_USERS: return
    await msg.answer("Команда принята (админ-панель)")

@dp.message(F.text.regexp(r"(youtube\.com|youtu\.be|vk\.com|tiktok\.com|vkvideo\.ru)"))
async def link_handler(msg: types.Message, state: FSMContext):
    if msg.from_user.id not in ALLOWED_USERS: return

    url = msg.text.strip()
    source = "youtube" if "youtu" in url else "tiktok" if "tiktok" in url else "vk"
    
    if source == "tiktok":
        url = await expand_tiktok_url(url)
    
    norm_url = normalize_url(url, source)
    if is_link_posted(norm_url):
        await msg.answer("⚠️ Это видео уже было!")
        return

    await state.update_data(url=url, source=source, norm_url=norm_url)
    await state.set_state(PostStates.waiting_for_time)
    
    await msg.answer(
        "📝 Когда опубликовать это видео?\n\n"
        "Отправь время в формате:\n"
        "• `15:30` (сегодня или завтра)\n"
        "• `30.01.2024 12:00` (конкретная дата)\n"
        "• `сейчас` (мгновенная обработка)",
        parse_mode="Markdown"
    )

@dp.message(PostStates.waiting_for_time)
async def time_handler(msg: types.Message, state: FSMContext):
    user_data = await state.get_data()
    time_str = msg.text.lower().strip()
    
    target_dt = None
    now = datetime.datetime.now()

    try:
        if time_str == "сейчас":
            target_dt = now
        elif re.match(r"^\d{1,2}:\d{2}$", time_str):
            h, m = map(int, time_str.split(":"))
            target_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if target_dt < now:
                target_dt += datetime.timedelta(days=1)
        else:
            target_dt = datetime.datetime.strptime(time_str, "%d.%m.%Y %H:%M")
    except Exception:
        await msg.answer("❌ Неверный формат времени. Попробуй еще раз (например, 18:00):")
        return

    tasks = get_scheduled_tasks()
    tasks.append({
        "url": user_data["url"],
        "source": user_data["source"],
        "norm_url": user_data["norm_url"],
        "post_at": target_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "user_id": msg.from_user.id
    })
    save_scheduled_tasks(tasks)
    
    await state.clear()
    await msg.answer(f"✅ Запланировано на: `{target_dt.strftime('%d.%m %H:%M')}`", parse_mode="Markdown")

# ================== SCHEDULER ==================
async def scheduler_loop():
    while True:
        try:
            now = datetime.datetime.now()
            tasks = get_scheduled_tasks()
            remaining_tasks = []
            
            for task in tasks:
                post_at = datetime.datetime.strptime(task["post_at"], "%Y-%m-%d %H:%M:%S")
                
                if now >= post_at:
                    print(f"[PROCESS] Настало время для: {task['url']}")
                    try:
                        file_path, info = await download_video(task["url"], task["source"])
                        caption_data = await generate_caption(info, task["source"])
                        text = f"{caption_data['title']}\n\n{caption_data['caption']}\n\n💬 {caption_data['question']}\n\n{caption_data['hashtags']}"
                        
                        await bot.send_video(
                            chat_id=CHANNEL_ID,
                            video=types.FSInputFile(file_path),
                            caption=text,
                            supports_streaming=True
                        )
                        
                        posted_links_path = BASE_DIR / "posted_links.txt"
                        posted_path = BASE_DIR / "posted.txt"
                        with open(posted_links_path, "a") as f: f.write(task["norm_url"] + "\n")
                        with open(posted_path, "a") as f: f.write(info.get("id", "none") + "\n")
                        
                        if os.path.exists(file_path): os.remove(file_path)
                        await bot.send_message(task["user_id"], f"✅ Видео опубликовано успешно!\n{task['url']}")
                    
                    except Exception as e:
                        print(f"[ERROR] Ошибка в планировщике: {e}")
                        await bot.send_message(task["user_id"], f"❌ Ошибка публикации {task['url']}:\n{str(e)[:100]}")
                else:
                    remaining_tasks.append(task)
            
            save_scheduled_tasks(remaining_tasks)
        except Exception as e:
            print(f"[CRITICAL] Loop error: {e}")
            
        await asyncio.sleep(60)

async def main():
    asyncio.create_task(scheduler_loop())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
