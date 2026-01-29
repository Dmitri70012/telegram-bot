import os
import re
import asyncio
import aiohttp
import json
import subprocess
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

POST_COUNTER_FILE = "post_counter.txt"
if not os.path.exists(POST_COUNTER_FILE):
    with open(POST_COUNTER_FILE, "w", encoding="utf-8") as f:
        f.write("0")

# ================== QUEUE ==================
video_queue = asyncio.Queue()

# ================== REGEX ==================
YT_REGEX = r"(youtube\.com|youtu\.be)"
VK_REGEX = r"(vk\.com|vk\.ru|vkvideo\.ru)"
TT_REGEX = r"(tiktok\.com|vt\.tiktok\.com|vm\.tiktok\.com)"
IG_REGEX = r"(instagram\.com/(p|reel|tv)/[^/?]+)"

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
    
    elif source == "instagram":
        # Для Instagram извлекаем shortcode из разных форматов
        patterns = [
            r"instagram\.com/(?:p|reel|tv)/([^/?]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return f"instagram:{match.group(1)}"
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

def get_post_count() -> int:
    """Возвращает текущий счетчик постов"""
    try:
        with open(POST_COUNTER_FILE, "r", encoding="utf-8") as f:
            return int(f.read().strip() or "0")
    except:
        return 0

def increment_post_count():
    """Увеличивает счетчик постов"""
    count = get_post_count() + 1
    with open(POST_COUNTER_FILE, "w", encoding="utf-8") as f:
        f.write(str(count))
    return count

def should_create_poll() -> bool:
    """Проверяет, нужно ли создавать опрос (каждый 5-й пост)"""
    return get_post_count() % 5 == 0

# ================== LLM FUNCTIONS ==================
async def generate_caption_with_llm(video_info: dict, source: str) -> dict:
    """
    Генерирует креативную подпись через LLM
    Возвращает: {
        "title": str,
        "caption": str,
        "question": str,
        "hashtags": str,
        "poll_question": str,
        "poll_options": list
    }
    """
    if not llm_client:
        print("[DEBUG] LLM клиент не инициализирован! Используется fallback с вариативностью.")
        # Fallback если нет API ключа - но с вариативностью
        title = video_info.get("title", "Видео")
        # Пытаемся извлечь тему из названия
        title_lower = title.lower()
        
        fallback_captions = [
            "Когда понимаешь что это про тебя 😂",
            "Типичная ситуация в жизни каждого 💀",
            "Это момент когда все идет не так 😅",
            "Когда пытаешься объяснить но не получается 🤣",
            "Реакция на происходящее 🔥",
            "Когда случайно делаешь что-то не то 😆",
            "Ощущение когда понимаешь что ты в беде 😭",
            "Когда думаешь что все под контролем 🤪",
            "Тот момент когда все понятно без слов 😂",
            "Когда пытаешься быть крутым но не получается 💀"
        ]
        
        fallback_questions = [
            "А у вас такое было?",
            "Узнали себя?",
            "Знакомо?",
            "Было такое?",
            "У вас так бывает?",
            "Это про вас?",
            "Узнаете ситуацию?",
            "Знакомая ситуация?",
            "Бывало у вас?",
            "Это вы?"
        ]
        
        # Выбираем случайные варианты
        caption = random.choice(fallback_captions)
        question = random.choice(fallback_questions)
        emoji = random.choice(["😂", "😅", "🤣", "💀", "🔥", "😆", "😭", "🤪"])
        
        return {
            "title": f"{emoji} СМЕШНО.ТОЧКА",
            "caption": caption,
            "question": question,
            "hashtags": "#жиза #смешно #мемы",
            "poll_question": "Оцените уровень смешного",
            "poll_options": ["1-3", "4-6", "7-8", "9-10"]
        }
    
    # Формируем контекст для LLM
    title = video_info.get("title", "Видео")
    description = video_info.get("description", "")[:500]  # Ограничиваем длину
    duration = video_info.get("duration", 0)
    uploader = video_info.get("uploader", "")
    tags = video_info.get("tags", [])
    tags_str = ", ".join(tags[:10]) if isinstance(tags, list) else str(tags)[:200]
    categories = video_info.get("categories", [])
    categories_str = ", ".join(categories[:5]) if isinstance(categories, list) else ""
    
    # Генерируем случайный стиль для разнообразия
    styles = [
        "ироничный комментарий",
        "смешное наблюдение",
        "мемный формат",
        "саркастичный комментарий",
        "юмористическое замечание",
        "остроумный комментарий"
    ]
    selected_style = random.choice(styles)
    
    context = f"""
Проанализируй это видео и создай УНИКАЛЬНЫЙ креативный контент для Telegram-канала "СМЕШНО.ТОЧКА".

ВАЖНО: Каждый раз создавай РАЗНЫЕ подписи! Не повторяйся!

Информация о видео:
- Название: {title}
- Описание: {description[:400]}
- Длительность: {duration} сек
- Источник: {source}
- Автор: {uploader}
- Теги: {tags_str}
- Категории: {categories_str}

Создай УНИКАЛЬНЫЙ контент:
1. Креативный короткий заголовок (до 50 символов, БЕЗ эмодзи в начале, БЕЗ слова "СМЕШНО.ТОЧКА")
2. {selected_style} к видео (1-2 предложения, НЕ используй слово "Жиза" каждый раз, будь креативным!)
3. Один вовлекающий вопрос к аудитории (разные формулировки каждый раз)
4. 3-5 релевантных хэштегов по теме видео (без #, через пробел)
5. Вопрос для опроса
6. 4 варианта ответа для опроса (короткие, до 20 символов каждый)

Стили подписей для разнообразия:
- "Когда ты...", "Это момент когда...", "Типичная ситуация...", "Поведение когда...", "Реакция на...", "Когда понимаешь что...", "Тот момент...", "Когда пытаешься...", "Ситуация когда...", "Когда видишь...", "Ощущение когда...", "Когда случайно...", "Когда думаешь что...", "Когда наконец...", "Когда осознаешь...", "Когда пытаешься объяснить...", "Когда все идет не так...", "Когда понимаешь что ты...", "Когда случайно делаешь...", "Когда пытаешься быть..."

Ответь ТОЛЬКО в формате JSON:
{{
    "title": "уникальный заголовок",
    "caption": "уникальная подпись в стиле {selected_style}",
    "question": "уникальный вопрос",
    "hashtags": "хэштег1 хэштег2 хэштег3",
    "poll_question": "вопрос для опроса",
    "poll_options": ["вариант1", "вариант2", "вариант3", "вариант4"]
}}
"""
    
    try:
        print(f"[DEBUG] Генерирую подпись для видео: {title[:50]}...")
        response = await llm_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Ты креативный контент-менеджер для юмористического Telegram-канала. ВАЖНО: Каждый раз создавай РАЗНЫЕ, УНИКАЛЬНЫЕ подписи! Не повторяйся! Используй разные стили, форматы, вопросы. Будь креативным и разнообразным."},
                {"role": "user", "content": context}
            ],
            temperature=1.2,  # Увеличил для большей вариативности
            max_tokens=600,
            response_format={"type": "json_object"}
        )
        
        result = json.loads(response.choices[0].message.content)
        
        # Добавляем эмодзи к заголовку (случайный выбор)
        emoji_options = ["😂", "😅", "🤣", "😆", "💀", "😭", "🤪", "😎", "🔥", "✨"]
        emoji = random.choice(emoji_options)
        title_text = result.get('title', 'СМЕШНО.ТОЧКА').strip()
        # Убираем "СМЕШНО.ТОЧКА" если оно есть в заголовке
        if "СМЕШНО.ТОЧКА" in title_text.upper():
            title_text = title_text.replace("СМЕШНО.ТОЧКА", "").replace("смешно.точка", "").strip()
        result["title"] = f"{emoji} {title_text}" if title_text else f"{emoji} СМЕШНО.ТОЧКА"
        
        # Улучшаем подпись - добавляем эмодзи если его нет
        caption_text = result.get("caption", "").strip()
        if caption_text and not any(ord(c) > 127 for c in caption_text[:10]):  # Проверяем наличие эмодзи
            caption_emojis = ["😂", "😅", "🤣", "💀", "🔥"]
            result["caption"] = f"{caption_text} {random.choice(caption_emojis)}"
        else:
            result["caption"] = caption_text
        
        # Форматируем хэштеги
        hashtags_str = result.get("hashtags", "")
        if hashtags_str:
            hashtag_list = [tag.strip() for tag in hashtags_str.split() if tag.strip()][:5]
            result["hashtags"] = " ".join([f"#{tag}" for tag in hashtag_list])
        else:
            # Генерируем хэштеги на основе тегов видео
            fallback_tags = ["жиза", "смешно", "мемы", "юмор"]
            if tags_str:
                # Пытаемся использовать теги из видео
                video_tags = [tag.lower().strip() for tag in tags_str.split(",")[:3] if tag.strip()]
                fallback_tags = video_tags + fallback_tags[:3-len(video_tags)]
            result["hashtags"] = " ".join([f"#{tag}" for tag in fallback_tags[:5]])
        
        print(f"[DEBUG] Сгенерирована подпись: {result.get('caption', '')[:50]}...")
        return result
        
    except Exception as e:
        print(f"[DEBUG] LLM error: {e}")
        import traceback
        traceback.print_exc()
        # Fallback при ошибке - но с вариативностью
        fallback_captions = [
            "Когда понимаешь что это про тебя 😂",
            "Типичная ситуация в жизни каждого 💀",
            "Это момент когда все идет не так 😅",
            "Когда пытаешься объяснить но не получается 🤣",
            "Реакция на происходящее 🔥",
            "Когда случайно делаешь что-то не то 😆",
            "Ощущение когда понимаешь что ты в беде 😭",
            "Когда думаешь что все под контролем 🤪"
        ]
        fallback_questions = [
            "А у вас такое было?",
            "Узнали себя?",
            "Знакомо?",
            "Было такое?",
            "У вас так бывает?",
            "Это про вас?",
            "Узнаете ситуацию?",
            "Знакомая ситуация?"
        ]
        return {
            "title": f"{random.choice(['😂', '😅', '🤣', '💀', '🔥'])} СМЕШНО.ТОЧКА",
            "caption": random.choice(fallback_captions),
            "question": random.choice(fallback_questions),
            "hashtags": "#жиза #смешно #мемы",
            "poll_question": "Оцените уровень смешного",
            "poll_options": ["1-3", "4-6", "7-8", "9-10"]
        }

# ================== VIDEO PROCESSING ==================
async def create_thumbnail(video_path: str) -> str:
    """Создает обложку из первого кадра видео"""
    thumbnail_path = "thumbnail.jpg"
    try:
        # Используем ffmpeg для извлечения первого кадра
        cmd = [
            "ffmpeg",
            "-i", video_path,
            "-ss", "00:00:00",
            "-vframes", "1",
            "-vf", "scale=1280:720:force_original_aspect_ratio=decrease",
            thumbnail_path,
            "-y"  # Перезаписать если существует
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await process.communicate()
        
        if os.path.exists(thumbnail_path):
            return thumbnail_path
    except Exception as e:
        print(f"[DEBUG] Thumbnail creation error: {e}")
    return None

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
            "• VK / VK Video\n"
            "• Instagram (Reels, Posts, TV)"
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
    elif re.search(IG_REGEX, text):
        source = "instagram"
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
    cookies_valid = False
    if source == "youtube":
        is_shorts = "/shorts/" in text or "youtube.com/shorts" in text
        
        # Проверяем валидность cookies файла заранее
        cookies_file = "youtube_cookies.txt"
        has_cookies = os.path.exists(cookies_file)
        if has_cookies:
            try:
                with open(cookies_file, "r", encoding="utf-8") as f:
                    cookies_content = f.read()
                    # Проверяем, что файл не пустой и содержит нужные данные
                    if cookies_content.strip() and ("youtube.com" in cookies_content or "domain" in cookies_content.lower()):
                        cookies_valid = True
                        print(f"[DEBUG] Cookies файл найден и валиден ({len(cookies_content)} символов)")
                    else:
                        print(f"[DEBUG] Cookies файл пустой или невалидный")
            except Exception as e:
                print(f"[DEBUG] Ошибка чтения cookies: {e}")
                cookies_valid = False

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
                # Если есть валидные cookies, пробуем их использовать в первую очередь
                configs_to_try = []
                
                # Если есть cookies, добавляем конфигурации с cookies в приоритете
                if cookies_valid:
                    configs_to_try.extend([
                        # Конфигурация 1: Android с cookies (самый надежный)
                        {
                            "client": ["android"],
                            "user_agent": "com.google.android.youtube/19.09.37 (Linux; U; Android 11) gzip",
                            "use_extractor_args": True,
                            "age_gate": False,
                            "use_cookies": True,
                        },
                        # Конфигурация 2: iOS с cookies
                        {
                            "client": ["ios"],
                            "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
                            "use_extractor_args": True,
                            "age_gate": False,
                            "use_cookies": True,
                        },
                        # Конфигурация 3: Android + iOS с cookies
                        {
                            "client": ["android", "ios"],
                            "user_agent": "com.google.android.youtube/19.09.37 (Linux; U; Android 11) gzip",
                            "use_extractor_args": True,
                            "age_gate": False,
                            "use_cookies": True,
                        },
                    ])
                
                # Добавляем конфигурации без cookies (или если cookies нет)
                configs_to_try.extend([
                    # Конфигурация: Android клиент (лучше всего для Shorts)
                    {
                        "client": ["android"],
                        "user_agent": "com.google.android.youtube/19.09.37 (Linux; U; Android 11) gzip",
                        "use_extractor_args": True,
                        "age_gate": False,
                        "use_cookies": cookies_valid,
                    },
                    # Конфигурация: iOS клиент
                    {
                        "client": ["ios"],
                        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
                        "use_extractor_args": True,
                        "age_gate": False,
                        "use_cookies": cookies_valid,
                    },
                    # Конфигурация: Android + iOS комбинация
                    {
                        "client": ["android", "ios"],
                        "user_agent": "com.google.android.youtube/19.09.37 (Linux; U; Android 11) gzip",
                        "use_extractor_args": True,
                        "age_gate": False,
                        "use_cookies": cookies_valid,
                    },
                    # Конфигурация: iOS + Android + mweb
                    {
                        "client": ["ios", "android", "mweb"],
                        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
                        "use_extractor_args": True,
                        "age_gate": False,
                        "use_cookies": cookies_valid,
                    },
                    # Конфигурация: Mobile web
                    {
                        "client": ["mweb"],
                        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
                        "use_extractor_args": True,
                        "age_gate": False,
                        "use_cookies": cookies_valid,
                    },
                    # Конфигурация: Android с обходом возрастных ограничений
                    {
                        "client": ["android"],
                        "user_agent": "com.google.android.youtube/19.09.37 (Linux; U; Android 11) gzip",
                        "use_extractor_args": True,
                        "age_gate": True,
                        "use_cookies": cookies_valid,
                    },
                    # Конфигурация: iOS с обходом возрастных ограничений
                    {
                        "client": ["ios"],
                        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
                        "use_extractor_args": True,
                        "age_gate": True,
                        "use_cookies": cookies_valid,
                    },
                    # Конфигурация: Desktop web
                    {
                        "client": ["web"],
                        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        "use_extractor_args": True,
                        "age_gate": False,
                        "use_cookies": cookies_valid,
                    },
                    # Конфигурация: Без extractor_args (иногда помогает)
                    {
                        "client": None,
                        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        "use_extractor_args": False,
                        "age_gate": False,
                        "use_cookies": cookies_valid,
                    },
                ])
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
                        # Пробуем разные форматы для Shorts
                        format_selector = "best[height<=1080][ext=mp4]/best[ext=mp4]/bestvideo[height<=1080]+bestaudio/best[height<=1080]/bestvideo+bestaudio/best"
                    else:
                        format_selector = "best[height<=1080][ext=mp4]/best[ext=mp4]/best"
                    
                    # Базовые заголовки
                    headers = {
                        "User-Agent": config["user_agent"],
                        "Accept": "*/*",
                        "Accept-Language": "en-US,en;q=0.9",
                        "Accept-Encoding": "gzip, deflate, br",
                        "Referer": "https://www.youtube.com/",
                        "Origin": "https://www.youtube.com",
                    }
                    
                    # Для Shorts добавляем дополнительные заголовки
                    if is_shorts:
                        headers.update({
                            "X-YouTube-Client-Name": "1" if "android" in str(config.get("client", [])).lower() else "2",
                            "X-YouTube-Client-Version": "19.09.37" if "android" in str(config.get("client", [])).lower() else "17.33.2",
                        })
                    
                    ydl_opts = {
                        **base_opts,
                        "format": format_selector,
                        "merge_output_format": "mp4",
                        "noplaylist": True,  # Не скачивать плейлисты
                        "http_headers": headers,
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
                        
                        # Дополнительные параметры для обхода защиты Shorts
                        ydl_opts["no_warnings"] = False  # Показываем предупреждения для диагностики
                        ydl_opts["ignoreerrors"] = False  # Не игнорируем ошибки
                        ydl_opts["extract_flat"] = False  # Полное извлечение информации
                    else:
                        # Добавляем extractor_args только если нужно
                        if config["use_extractor_args"] and config["client"]:
                            ydl_opts["extractor_args"] = {
                                "youtube": {
                                    "player_client": config["client"],
                                }
                            }
                    
                    # Используем cookies если указано в конфигурации и файл валиден
                    if config.get("use_cookies", False) and cookies_valid:
                        ydl_opts["cookiefile"] = cookies_file
                        print(f"[DEBUG] Используем cookies для попытки {idx + 1}")
                    elif has_cookies and not is_shorts:
                        # Для обычных видео используем cookies если есть
                        ydl_opts["cookiefile"] = cookies_file
                    
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

        elif source == "vk":
            ydl_opts = {
                **base_opts,
                "format": "mp4",
            }
            
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(text, download=True)
                video_id = info.get("id")

        else:  # Instagram
            ydl_opts = {
                **base_opts,
                "format": "best[ext=mp4]/best",
                "extractor_args": {
                    "instagram": {
                        "webpage_download_timeout": 120,
                    }
                },
            }
            
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(text, download=True)
                # Для Instagram используем shortcode как video_id
                video_id = info.get("id") or info.get("shortcode") or info.get("display_id")

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
                    # Формируем информативное сообщение
                    cookies_status = "✅ Найден" if cookies_valid else "❌ Не найден или невалиден"
                    attempts_info = "Попробовано несколько методов"
                    try:
                        attempts_info = f"Попробовано методов: {len(configs_to_try)}"
                    except:
                        pass
                    
                    error_msg = (
                        f"⚠️ Не удалось скачать YouTube Shorts после всех попыток.\n\n"
                        f"📊 Статус:\n"
                        f"   • Cookies: {cookies_status}\n"
                        f"   • {attempts_info}\n\n"
                        f"🔧 Решения:\n"
                    )
                    
                    if not cookies_valid:
                        error_msg += (
                            f"1️⃣ Экспортируй cookies (ВАЖНО!):\n"
                            f"   • Установи расширение 'Get cookies.txt LOCALLY'\n"
                            f"   • Зайди на youtube.com и авторизуйся\n"
                            f"   • Экспортируй cookies в файл 'youtube_cookies.txt'\n"
                            f"   • Загрузи файл в папку с ботом\n"
                            f"   • Убедись, что файл содержит данные (не пустой)\n\n"
                        )
                    
                    error_msg += (
                        f"2️⃣ Обнови yt-dlp до последней версии:\n"
                        f"   pip install -U yt-dlp\n\n"
                        f"3️⃣ Проверь:\n"
                        f"   • Доступно ли видео (не приватное, не удалено)\n"
                        f"   • Подожди 5-10 минут и попробуй снова\n"
                        f"   • Попробуй другую ссылку на Shorts\n\n"
                        f"💡 Если проблема сохраняется, проверь логи бота для деталей."
                    )
                    
                    await msg.answer(error_msg)
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
        elif source == "instagram":
            if "Login required" in err or "Private" in err:
                await msg.answer(
                    "🚫 Instagram требует авторизацию или видео приватное.\n"
                    "Попробуй публичную ссылку."
                )
            elif "Video unavailable" in err or "Not available" in err:
                await msg.answer(
                    "❌ Видео недоступно или удалено.\n"
                    "Проверь ссылку."
                )
            else:
                await msg.answer(
                    f"❌ Ошибка скачивания из Instagram: {e}\n\n"
                    "💡 Попробуй:\n"
                    "• Проверить, что ссылка правильная\n"
                    "• Убедиться, что пост/реел публичный\n"
                    "• Подождать несколько минут и попробовать снова"
                )
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

    # ---------- Добавляем в очередь ----------
    await video_queue.put({
        "video_path": "video.mp4",
        "video_id": video_id,
        "normalized_url": normalized_url,
        "source": source,
        "info": info,
        "user_msg": msg
    })
    
    await msg.answer("✅ Видео добавлено в очередь обработки")

# ================== QUEUE PROCESSOR ==================
async def process_video_queue():
    """Обрабатывает очередь видео"""
    while True:
        try:
            task = await video_queue.get()
            
            video_path = task["video_path"]
            video_id = task["video_id"]
            normalized_url = task["normalized_url"]
            source = task["source"]
            info = task["info"]
            user_msg = task["user_msg"]
            
            # Проверяем существование видео
            if not os.path.exists(video_path):
                await user_msg.answer("❌ Файл видео не найден")
                video_queue.task_done()
                continue
            
            # ---------- Генерация подписи через LLM ----------
            await user_msg.answer("🤖 Генерирую креативную подпись...")
            
            llm_content = await generate_caption_with_llm(info, source)
            
            # Формируем финальную подпись
            caption_parts = [
                llm_content["title"],
                "",
                llm_content["caption"],
                "",
                f"💬 {llm_content['question']}",
                "",
                llm_content["hashtags"]
            ]
            final_caption = "\n".join(caption_parts)
            
            # ---------- Создание обложки ----------
            thumbnail_path = None
            if os.path.exists(video_path):
                thumbnail_path = await create_thumbnail(video_path)
            
            # ---------- Публикация ----------
            try:
                video_file = types.FSInputFile(video_path)
                send_kwargs = {
                    "chat_id": CHANNEL_ID,
                    "video": video_file,
                    "caption": final_caption,
                    "supports_streaming": True
                }
                
                # Добавляем обложку если есть
                if thumbnail_path and os.path.exists(thumbnail_path):
                    send_kwargs["thumbnail"] = types.FSInputFile(thumbnail_path)
                
                sent_message = await bot.send_video(**send_kwargs)
                
                # ---------- Сохранение данных ----------
                with open(POSTED_FILE, "a", encoding="utf-8") as f:
                    f.write(video_id + "\n")
                
                add_link_to_posted(normalized_url)
                post_count = increment_post_count()
                
                # ---------- Создание опроса (каждый 5-й пост) ----------
                if should_create_poll() and llm_content.get("poll_question"):
                    await asyncio.sleep(2)  # Небольшая задержка перед опросом
                    try:
                        poll_options = llm_content.get("poll_options", [])
                        if len(poll_options) >= 2:
                            # Ограничиваем до 4 вариантов (лимит Telegram)
                            poll_options = poll_options[:4]
                            
                            await bot.send_poll(
                                chat_id=CHANNEL_ID,
                                question=llm_content["poll_question"],
                                options=poll_options,
                                is_anonymous=False,
                                reply_to_message_id=sent_message.message_id
                            )
                    except Exception as poll_error:
                        print(f"[DEBUG] Poll error: {poll_error}")
                
                # ---------- Очистка ----------
                if os.path.exists(video_path):
                    os.remove(video_path)
                if thumbnail_path and os.path.exists(thumbnail_path):
                    os.remove(thumbnail_path)
                
                await user_msg.answer(f"✅ Опубликовано (пост #{post_count})")
                
                # ⏸ паузы против блокировок
                await asyncio.sleep(4 if source == "youtube" else 6)
                
            except Exception as e:
                await user_msg.answer(f"❌ Ошибка при отправке в канал: {e}")
                print(f"[DEBUG] Publication error: {e}")
                if os.path.exists(video_path):
                    os.remove(video_path)
                if thumbnail_path and os.path.exists(thumbnail_path):
                    os.remove(thumbnail_path)
            
            video_queue.task_done()
            
        except Exception as e:
            print(f"[DEBUG] Queue processor error: {e}")
            await asyncio.sleep(5)

# ================== RUN ==================
async def main():
    # Запускаем обработчик очереди в фоне
    queue_task = asyncio.create_task(process_video_queue())
    
    while True:
        try:
            await dp.start_polling(bot)
        except Exception as e:
            print(f"[DEBUG] Telegram error: {e}")
            await asyncio.sleep(5)

asyncio.run(main())
