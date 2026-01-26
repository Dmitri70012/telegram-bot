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

ALLOWED_USERS_FILE = "allowed_users.txt"
if not os.path.exists(ALLOWED_USERS_FILE):
    open(ALLOWED_USERS_FILE, "w", encoding="utf-8").close()

if os.path.exists(ALLOWED_USERS_FILE):
    with open(ALLOWED_USERS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip().isdigit():
                ALLOWED_USERS.add(int(line.strip()))

POSTED_FILE = "posted.txt"
if not os.path.exists(POSTED_FILE):
    open(POSTED_FILE, "w", encoding="utf-8").close()

POSTED_LINKS_FILE = "posted_links.txt"
if not os.path.exists(POSTED_LINKS_FILE):
    open(POSTED_LINKS_FILE, "w", encoding="utf-8").close()

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

def add_user_to_allowed(user_id: int) -> bool:
    """Добавляет пользователя в список разрешенных"""
    if user_id in ALLOWED_USERS:
        return False  # Уже есть
    
    ALLOWED_USERS.add(user_id)
    
    # Сохраняем в файл
    with open(ALLOWED_USERS_FILE, "a", encoding="utf-8") as f:
        f.write(str(user_id) + "\n")
    
    return True

def remove_user_from_allowed(user_id: int) -> bool:
    """Удаляет пользователя из списка разрешенных"""
    if user_id not in ALLOWED_USERS or user_id in ADMIN_USERS:
        return False  # Нет в списке или это администратор
    
    ALLOWED_USERS.discard(user_id)
    
    # Перезаписываем файл без удаленного пользователя
    with open(ALLOWED_USERS_FILE, "w", encoding="utf-8") as f:
        for uid in ALLOWED_USERS:
            if uid not in ADMIN_USERS:
                f.write(str(uid) + "\n")
    
    return True

def get_allowed_users_list() -> list:
    """Возвращает список всех разрешенных пользователей"""
    return sorted(list(ALLOWED_USERS))

def normalize_url(url: str, source: str) -> str:
    """Нормализует URL для сравнения (убирает параметры, приводит к единому виду)"""
    url = url.strip()
    
    if source == "youtube":
        # Извлекаем video_id из разных форматов YouTube
        patterns = [
            r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)([a-zA-Z0-9_-]+)",
            r"youtube\.com/embed/([a-zA-Z0-9_-]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return f"youtube:{match.group(1)}"
        # Если не нашли video_id, возвращаем как есть
        return url
    
    elif source == "tiktok":
        # Для TikTok используем полную ссылку после расширения
        # Извлекаем основной путь без параметров
        match = re.search(r"(tiktok\.com/[^?]+)", url)
        if match:
            return f"tiktok:{match.group(1)}"
        return url
    
    elif source == "vk":
        # Для VK нормализуем URL, убирая параметры
        match = re.search(r"(vk\.(?:com|ru)/[^?]+)", url)
        if match:
            return f"vk:{match.group(1)}"
        return url
    
    return url

def is_link_posted(normalized_url: str) -> bool:
    """Проверяет, была ли ссылка уже обработана"""
    if not os.path.exists(POSTED_LINKS_FILE):
        return False
    
    with open(POSTED_LINKS_FILE, "r", encoding="utf-8") as f:
        posted_links = set(line.strip() for line in f if line.strip())
    
    return normalized_url in posted_links

def add_link_to_posted(normalized_url: str):
    """Добавляет ссылку в список обработанных"""
    with open(POSTED_LINKS_FILE, "a", encoding="utf-8") as f:
        f.write(normalized_url + "\n")

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
        welcome_msg = (
            "🎬 Кидай ссылку:\n"
            "• YouTube Shorts\n"
            "• TikTok\n"
            "• VK / VK Video"
        )
        
        # Добавляем информацию для администраторов
        if msg.from_user.id in ADMIN_USERS:
            welcome_msg += (
                "\n\n"
                "👑 Админ команды:\n"
                "/add_user <ID> - добавить пользователя\n"
                "/remove_user <ID> - удалить пользователя\n"
                "/list_users - список пользователей"
            )
        
        await msg.answer(welcome_msg)
        return

    # ---------- Админ команды ----------
    if msg.from_user.id in ADMIN_USERS:
        # ---------- /add_user ----------
        if text.startswith("/add_user"):
            parts = text.split()
            if len(parts) != 2:
                await msg.answer("❌ Использование: /add_user <ID_пользователя>")
                return
            
            try:
                user_id = int(parts[1])
                if add_user_to_allowed(user_id):
                    await msg.answer(f"✅ Пользователь {user_id} добавлен")
                else:
                    await msg.answer(f"⚠️ Пользователь {user_id} уже есть в списке")
            except ValueError:
                await msg.answer("❌ ID должен быть числом")
            return

        # ---------- /remove_user ----------
        if text.startswith("/remove_user"):
            parts = text.split()
            if len(parts) != 2:
                await msg.answer("❌ Использование: /remove_user <ID_пользователя>")
                return
            
            try:
                user_id = int(parts[1])
                if user_id in ADMIN_USERS:
                    await msg.answer("❌ Нельзя удалить администратора")
                    return
                
                if remove_user_from_allowed(user_id):
                    await msg.answer(f"✅ Пользователь {user_id} удален")
                else:
                    await msg.answer(f"⚠️ Пользователь {user_id} не найден в списке")
            except ValueError:
                await msg.answer("❌ ID должен быть числом")
            return

        # ---------- /list_users ----------
        if text.startswith("/list_users"):
            users = get_allowed_users_list()
            if not users:
                await msg.answer("📋 Список пользователей пуст")
                return
            
            admin_list = [f"👑 {uid} (админ)" for uid in ADMIN_USERS]
            regular_list = [f"👤 {uid}" for uid in users if uid not in ADMIN_USERS]
            
            users_text = "\n".join(admin_list + regular_list)
            await msg.answer(f"📋 Разрешенные пользователи ({len(users)}):\n\n{users_text}")
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

    # ---------- TikTok redirect (нужно сделать до нормализации) ----------
    if source == "tiktok":
        text = await expand_tiktok_url(text)

    # ---------- Проверка дубликатов по ссылке ----------
    normalized_url = normalize_url(text, source)
    if is_link_posted(normalized_url):
        await msg.answer("⚠️ Эта ссылка уже была обработана ранее")
        return

    await msg.answer(f"⏳ Загружаю ({source})...")

    # ---------- Определяем, является ли это Shorts (для YouTube) ----------
    is_shorts = False
    if source == "youtube":
        is_shorts = "/shorts/" in text or "youtube.com/shorts" in text

    # ---------- Download ----------
    try:
        # ---------- yt-dlp options ----------
        base_opts = {
            "outtmpl": "video.mp4",
            "quiet": True,
            "retries": 3,
            "fragment-retries": 3,
            "retry_sleep": 2,
            "timeout": 120,
            "socket_timeout": 120,
            "nocheckcertificate": True,
        }

        if source == "youtube":
            
            # Пробуем несколько методов обхода блокировки YouTube
            cookies_file = "youtube_cookies.txt"
            has_cookies = os.path.exists(cookies_file)
            
            # Для Shorts используем приоритетно мобильные клиенты
            if is_shorts:
                # Список конфигураций для Shorts (мобильные клиенты в приоритете)
                configs_to_try = [
                    # Конфигурация 1: Android клиент (лучше всего для Shorts)
                    {
                        "client": ["android"],
                        "user_agent": "com.google.android.youtube/19.09.37 (Linux; U; Android 11) gzip",
                        "use_extractor_args": True,
                        "age_gate": False,
                    },
                    # Конфигурация 2: iOS клиент
                    {
                        "client": ["ios"],
                        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
                        "use_extractor_args": True,
                        "age_gate": False,
                    },
                    # Конфигурация 3: Android + iOS комбинация
                    {
                        "client": ["android", "ios"],
                        "user_agent": "com.google.android.youtube/19.09.37 (Linux; U; Android 11) gzip",
                        "use_extractor_args": True,
                        "age_gate": False,
                    },
                    # Конфигурация 4: iOS + Android + mweb
                    {
                        "client": ["ios", "android", "mweb"],
                        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
                        "use_extractor_args": True,
                        "age_gate": False,
                    },
                    # Конфигурация 5: Mobile web
                    {
                        "client": ["mweb"],
                        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
                        "use_extractor_args": True,
                        "age_gate": False,
                    },
                    # Конфигурация 6: Android с обходом возрастных ограничений
                    {
                        "client": ["android"],
                        "user_agent": "com.google.android.youtube/19.09.37 (Linux; U; Android 11) gzip",
                        "use_extractor_args": True,
                        "age_gate": True,
                    },
                    # Конфигурация 7: iOS с обходом возрастных ограничений
                    {
                        "client": ["ios"],
                        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
                        "use_extractor_args": True,
                        "age_gate": True,
                    },
                    # Конфигурация 8: Desktop web (последняя попытка)
                    {
                        "client": ["web"],
                        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        "use_extractor_args": True,
                        "age_gate": False,
                    },
                    # Конфигурация 9: Без extractor_args (иногда помогает)
                    {
                        "client": None,
                        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        "use_extractor_args": False,
                        "age_gate": False,
                    },
                ]
            else:
                # Список конфигураций для обычных видео (в порядке приоритета)
                configs_to_try = [
                        # Конфигурация 1: iOS клиент
                        {
                            "client": ["ios"],
                            "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
                            "use_extractor_args": True,
                            "age_gate": False,
                        },
                        # Конфигурация 2: Android клиент
                        {
                            "client": ["android"],
                            "user_agent": "com.google.android.youtube/19.09.37 (Linux; U; Android 11) gzip",
                            "use_extractor_args": True,
                            "age_gate": False,
                        },
                        # Конфигурация 3: Mobile web
                        {
                            "client": ["mweb"],
                            "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
                            "use_extractor_args": True,
                            "age_gate": False,
                        },
                        # Конфигурация 4: Desktop web
                        {
                            "client": ["web"],
                            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                            "use_extractor_args": True,
                            "age_gate": False,
                        },
                        # Конфигурация 5: Без extractor_args (иногда помогает)
                        {
                            "client": None,
                            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                            "use_extractor_args": False,
                            "age_gate": False,
                        },
                        # Конфигурация 6: iOS + Android комбинация
                        {
                            "client": ["ios", "android"],
                            "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
                            "use_extractor_args": True,
                            "age_gate": False,
                        },
                    ]
            
            video_id = None
            last_error = None
            tried_all = False
            
            for idx, config in enumerate(configs_to_try):
                try:
                    # Отладочная информация для Shorts
                    if is_shorts:
                        print(f"[DEBUG] Shorts попытка {idx + 1}/{len(configs_to_try)}: клиент={config.get('client', 'None')}")
                    
                    # Для Shorts используем более гибкий формат
                    if is_shorts:
                        format_selector = "best[height<=1080][ext=mp4]/best[ext=mp4]/bestvideo[height<=1080]+bestaudio/best[height<=1080]/best"
                    else:
                        format_selector = "best[height<=1080][ext=mp4]/best[ext=mp4]/best"
                    
                    ydl_opts = {
                        **base_opts,
                        "format": format_selector,
                        "merge_output_format": "mp4",
                        "noplaylist": True,  # Не скачивать плейлисты
                        "http_headers": {
                            "User-Agent": config["user_agent"],
                            "Accept": "*/*",
                            "Accept-Language": "en-US,en;q=0.9",
                            "Accept-Encoding": "gzip, deflate, br",
                            "Referer": "https://www.youtube.com/",
                            "Origin": "https://www.youtube.com",
                        },
                        "postprocessors": [
                            {
                                "key": "FFmpegVideoRemuxer",
                                "preferedformat": "mp4",
                            }
                        ],
                        "postprocessor_args": ["-movflags", "+faststart"],
                    }
                    
                    # Для Shorts добавляем дополнительные параметры
                    if is_shorts:
                        ydl_opts["extractor_args"] = ydl_opts.get("extractor_args", {})
                        ydl_opts["extractor_args"]["youtube"] = ydl_opts["extractor_args"].get("youtube", {})
                        
                        # Добавляем extractor_args только если нужно
                        if config["use_extractor_args"] and config["client"]:
                            ydl_opts["extractor_args"]["youtube"]["player_client"] = config["client"]
                        
                        # Обработка возрастных ограничений
                        if config.get("age_gate", False):
                            ydl_opts["extractor_args"]["youtube"]["skip"] = ["dash", "hls"]
                            ydl_opts["age_gate"] = False
                    else:
                        # Добавляем extractor_args только если нужно
                        if config["use_extractor_args"] and config["client"]:
                            ydl_opts["extractor_args"] = {
                                "youtube": {
                                    "player_client": config["client"],
                                }
                            }
                    
                    # Используем cookies если есть (приоритет для Shorts)
                    if has_cookies:
                        ydl_opts["cookiefile"] = cookies_file
                    elif is_shorts:
                        # Для Shorts пытаемся использовать cookies даже если файл не найден
                        # (на случай если файл создастся позже)
                        pass
                    
                    with YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(text, download=True)
                        video_id = info.get("id")
                        break  # Успешно скачали
                        
                except DownloadError as e:
                    last_error = e
                    err_str = str(e)
                    # Отладочная информация для Shorts
                    if is_shorts:
                        print(f"[DEBUG] Shorts ошибка попытка {idx + 1}: {err_str[:200]}")
                    # Если это не ошибка связанная с защитой, не пробуем дальше
                    skip_errors = ["403", "Forbidden", "Failed to extract", "player response", "Sign in", "private video", "Unable to extract", "Video unavailable"]
                    # Для критических ошибок (не связанных с защитой) прерываем попытки
                    critical_errors = ["No video formats found", "Private video", "Video unavailable", "This video is not available"]
                    if any(crit_err in err_str for crit_err in critical_errors):
                        if is_shorts:
                            print(f"[DEBUG] Shorts критическая ошибка, прерываем попытки")
                        break
                    # Если это не ошибка связанная с защитой YouTube, не пробуем дальше
                    if not any(err in err_str for err in skip_errors):
                        if is_shorts:
                            print(f"[DEBUG] Shorts неизвестная ошибка, прерываем попытки")
                        break
                    # Если это последняя попытка
                    if idx == len(configs_to_try) - 1:
                        tried_all = True
                        if is_shorts:
                            print(f"[DEBUG] Shorts все попытки исчерпаны")
                    continue
                except Exception as e:
                    last_error = e
                    if idx == len(configs_to_try) - 1:
                        tried_all = True
                    continue
            
            if video_id is None:
                if tried_all:
                    raise DownloadError(last_error if last_error else "Не удалось скачать видео после всех попыток")
                else:
                    raise DownloadError(last_error if last_error else "Не удалось скачать видео")

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
            
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(text, download=True)
                video_id = info.get("id")

        else:  # VK
            ydl_opts = {
                **base_opts,
                "format": "mp4",
            }
            
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(text, download=True)
                video_id = info.get("id")

    except (DownloadError, Exception) as e:
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
        elif source == "youtube":
            # Определяем, была ли это попытка скачать Shorts
            is_shorts = "/shorts/" in text or "youtube.com/shorts" in text
            
            if "403" in err or "Forbidden" in err:
                if is_shorts:
                    await msg.answer(
                        "🚫 YouTube Shorts заблокировал доступ.\n\n"
                        "💡 Решения:\n"
                        "• Экспортируй cookies из браузера в файл 'youtube_cookies.txt'\n"
                        "• Обнови yt-dlp: pip install -U yt-dlp\n"
                        "• Попробуй позже или другую ссылку"
                    )
                else:
                    await msg.answer(
                        "🚫 YouTube заблокировал доступ после всех попыток.\n\n"
                        "💡 Решения:\n"
                        "• Экспортируй cookies из браузера в файл 'youtube_cookies.txt'\n"
                        "• Обнови yt-dlp: pip install -U yt-dlp\n"
                        "• Попробуй позже или другую ссылку"
                    )
            elif "Failed to extract" in err or "player response" in err or "Unable to extract" in err or "Sign in" in err:
                if is_shorts:
                    await msg.answer(
                        "⚠️ Не удалось скачать YouTube Shorts после всех попыток.\n\n"
                        "🔧 Решения (в порядке приоритета):\n"
                        "1️⃣ Экспортируй cookies из браузера:\n"
                        "   • Установи расширение 'Get cookies.txt LOCALLY'\n"
                        "   • Зайди на youtube.com и авторизуйся\n"
                        "   • Экспортируй cookies в файл 'youtube_cookies.txt'\n"
                        "   • Загрузи файл в папку с ботом\n\n"
                        "2️⃣ Обнови yt-dlp:\n"
                        "   pip install -U yt-dlp\n\n"
                        "3️⃣ Попробуй:\n"
                        "   • Подождать 5-10 минут\n"
                        "   • Другую ссылку на Shorts\n"
                        "   • Проверить, доступно ли видео"
                    )
                else:
                    await msg.answer(
                        "⚠️ YouTube изменил защиту.\n\n"
                        "🔧 Для Railway обнови yt-dlp:\n"
                        "1. В файле requirements.txt укажи:\n"
                        "   yt-dlp>=2025.12.8\n"
                        "2. Или через Railway CLI:\n"
                        "   railway run pip install -U yt-dlp\n"
                        "3. Перезапусти деплой\n\n"
                        "💡 Или попробуй:\n"
                        "• Другую ссылку\n"
                        "• Подождать несколько минут\n"
                        "• Экспортировать cookies в 'youtube_cookies.txt'"
                    )
            else:
                await msg.answer(f"❌ Ошибка скачивания: {e}")
        else:
            await msg.answer(f"❌ Ошибка скачивания: {e}")

        print(f"[DEBUG] yt-dlp error: {e}")
        if os.path.exists("video.mp4"):
            os.remove("video.mp4")
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

        # Сохраняем ссылку в список обработанных
        add_link_to_posted(normalized_url)

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
