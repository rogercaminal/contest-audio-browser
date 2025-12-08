import os
import io
import zipfile
from datetime import datetime

from flask import (
    Flask,
    render_template,
    send_from_directory,
    request,
    send_file,
)
from mutagen.mp3 import MP3  # for MP3 duration
from pydub import AudioSegment

AUDIO_DIR = os.environ.get("AUDIO_DIR", "/data/audio")
CABRILLO_FILE = os.environ.get("CABRILLO_FILE", "/data/logs/contest.log")
EXPORT_DIR = os.environ.get("EXPORT_DIR")
RECORDING_START_UTC = os.environ.get("RECORDING_START_UTC")
CONTEST_START_UTC = os.environ.get("CONTEST_START_UTC")
PRE_SECONDS = float(os.environ.get("PRE_SECONDS", "10"))  # how many seconds before QSO to start

app = Flask(__name__)

audio_index = []  # list of {filename, start, end}
qsos = []         # list of QSO dicts with file + offset
header_lines = [] # Cabrillo header lines (everything before first QSO:)


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
    """Very simple Cabrillo QSO parser. Returns (header_lines, qso_list)."""
    qsos = []
    headers = []
    in_qso = False

    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            raw = line.rstrip("\n")
            stripped = raw.strip()

            if stripped.startswith("QSO:"):
                in_qso = True
                parts = stripped.split()
                # QSO: freq mode date time mycall rst_s exch_s hiscall rst_r exch_r ...
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
            else:
                if not in_qso:
                    headers.append(raw)

    return headers, qsos


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

        center = absolute_rec_second
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


# --- helper: build AudioSegment for [start_s, end_s] over all MP3 files ---
def build_audio_window(start_s: float, end_s: float) -> AudioSegment:
    """Return a pydub.AudioSegment for [start_s, end_s] seconds in the whole recording."""
    if not audio_index:
        raise RuntimeError("Audio index not built")

    # total duration
    total_duration = audio_index[-1]["end"]
    start_s = max(0.0, start_s)
    end_s = min(total_duration, end_s)
    if end_s <= start_s:
        raise RuntimeError("Requested audio window is empty or out of range.")

    start_ms = int(start_s * 1000)
    end_ms = int(end_s * 1000)

    combined = AudioSegment.silent(duration=0)

    for f in audio_index:
        file_start_ms = int(f["start"] * 1000)
        file_end_ms = int(f["end"] * 1000)

        overlap_start_ms = max(start_ms, file_start_ms)
        overlap_end_ms = min(end_ms, file_end_ms)
        if overlap_end_ms <= overlap_start_ms:
            continue

        local_start_ms = overlap_start_ms - file_start_ms
        local_end_ms = overlap_end_ms - file_start_ms

        path = os.path.join(AUDIO_DIR, f["filename"])
        audio = AudioSegment.from_file(path)
        part = audio[local_start_ms:local_end_ms]
        combined += part

    if len(combined) == 0:
        raise RuntimeError("No audio in requested window.")
    return combined


# --- helper: build a small Cabrillo for selected QSOs ---
def build_cabrillo_subset(selected_qsos):
    """Return Cabrillo text (str) containing header + only the selected QSO lines."""
    lines = []
    # header lines as they were in the original file
    for h in header_lines:
        lines.append(h)

    # ensure there's a START-OF-LOG header if not present (minimal safety)
    if not any(l.startswith("START-OF-LOG") for l in lines):
        lines.insert(0, "START-OF-LOG: 3.0")

    # blank line between header and QSO lines
    lines.append("")

    for q in selected_qsos:
        date_str = q["datetime"].strftime("%Y-%m-%d")
        time_str = q["datetime"].strftime("%H%M")
        freq = q["freq"]
        mode = q["mode"]
        mycall = q["mycall"]
        rst_s = q["rst_s"]
        exch_s = q["exch_s"]
        hiscall = q["hiscall"]
        rst_r = q["rst_r"]
        exch_r = q["exch_r"]

        line = (
            f"QSO: {freq:>5} {mode:>2} {date_str} {time_str} "
            f"{mycall:<13} {rst_s:>3} {exch_s:<6} "
            f"{hiscall:<13} {rst_r:>3} {exch_r:<6}"
        )
        lines.append(line)

    lines.append("END-OF-LOG:")
    return "\n".join(lines)


@app.route("/")
def index():
    call_query = (request.args.get("call") or "").strip().upper()
    time_from_query = (request.args.get("time_from") or "").strip()
    time_to_query = (request.args.get("time_to") or "").strip()

    # Parse time_from / time_to if provided
    time_from_dt = None
    time_to_dt = None
    time_fmt = "%Y-%m-%d %H:%M"  # same format we display in the table

    if time_from_query:
        try:
            time_from_dt = datetime.strptime(time_from_query, time_fmt)
        except ValueError:
            time_from_dt = None  # invalid -> ignore filter

    if time_to_query:
        try:
            time_to_dt = datetime.strptime(time_to_query, time_fmt)
        except ValueError:
            time_to_dt = None

    filtered = []
    for q in qsos:
        # Call filter (matches MY call or DX call, case-insensitive)
        if call_query:
            if call_query not in q["hiscall"].upper() and call_query not in q["mycall"].upper():
                continue

        # Time range filter
        q_dt = q["datetime"]
        if time_from_dt and q_dt < time_from_dt:
            continue
        if time_to_dt and q_dt > time_to_dt:
            continue

        filtered.append(q)

    return render_template(
        "index.html",
        qsos=filtered,
        call_query=call_query,
        time_from_query=time_from_query,
        time_to_query=time_to_query,
    )


@app.route("/audio/<path:filename>")
def audio(filename):
    return send_from_directory(AUDIO_DIR, filename)


@app.route("/download_selection", methods=["POST"])
def download_selection():
    try:
        start_idx = int(request.form.get("start_index", "0"))
        end_idx = int(request.form.get("end_index", "0"))
    except ValueError:
        return "Invalid indices", 400

    if start_idx <= 0 or end_idx <= 0 or end_idx < start_idx:
        return "Invalid range", 400

    selected = [q for q in qsos if start_idx <= q["index"] <= end_idx]
    if not selected:
        return "No QSOs in selected range", 400

    centers = [q["abs_rec_second"] for q in selected]
    start_s = min(centers) - PRE_SECONDS
    end_s = max(centers) + PRE_SECONDS

    audio_seg = build_audio_window(start_s, end_s)
    cab_text = build_cabrillo_subset(selected)

    # --- build ZIP in memory ---
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # audio
        audio_bytes_io = io.BytesIO()
        audio_seg.export(audio_bytes_io, format="mp3")
        audio_bytes_io.seek(0)
        zf.writestr("snippet.mp3", audio_bytes_io.read())
        # cabrillo
        zf.writestr("snippet.log", cab_text.encode("utf-8"))
    buf.seek(0)

    filename = f"qsos_{start_idx}_to_{end_idx}.zip"

    # --- optional: also save ZIP on server in EXPORT_DIR ---
    if EXPORT_DIR:
        try:
            os.makedirs(EXPORT_DIR, exist_ok=True)
            server_path = os.path.join(EXPORT_DIR, filename)
            with open(server_path, "wb") as f:
                f.write(buf.getbuffer())
            app.logger.info(f"Saved export to {server_path}")
        except Exception as e:
            app.logger.error(f"Error saving export to EXPORT_DIR: {e}")

    # --- send to browser as download ---
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=filename,
    )


def init_app():
    global audio_index, qsos, header_lines
    audio_index = build_audio_index()
    header_lines, qsos_raw = parse_cabrillo(CABRILLO_FILE)
    qsos = attach_audio_positions(qsos_raw, audio_index)


if __name__ == "__main__":
    init_app()
    app.run(host="0.0.0.0", port=8000, debug=True)

