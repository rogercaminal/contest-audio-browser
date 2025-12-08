FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

# ffmpeg for pydub
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py /app/
COPY templates /app/templates

ENV AUDIO_DIR=/data/audio \
    CABRILLO_FILE=/data/logs/contest.log \
    RECORDING_START_UTC="2025-11-30 11:55:00" \
    CONTEST_START_UTC="2025-11-30 12:00:00" \
    PRE_SECONDS=10

EXPOSE 8000
CMD ["python", "app.py"]

