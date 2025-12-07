# app.py
import os
from datetime import datetime

from flask import Flask, render_template, send_from_directory
from mutagen.mp3 import MP3  # for MP3 duration

AUDIO_DIR = os.environ.get("AUDIO_DIR", "/data/audio")
CABRILLO_FILE = os.environ.get("CABRILLO_FILE", "/data/logs/contest.log")
RECORDING_START_UTC = os.environ.get("RECORDING_START_UTC")
CONTEST_START_UTC = os.environ.get("CONTEST_START_UTC")
PRE_SECONDS = float(os.environ.get("PRE_SECONDS", "10"))  # how many seconds before QSO to start

app = Flask(__name__)

audio_index = []  # list of {filename, start, end}
qsos = []         # list of QSO dicts with file + offset


def parse_time_utc(s: str) -> datetime:
    # format: "YYYY-MM-DD HH:MM:SS"
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


def build_audio_index():
    """Scan AUDIO_DIR for .mp3 files and build a continuous timeline."""
    files = [f for f in os.listdir(AUDIO_DIR) if f.lower().endswith(".mp3")]
    if not files:
        raise RuntimeError(f"No MP3 files found in {AUDIO_DIR}")

    files.sort()  # assumes filename order == chronological order

    index = []
    start = 0.0
    for name in files:
        path = os.path.join(AUDIO_DIR, name)
        audio = MP3(path)
        duration = float(audio.info.length)  # seconds
        index.append({
            "filename": name,
            "start": start,
            "end": start + duration,
        })
        start += duration

    return index


def parse_cabrillo(path):
    """Very simple Cabrillo QSO parser."""
    qsos = []
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("QSO:"):
                continue
            parts = line.split()
            # QSO: freq mode date time mycall rst_s exch_s hiscall rst_r exch_r ...
            # We expect at least 11 tokens
            if len(parts) < 11:
                continue

            freq = parts[1]
            mode = parts[2]
            date = parts[3]          # YYYY-MM-DD
            time = parts[4]          # HHMM
            mycall = parts[5]
            rst_s = parts[6]
            exch_s = parts[7]
            hiscall = parts[8]
            rst_r = parts[9]
            exch_r = parts[10]

            dt = datetime.strptime(date + " " + time, "%Y-%m-%d %H%M")

            qsos.append({
                "datetime": dt,
                "freq": freq,
                "mode": mode,
                "mycall": mycall,
                "rst_s": rst_s,
                "exch_s": exch_s,
                "hiscall": hiscall,
                "rst_r": rst_r,
                "exch_r": exch_r,
            })

    return qsos


def attach_audio_positions(qsos, audio_index):
    """For each QSO, compute which file + offset (in seconds) to jump to."""
    if not RECORDING_START_UTC or not CONTEST_START_UTC:
        raise RuntimeError("RECORDING_START_UTC and CONTEST_START_UTC env vars must be set.")

    rec_start = parse_time_utc(RECORDING_START_UTC)
    contest_start = parse_time_utc(CONTEST_START_UTC)

    offset_rec_vs_contest = (contest_start - rec_start).total_seconds()

    for i, q in enumerate(qsos):
        delta_qso_vs_contest = (q["datetime"] - contest_start).total_seconds()
        absolute_rec_second = offset_rec_vs_contest + delta_qso_vs_contest

        # center of the QSO in the recording
        center = absolute_rec_second
        # where we actually start playback (a bit earlier)
        start_play = max(0.0, center - PRE_SECONDS)

        file_name = None
        file_offset = 0.0

        for f in audio_index:
            if start_play >= f["start"] and start_play < f["end"]:
                file_name = f["filename"]
                file_offset = start_play - f["start"]
                break

        q["index"] = i + 1
        q["abs_rec_second"] = absolute_rec_second
        q["file"] = file_name
        q["file_offset"] = round(file_offset, 3)

    return qsos


@app.route("/")
def index():
    return render_template("index.html", qsos=qsos)


@app.route("/audio/<path:filename>")
def audio(filename):
    # Serve raw MP3 files from AUDIO_DIR
    return send_from_directory(AUDIO_DIR, filename)


def init_app():
    global audio_index, qsos
    audio_index = build_audio_index()
    qsos_raw = parse_cabrillo(CABRILLO_FILE)
    qsos = attach_audio_positions(qsos_raw, audio_index)


if __name__ == "__main__":
    init_app()
    app.run(host="0.0.0.0", port=8000, debug=True)

