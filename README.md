# Video Saver Telegram Bot

Telegram-бот принимает ссылку на видео (YouTube, TikTok, Instagram, VK, RuTube и другие сайты, поддерживаемые `yt-dlp`), показывает варианты качества и скачивает файл через `yt-dlp`/`ffmpeg`.

## Возможности

- Python 3.11, aiogram 3, FastAPI, Redis, RQ, PostgreSQL, Docker Compose, Nginx.
- Получение `title`, `duration`, `thumbnail` и вариантов: `360p`, `480p`, `720p`, `1080p`, `Best`, `MP3`.
- Очередь фоновых задач скачивания.
- Статусы задач: `pending`, `downloading`, `processing`, `ready`, `failed`, `expired`.
- Ограничение: 1 активная задача на пользователя; для `ADMIN_USER_IDS` ограничение отключено.
- Файлы до `MAX_TELEGRAM_FILE_MB` отправляются в Telegram, файлы больше лимита выдаются временной ссылкой на 3 часа.
- После скачивания worker проверяет файл через `ffprobe`; видео с AV1/VP9 или аудио Opus автоматически конвертируется в совместимый MP4 (H.264 + AAC).
- Итоговые видеофайлы сохраняются как `<task_id>.mp4`, битые файлы и `.part`-хвосты удаляются при ошибках.
- Автоочистка файлов с истекшим сроком жизни.
- Настраиваемый endpoint Telegram Bot API через `BOT_API_BASE_URL` для local Telegram Bot API server.

## Быстрый запуск

1. Скопируйте переменные окружения:

   ```bash
   cp .env.example .env
   ```

2. Заполните `BOT_TOKEN`, `PUBLIC_BASE_URL`, пароли PostgreSQL и при необходимости `ADMIN_USER_IDS`.

3. Запустите сервисы:

   ```bash
   docker compose up --build
   ```

4. Перед запуском или в CI можно выполнить smoke-check без внешних Python-зависимостей:

   ```bash
   python scripts/smoke_check.py
   ```

5. Откройте проверку API:

   ```bash
   curl http://localhost/health
   ```

## Переменные окружения

| Переменная | Описание |
| --- | --- |
| `BOT_TOKEN` | Токен Telegram-бота. Не храните реальный токен в репозитории. |
| `BOT_API_BASE_URL` | Опциональный URL local Telegram Bot API server. Если пусто, используется стандартный Telegram Bot API. |
| `PUBLIC_BASE_URL` | Публичный адрес backend/Nginx для временных ссылок. |
| `DATABASE_URL` | SQLAlchemy URL PostgreSQL (`postgresql+asyncpg://...`). |
| `REDIS_URL` | URL Redis для RQ. |
| `ADMIN_USER_IDS` | JSON-список Telegram user id, для которых нет лимита активных задач. Пример: `ADMIN_USER_IDS=[123456789,987654321]`. |
| `DOWNLOADS_DIR` | Каталог скачанных файлов внутри контейнера. |
| `MAX_TELEGRAM_FILE_MB` | Лимит отправки файла в Telegram; по умолчанию 1900. |
| `DOWNLOAD_LINK_TTL_SECONDS` | Срок жизни временной ссылки; по умолчанию 10800 секунд (3 часа). |
| `CLEANUP_INTERVAL_SECONDS` | Интервал фоновой очистки. |
| `MIN_FREE_DISK_MB` | Минимальный запас свободного места перед скачиванием. |
| `RQ_QUEUE_NAME` | Имя очереди RQ. |

## Проверка проекта

Быстрая проверка структуры, синтаксиса Python, Docker Compose service names, `.env.example`, Nginx proxy и ключевых hook-ов:

```bash
python scripts/smoke_check.py
```

Полный запуск:

```bash
docker compose up --build
```

## Совместимость видео

Для вариантов `360p`, `480p`, `720p`, `1080p` и `Best` загрузчик сначала запрашивает H.264-видео (`avc1`) и AAC-аудио (`mp4a`). Если сайт всё равно отдаёт MP4/WebM с AV1, VP9 или Opus, worker после скачивания выполняет:

```bash
ffmpeg -y -i input.mp4 -c:v libx264 -preset fast -crf 23 -c:a aac -b:a 128k -movflags +faststart output_fixed.mp4
```

После конвертации файл повторно проверяется через `ffprobe`, старый файл заменяется, а итоговый путь имеет вид `<task_id>.mp4`. При ошибке `ffprobe`/`ffmpeg` задача получает статус `failed`, временные и битые файлы удаляются, пользователь получает понятное сообщение об ошибке.

## Архитектура

- `bot` — aiogram polling, проверка ссылок и постановка задач.
- `worker` — RQ worker, скачивание через `yt-dlp`, проверка через `ffprobe`, конвертация несовместимых AV1/VP9/Opus файлов через `ffmpeg` и отправка результата пользователю.
- `api` — FastAPI для healthcheck и временных download-ссылок.
- `cleanup` — периодически помечает истекшие задачи `expired` и удаляет файлы.
- `nginx` — reverse proxy к FastAPI.
- `postgres` — хранение задач и статусов.
- `redis` — очередь RQ.

## Local Telegram Bot API server

Если вы используете локальный Telegram Bot API server, задайте:

```env
BOT_API_BASE_URL=http://telegram-bot-api:8081
```

Если переменная пустая, aiogram будет работать со стандартным Telegram Bot API.
