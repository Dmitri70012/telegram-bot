# Новый базовый образ
FROM python:3.11-slim-bullseye

# Устанавливаем ffmpeg и зависимости
RUN apt-get update && apt-get install -y ffmpeg git curl && rm -rf /var/lib/apt/lists/*

# Копируем проект
WORKDIR /app
COPY . /app

# Устанавливаем зависимости Python
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Запуск бота
CMD ["python", "bot.py"]
