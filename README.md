# Video Saver Telegram Bot

Telegram-бот принимает ссылку на видео (YouTube, TikTok, Instagram, VK, RuTube и другие сайты, поддерживаемые `yt-dlp`), показывает варианты качества и скачивает файл через `yt-dlp`/`ffmpeg`.

## Возможности

- Python 3.11, aiogram 3, FastAPI, Redis, RQ, PostgreSQL, Docker Compose, Nginx.
- Получение `title`, `duration`, `thumbnail` и вариантов: `360p`, `480p`, `720p`, `1080p`, `Best`, `MP3`.
- Очередь фоновых задач скачивания.
- Быстрый путь для 360p/480p/720p: сначала выбирается единый совместимый MP4 до выбранного качества, чтобы минимизировать download/merge/conversion time.
- Telegram `file_id` кэшируется в `media_cache`; повторная отправка той же ссылки и качества идёт без повторного скачивания.
- Готовые локальные MP4 кэшируются по стабильному ключу из normalized URL + quality и переиспользуются без повторного `yt-dlp`.
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

2. Заполните `BOT_TOKEN`, `PUBLIC_BASE_URL`, пароли PostgreSQL, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` для Local Telegram Bot API и при необходимости `ADMIN_USER_IDS`. Если хотите использовать стандартный Telegram Bot API, оставьте `BOT_API_BASE_URL=` пустым и не используйте local Bot API server.

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
| `BOT_API_BASE_URL` | URL local Telegram Bot API server. Для Docker по умолчанию: `http://telegram-bot-api:8081`. Если пусто, используется стандартный Telegram Bot API. |
| `TELEGRAM_API_ID` | API ID для Local Telegram Bot API server. Получается в Telegram API tools. |
| `TELEGRAM_API_HASH` | API hash для Local Telegram Bot API server. Получается в Telegram API tools. |
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

## Быстрый путь и кэширование

Для коротких публичных видео цель — минимизировать время от выбора качества до получения файла. Для `360p`, `480p` и `720p` worker сначала пытается скачать уже готовый единый MP4 (`best[ext=mp4]`) с H.264/AAC без выбора AV1/VP9 и без автоматической перекодировки. Если для `normalized_url + quality` уже есть `telegram_file_id` в таблице `media_cache`, worker сразу отправляет видео по `file_id` и не запускает `yt-dlp`. Если Telegram cache ещё нет, но готовый локальный MP4 лежит в хранилище по стабильному cache key, worker отправляет этот файл без повторного скачивания.

MP4 отправляется через `bot.send_video` с `supports_streaming=True`, `duration`, `width`, `height` из `ffprobe`; `send_document` используется только как fallback при ошибке `send_video`. Worker пишет в logs этапы `metadata_time`, `cache_lookup_time`, `download_time`, `merge_time`, `conversion_time`, `telegram_upload_time`, `total_time`.

## Совместимость видео

Для ручного выбора `1080p` и `Best` загрузчик использует расширенную логику H.264-видео (`avc1`) + AAC-аудио (`mp4a`) с объединением потоков. Если сайт всё равно отдаёт MP4/WebM с AV1, VP9 или Opus, worker после скачивания выполняет:

```bash
ffmpeg -y -i input.mp4 -c:v libx264 -preset fast -crf 23 -c:a aac -b:a 128k -movflags +faststart output_fixed.mp4
```

После конвертации файл повторно проверяется через `ffprobe`, старый файл заменяется, а итоговый путь имеет вид `<task_id>.mp4`. При ошибке `ffprobe`/`ffmpeg` задача получает статус `failed`, временные и битые файлы удаляются, пользователь получает понятное сообщение об ошибке.

## Архитектура

- `telegram-bot-api` — Local Telegram Bot API server на `http://telegram-bot-api:8081` внутри Docker-сети.
- `bot` — aiogram polling, проверка ссылок и постановка задач; зависит от `telegram-bot-api` при Docker-запуске.
- `worker` — RQ worker, быстрый cache lookup, скачивание через `yt-dlp`, проверка через `ffprobe`, конвертация несовместимых AV1/VP9/Opus файлов через `ffmpeg`, отправка MP4 через `send_video` и сохранение Telegram `file_id` в `media_cache`.
- `api` — FastAPI для healthcheck и временных download-ссылок.
- `cleanup` — периодически помечает истекшие задачи `expired` и удаляет файлы.
- `nginx` — reverse proxy к FastAPI.
- `postgres` — хранение задач и статусов.
- `redis` — очередь RQ.

## Local Telegram Bot API server

В Docker Compose добавлен сервис `telegram-bot-api` на образе `aiogram/telegram-bot-api`. Он доступен другим контейнерам по адресу:

```text
http://telegram-bot-api:8081
```

Для включения Local Telegram Bot API заполните в `.env`:

```env
BOT_API_BASE_URL=http://telegram-bot-api:8081
TELEGRAM_API_ID=123456
TELEGRAM_API_HASH=replace_me
```

Если хотите использовать стандартный Telegram Bot API, оставьте `BOT_API_BASE_URL=` пустым. Код бота в этом случае не настраивает local endpoint и использует стандартный Telegram Bot API.
