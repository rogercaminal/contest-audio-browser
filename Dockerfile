FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# ffmpeg needed for pydub exporting MP3
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py /app/
COPY templates /app/templates

EXPOSE 8000

CMD ["python", "app.py"]

