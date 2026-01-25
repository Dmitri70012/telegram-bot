# Берём лёгкий Python с Debian Bullseye
FROM python:3.11-slim-bullseye

# Устанавливаем ffmpeg, git, curl
RUN apt-get update && apt-get install -y ffmpeg git curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

# Обновляем pip и устанавливаем зависимости
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Команда запуска бота
CMD ["python", "bot.py"]
