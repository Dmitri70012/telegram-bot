import os
import re
import asyncio
import json
import aiohttp
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types
from yt_dlp import YoutubeDL, DownloadError
from dotenv import load_dotenv

# Импорт исключений (для разных версий aiogram)
try:
    from aiogram.exceptions import TelegramConflictError
except ImportError:
    # Для старых версий aiogram
    TelegramConflictError = Exception

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
        print(f"[DOWNLOAD] URL: {url}")
        print(f"[DOWNLOAD] Опции: {ydl_opts}")
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            video_id = info.get("id") or info.get("display_id") or info.get("webpage_url", url).split("/")[-1] or str(hash(url))
            print(f"[DOWNLOAD] Видео загружено, ID: {video_id}")
            print(f"[DOWNLOAD] Название: {info.get('title', 'N/A')}")
            print(f"[DOWNLOAD] Длительность: {info.get('duration', 'N/A')} сек")
    except DownloadError as e:
        print(f"[DOWNLOAD] ❌ Ошибка загрузки (DownloadError): {e}")
        import traceback
        traceback.print_exc()
        if os.path.exists("video.mp4"):
            try:
                os.remove("video.mp4")
            except:
                pass
        return False
    except Exception as e:
        print(f"[DOWNLOAD] ❌ Неожиданная ошибка при загрузке: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        if os.path.exists("video.mp4"):
            try:
                os.remove("video.mp4")
            except:
                pass
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
        print(f"[SEND] Размер файла для отправки: {file_size} байт ({file_size / 1024 / 1024:.2f} МБ)")
        
        if not CHANNEL_ID:
            print(f"[SEND] ❌ CHANNEL_ID не установлен!")
            return False
            
        if not bot:
            print(f"[SEND] ❌ Бот не инициализирован!")
            return False
        
        # Проверяем доступность бота
        try:
            bot_info = await bot.get_me()
            print(f"[SEND] Бот доступен: @{bot_info.username}")
        except Exception as e:
            print(f"[SEND] ⚠️ Не удалось получить информацию о боте: {e}")
        
        # Отправляем видео
        result = await bot.send_video(
            chat_id=CHANNEL_ID,
            video=types.FSInputFile("video.mp4"),
            caption="😂 СМЕШНО.ТОЧКА\nПодписывайся 👇",
            supports_streaming=True
        )
        print(f"[SEND] Видео отправлено, message_id: {result.message_id}")
        
        # Сохраняем ID опубликованного видео
        if video_id:
            try:
                with open(POSTED_FILE, "a", encoding="utf-8") as f:
                    f.write(video_id + "\n")
                print(f"[SEND] ID сохранен в {POSTED_FILE}: {video_id}")
            except Exception as e:
                print(f"[SEND] ⚠️ Ошибка при сохранении ID: {e}")
        
        # Удаляем временный файл
        if os.path.exists("video.mp4"):
            try:
                os.remove("video.mp4")
                print(f"[SEND] Временный файл удален")
            except Exception as e:
                print(f"[SEND] ⚠️ Не удалось удалить временный файл: {e}")
        
        print(f"[SEND] ✅ Видео успешно отправлено в канал! (ID: {video_id})")
        return True
    except Exception as e:
        print(f"[SEND] ❌ Ошибка при отправке видео: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
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
    
    # ---------- /schedule ----------
    if text.startswith("/schedule"):
        try:
            if os.path.exists(SCHEDULE_FILE):
                with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
                    schedule = json.load(f)
                if not schedule:
                    await msg.answer("📅 Расписание пустое")
                else:
                    now = datetime.now()
                    schedule_text = f"📅 Запланировано публикаций: {len(schedule)}\n\n"
                    for idx, item in enumerate(schedule, 1):
                        post_time = datetime.fromisoformat(item['time'])
                        time_diff = (post_time - now).total_seconds()
                        url_short = item['url'][:40] + "..." if len(item['url']) > 40 else item['url']
                        if time_diff > 0:
                            schedule_text += f"{idx}. {post_time.strftime('%H:%M')} ({int(time_diff/60)} мин)\n{url_short}\n\n"
                        else:
                            schedule_text += f"{idx}. {post_time.strftime('%H:%M')} (прошло)\n{url_short}\n\n"
                    await msg.answer(schedule_text)
            else:
                await msg.answer("📅 Файл расписания не найден")
        except Exception as e:
            await msg.answer(f"❌ Ошибка при чтении расписания: {e}")
        return

    # ---------- Если ждём время ----------
    pending = user_pending.get(msg.from_user.id)
    if pending:
        print(f"[HANDLER] Ожидается время от пользователя {msg.from_user.id}, получен текст: '{text}'")
        time_text = text.strip()
        
        # Строгая проверка формата времени HH:MM
        time_pattern = r'^(\d{1,2}):(\d{2})$'
        match = re.match(time_pattern, time_text)
        
        if match:
            try:
                hour = int(match.group(1))
                minute = int(match.group(2))
                
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
                    json.dump(schedule, f, indent=2, ensure_ascii=False)

                await msg.answer(f"✅ Запланировано на {post_time.strftime('%H:%M')}")
                user_pending.pop(msg.from_user.id)
                print(f"[HANDLER] Время успешно обработано, pending очищен")
                return
            except ValueError as e:
                print(f"[HANDLER] Ошибка валидации времени: {e}")
                await msg.answer("❌ Неверный формат времени. Используй HH:MM (например, 14:30)")
                return
            except Exception as e:
                print(f"[HANDLER] Неожиданная ошибка при обработке времени: {e}")
                import traceback
                traceback.print_exc()
                await msg.answer("❌ Ошибка при сохранении времени. Попробуй еще раз.")
                return
        else:
            print(f"[HANDLER] Текст не соответствует формату времени HH:MM: '{time_text}'")
            await msg.answer("❌ Неверный формат времени. Используй HH:MM (например, 14:30)")
            return

    # ---------- Проверка ссылки ----------
    print(f"[HANDLER] Проверяю текст как ссылку: '{text}'")
    print(f"[HANDLER] pending для пользователя {msg.from_user.id}: {user_pending.get(msg.from_user.id)}")
    
    # Проверяем, не является ли текст временем (на случай если pending был потерян)
    time_pattern = r'^(\d{1,2}):(\d{2})$'
    if re.match(time_pattern, text.strip()):
        print(f"[HANDLER] Текст похож на время, но pending отсутствует. Просим отправить ссылку.")
        await msg.answer("❌ Сначала отправь ссылку на видео, затем время публикации")
        return
    
    if re.search(YT_REGEX, text):
        source = "youtube"
        print(f"[HANDLER] Обнаружена ссылка YouTube")
    elif re.search(TT_REGEX, text):
        source = "tiktok"
        print(f"[HANDLER] Обнаружена ссылка TikTok")
    elif re.search(VK_REGEX, text):
        source = "vk"
        print(f"[HANDLER] Обнаружена ссылка VK")
    else:
        print(f"[HANDLER] Текст не является поддерживаемой ссылкой")
        await msg.answer("❌ Неподдерживаемая ссылка. Поддерживаются: YouTube, TikTok, VK")
        return

    user_pending[msg.from_user.id] = {'url': text, 'source': source}
    print(f"[HANDLER] Ссылка сохранена в pending для пользователя {msg.from_user.id}")
    await msg.answer("⏰ Введи время публикации (HH:MM)")

# ================== Планировщик ==================
async def scheduler():
    print("[SCHEDULER] Планировщик запущен, проверяю расписание каждые 10 секунд...")
    iteration = 0
    while True:
        await asyncio.sleep(10)  # Проверяем каждые 10 секунд для более точного времени
        iteration += 1
        try:
            now = datetime.now()
            print(f"[SCHEDULER] Проверка #{iteration} - Текущее время: {now.strftime('%H:%M:%S')}")
            
            if not os.path.exists(SCHEDULE_FILE):
                print(f"[SCHEDULER] Файл расписания не найден: {SCHEDULE_FILE}")
                continue
                
            with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
                schedule = json.load(f)
            
            if not schedule:
                if iteration % 6 == 0:  # Логируем каждую минуту
                    print(f"[SCHEDULER] Расписание пустое")
                continue
            
            print(f"[SCHEDULER] Найдено записей в расписании: {len(schedule)}")
            new_schedule = []
            for idx, item in enumerate(schedule):
                try:
                    post_time = datetime.fromisoformat(item['time'])
                    time_diff = (post_time - now).total_seconds()
                    
                    print(f"[SCHEDULER] Запись #{idx+1}: время={post_time.strftime('%H:%M:%S')}, разница={int(time_diff)}с, URL={item.get('url', 'N/A')[:50]}...")
                    
                    # Публикуем если время наступило (в пределах 5 секунд) или прошло недавно (до 2 минут назад)
                    # Это позволяет не пропустить публикацию при небольшой задержке или перезапуске бота
                    if -120 <= time_diff <= 5:
                        if time_diff < 0:
                            print(f"[SCHEDULER] ⏰ Время публикации прошло {int(abs(time_diff))} сек назад, публикую: {post_time.strftime('%H:%M:%S')}")
                        else:
                            print(f"[SCHEDULER] ⏰ Время публикации наступило: {post_time.strftime('%H:%M:%S')}")
                        print(f"[SCHEDULER] 📥 Загружаю видео: {item['url']} (источник: {item.get('source', 'unknown')})")
                        try:
                            # Запускаем загрузку и отправку
                            result = await download_and_send(item['source'], item['url'])
                            if result:
                                print(f"[SCHEDULER] ✅ Видео успешно опубликовано: {item['url']}")
                            else:
                                print(f"[SCHEDULER] ❌ Ошибка при публикации видео: {item['url']}")
                                # Не добавляем обратно в расписание, чтобы не зациклиться
                        except Exception as e:
                            print(f"[SCHEDULER] ❌ Исключение при публикации: {e}")
                            import traceback
                            traceback.print_exc()
                    elif time_diff > 5:
                        # Время еще не наступило, оставляем в расписании
                        new_schedule.append(item)
                        if time_diff < 300:  # Логируем если осталось меньше 5 минут
                            print(f"[SCHEDULER] ⏳ До публикации осталось {int(time_diff)} сек ({int(time_diff/60)} мин): {item['url'][:50]}...")
                    else:
                        # Время прошло более 2 минут назад, пропускаем
                        print(f"[SCHEDULER] ⚠️ Время публикации прошло более 2 минут назад, пропускаю: {item['url'][:50]}...")
                except Exception as e:
                    print(f"[SCHEDULER] ❌ Ошибка при обработке записи #{idx+1}: {e}")
                    import traceback
                    traceback.print_exc()
                    # Пропускаем проблемную запись
            
            # Обновляем расписание
            if len(new_schedule) != len(schedule):
                print(f"[SCHEDULER] Обновляю расписание: было {len(schedule)}, стало {len(new_schedule)}")
            with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
                json.dump(new_schedule, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[SCHEDULER] ❌ Критическая ошибка в планировщике: {e}")
            import traceback
            traceback.print_exc()
            await asyncio.sleep(30)

# ================== RUN ==================
async def main():
    print("[MAIN] Запуск бота...")
    
    # Останавливаем все предыдущие обновления перед запуском
    try:
        print("[MAIN] Останавливаю предыдущие обновления...")
        await bot.delete_webhook(drop_pending_updates=True)
        print("[MAIN] Предыдущие обновления удалены")
    except Exception as e:
        print(f"[MAIN] ⚠️ Не удалось удалить webhook: {e}")
    
    print("[MAIN] Запуск планировщика публикаций...")
    # Запускаем планировщик как фоновую задачу
    scheduler_task = asyncio.create_task(scheduler())
    print("[MAIN] Планировщик запущен")
    
    # Запускаем бота с обработкой конфликтов
    print("[MAIN] Запуск обработчика сообщений...")
    retry_count = 0
    max_retries = 5
    
    while retry_count < max_retries:
        try:
            await dp.start_polling(bot, skip_updates=True, close_bot_session=False)
            break  # Если успешно запустился, выходим из цикла
        except TelegramConflictError as e:
            retry_count += 1
            print(f"[MAIN] ❌ Конфликт: другой экземпляр бота уже запущен (попытка {retry_count}/{max_retries})")
            print(f"[MAIN] Убедитесь, что не запущено несколько экземпляров бота одновременно!")
            if retry_count < max_retries:
                wait_time = min(2 ** retry_count, 30)  # Экспоненциальная задержка, максимум 30 сек
                print(f"[MAIN] Ожидание {wait_time} секунд перед повторной попыткой...")
                await asyncio.sleep(wait_time)
                # Пытаемся остановить предыдущие обновления
                try:
                    await bot.delete_webhook(drop_pending_updates=True)
                except:
                    pass
            else:
                print(f"[MAIN] ❌ Достигнуто максимальное количество попыток. Остановка.")
                scheduler_task.cancel()
                raise
        except Exception as e:
            # Проверяем, не является ли это конфликтом по сообщению об ошибке
            error_str = str(e)
            if "Conflict" in error_str or "getUpdates" in error_str:
                retry_count += 1
                print(f"[MAIN] ❌ Обнаружен конфликт: другой экземпляр бота уже запущен (попытка {retry_count}/{max_retries})")
                print(f"[MAIN] Ошибка: {error_str}")
                print(f"[MAIN] Убедитесь, что не запущено несколько экземпляров бота одновременно!")
                if retry_count < max_retries:
                    wait_time = min(2 ** retry_count, 30)
                    print(f"[MAIN] Ожидание {wait_time} секунд перед повторной попыткой...")
                    await asyncio.sleep(wait_time)
                    try:
                        await bot.delete_webhook(drop_pending_updates=True)
                    except:
                        pass
                else:
                    print(f"[MAIN] ❌ Достигнуто максимальное количество попыток. Остановка.")
                    scheduler_task.cancel()
                    raise
            else:
                # Другая ошибка
                print(f"[MAIN] ❌ Ошибка Telegram: {type(e).__name__}: {e}")
                import traceback
                traceback.print_exc()
                retry_count += 1
                if retry_count < max_retries:
                    await asyncio.sleep(5)
                else:
                    print(f"[MAIN] ❌ Критическая ошибка. Остановка.")
                    scheduler_task.cancel()
                    raise
        except Exception as e:
            print(f"[MAIN] ❌ Ошибка Telegram: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            retry_count += 1
            if retry_count < max_retries:
                await asyncio.sleep(5)
            else:
                print(f"[MAIN] ❌ Критическая ошибка. Остановка.")
                scheduler_task.cancel()
                raise
    
    # Если дошли сюда, значит бот остановился
    print("[MAIN] Бот остановлен")
    scheduler_task.cancel()
    try:
        await scheduler_task
    except asyncio.CancelledError:
        pass

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[MAIN] Остановка по запросу пользователя")
    except Exception as e:
        print(f"[MAIN] Критическая ошибка при запуске: {e}")
        import traceback
        traceback.print_exc()
