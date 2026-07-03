FROM mwader/static-ffmpeg:latest AS static-ffmpeg
FROM denoland/deno:bin AS deno-bin
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY --from=static-ffmpeg /ffmpeg /usr/local/bin/ffmpeg
COPY --from=static-ffmpeg /ffprobe /usr/local/bin/ffprobe
COPY --from=deno-bin /deno /usr/local/bin/deno

COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .
RUN mkdir -p /data/downloads

CMD ["python", "-m", "app.bot.main"]
