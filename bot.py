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
    print(f"[DOWNLOAD] Начинаю загрузку: {source} - {url}")
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
        print(f"[DOWNLOAD] Раскрытая ссылка TikTok: {url}")
    else:  # VK
        ydl_opts = {**base_opts, "format": "mp4"}

    video_id = None
    try:
        print(f"[DOWNLOAD] Загружаю видео через yt-dlp...")
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            video_id = info.get("id") or info.get("display_id") or str(hash(url))
            print(f"[DOWNLOAD] Видео загружено, ID: {video_id}")
    except DownloadError as e:
        print(f"[DOWNLOAD] Ошибка загрузки: {e}")
        if os.path.exists("video.mp4"):
            os.remove("video.mp4")
        return False
    except Exception as e:
        print(f"[DOWNLOAD] Неожиданная ошибка при загрузке: {e}")
        if os.path.exists("video.mp4"):
            os.remove("video.mp4")
        return False

    # Проверка на дубликаты
    if video_id:
        try:
            with open(POSTED_FILE, "r", encoding="utf-8") as f:
                posted_ids = f.read().splitlines()
                if video_id in posted_ids:
                    print(f"[DOWNLOAD] Видео уже публиковалось (ID: {video_id})")
                    if os.path.exists("video.mp4"):
                        os.remove("video.mp4")
                    return False
        except Exception as e:
            print(f"[DOWNLOAD] Ошибка при проверке дубликатов: {e}")

    # Проверка размера видео
    if not os.path.exists("video.mp4"):
        print("[DOWNLOAD] Файл video.mp4 не найден после загрузки")
        return False
    file_size = os.path.getsize("video.mp4")
    if file_size == 0:
        print("[DOWNLOAD] Видео пустое (0 байт)")
        os.remove("video.mp4")
        return False

    print(f"[DOWNLOAD] Размер видео: {file_size} байт ({file_size / 1024 / 1024:.2f} МБ)")

    # Отправка в канал
    try:
        print(f"[SEND] Отправляю видео в канал {CHANNEL_ID}...")
        await bot.send_video(
            chat_id=CHANNEL_ID,
            video=types.FSInputFile("video.mp4"),
            caption="😂 СМЕШНО.ТОЧКА\nПодписывайся 👇",
            supports_streaming=True
        )
        
        # Сохраняем ID опубликованного видео
        if video_id:
            try:
                with open(POSTED_FILE, "a", encoding="utf-8") as f:
                    f.write(video_id + "\n")
            except Exception as e:
                print(f"[SEND] Ошибка при сохранении ID: {e}")
        
        # Удаляем временный файл
        if os.path.exists("video.mp4"):
            os.remove("video.mp4")
        
        print(f"[SEND] Видео успешно отправлено в канал! (ID: {video_id})")
        return True
    except Exception as e:
        print(f"[SEND] Ошибка при отправке видео: {e}")
        # Пытаемся удалить файл даже при ошибке
        if os.path.exists("video.mp4"):
            try:
                os.remove("video.mp4")
            except:
                pass
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
    print("[SCHEDULER] Планировщик запущен, проверяю расписание каждые 10 секунд...")
    while True:
        await asyncio.sleep(10)  # Проверяем каждые 10 секунд для более точного времени
        try:
            now = datetime.now()
            with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
                schedule = json.load(f)
            
            if not schedule:
                continue
                
            new_schedule = []
            for item in schedule:
                post_time = datetime.fromisoformat(item['time'])
                time_diff = (post_time - now).total_seconds()
                
                # Публикуем если время наступило (в пределах 5 секунд) или прошло недавно (до 2 минут назад)
                # Это позволяет не пропустить публикацию при небольшой задержке или перезапуске бота
                if -120 <= time_diff <= 5:
                    if time_diff < 0:
                        print(f"[SCHEDULER] Время публикации прошло {int(abs(time_diff))} сек назад, публикую: {post_time.strftime('%H:%M:%S')}")
                    else:
                        print(f"[SCHEDULER] Время публикации наступило: {post_time.strftime('%H:%M:%S')}")
                    print(f"[SCHEDULER] Загружаю видео: {item['url']}")
                    try:
                        # Запускаем загрузку и отправку
                        result = await download_and_send(item['source'], item['url'])
                        if result:
                            print(f"[SCHEDULER] ✅ Видео успешно опубликовано: {item['url']}")
                        else:
                            print(f"[SCHEDULER] ❌ Ошибка при публикации видео: {item['url']}")
                    except Exception as e:
                        print(f"[SCHEDULER] ❌ Исключение при публикации: {e}")
                        import traceback
                        traceback.print_exc()
                elif time_diff > 5:
                    # Время еще не наступило, оставляем в расписании
                    new_schedule.append(item)
                    if time_diff < 300:  # Логируем если осталось меньше 5 минут
                        print(f"[SCHEDULER] До публикации осталось {int(time_diff)} сек ({int(time_diff/60)} мин): {item['url']}")
                else:
                    # Время прошло более 2 минут назад, пропускаем
                    print(f"[SCHEDULER] ⚠️ Время публикации прошло более 2 минут назад, пропускаю: {item['url']}")
            
            # Обновляем расписание
            with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
                json.dump(new_schedule, f)
        except Exception as e:
            print(f"[SCHEDULER] Ошибка в планировщике: {e}")
            await asyncio.sleep(30)

# ================== RUN ==================
async def main():
    print("[MAIN] Запуск бота...")
    print("[MAIN] Запуск планировщика публикаций...")
    # Запускаем планировщик как фоновую задачу
    scheduler_task = asyncio.create_task(scheduler())
    print("[MAIN] Планировщик запущен")
    
    # Запускаем бота
    print("[MAIN] Запуск обработчика сообщений...")
    try:
        await dp.start_polling(bot, skip_updates=True)
    except Exception as e:
        print(f"[MAIN] Ошибка Telegram: {e}")
        scheduler_task.cancel()
        await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
