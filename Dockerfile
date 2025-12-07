# -----------------------------
# Base image
# -----------------------------
FROM python:3.11-slim

# -----------------------------
# Prevent Python from buffering logs
# -----------------------------
ENV PYTHONUNBUFFERED=1

# -----------------------------
# Set working directory
# -----------------------------
WORKDIR /app

# -----------------------------
# Install system packages (optional)
# mutagen doesn't need ffmpeg, but if you later add pydub snippet export, add ffmpeg.
# -----------------------------
# RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# -----------------------------
# Install Python dependencies
# -----------------------------
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# -----------------------------
# Copy application code
# -----------------------------
COPY app.py /app/
COPY templates /app/templates

# -----------------------------
# Environment variables
# These can be overridden with `docker run -e ...`
# -----------------------------
ENV AUDIO_DIR=/data/audio \
    CABRILLO_FILE=/data/logs/contest.log \
    RECORDING_START_UTC="2025-11-30 11:55:00" \
    CONTEST_START_UTC="2025-11-30 12:00:00" \
    PRE_SECONDS=10

# -----------------------------
# Expose Flask port
# -----------------------------
EXPOSE 8000

# -----------------------------
# Default command
# -----------------------------
CMD ["python", "app.py"]

