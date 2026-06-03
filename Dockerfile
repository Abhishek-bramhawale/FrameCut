FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8000 \
    FRAMECUT_LOW_MEMORY=1 \
    FRAMECUT_MAX_CONCURRENT_JOBS=1 \
    FRAMECUT_MAX_EXPORT_WORKERS=1 \
    FRAMECUT_MAX_SCENES=100 \
    FRAMECUT_SCENE_METHOD=ffmpeg
EXPOSE 8000

CMD ["bash", "-lc", "uvicorn main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
