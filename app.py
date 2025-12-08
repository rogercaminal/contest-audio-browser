import os
import io
import zipfile
from datetime import datetime

from flask import Flask, render_template, request, send_file, send_from_directory
from mutagen.mp3 import MP3
from pydub import AudioSegment

app = Flask(__name__)

CONTESTS_ROOT = os.environ.get("CONTESTS_ROOT", "/data/contests")
EXPORT_DIR = os.environ.get("EXPORT_DIR")
PRE_SECONDS = float(os.environ.get("PRE_SECONDS", "10"))

# Default timings (can later be per-contest)
RECORDING_START_UTC = os.environ.get("RECORDING_START_UTC")
CONTEST_START_UTC = os.environ.get("CONTEST_START_UTC")


# -------------------------------------------------------------------
# Contest session class ----------------------------------------------
# -------------------------------------------------------------------

class ContestSession:
    def __init__(self, contest_id, base_dir):
        self.id = contest_id
        self.base_dir = base_dir
        self.audio_dir = os.path.join(base_dir, "audio")
        self.log_path = os.path.join(base_dir, "logs", "contest.log")

        self.audio_index = []
        self.header_lines = []
        self.qsos = []

        self._build()

    @staticmethod
    def _parse_time_utc(s):
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")

    def _build_audio_index(self):
        files = [f for f in os.listdir(self.audio_dir) if f.lower().endswith(".mp3")]
        files.sort()
        if not files:
            raise RuntimeError(f"No MP3 files in {self.audio_dir}")

        index = []
        start = 0.0
        for name in files:
            path = os.path.join(self.audio_dir, name)
            audio = MP3(path)
            duration = float(audio.info.length)
            index.append({"filename": name, "start": start, "end": start + duration})
            start += duration

        self.audio_index = index

    def _parse_cabrillo(self):
        headers = []
        qsos = []
        in_qso = False

        with open(self.log_path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                raw = line.rstrip("\n")
                stripped = raw.strip()

                if stripped.startswith("QSO:"):
                    in_qso = True
                    parts = stripped.split()
                    if len(parts) < 11:
                        continue
                    freq, mode = parts[1], parts[2]
                    date, time = parts[3], parts[4]
                    mycall, rst_s, exch_s = parts[5], parts[6], parts[7]
                    hiscall, rst_r, exch_r = parts[8], parts[9], parts[10]
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

        self.header_lines = headers
        self.qsos = qsos

    def _attach_audio_positions(self):
        if not RECORDING_START_UTC or not CONTEST_START_UTC:
            raise RuntimeError("RECORDING_START_UTC and CONTEST_START_UTC must be set")

        rec_start = self._parse_time_utc(RECORDING_START_UTC)
        contest_start = self._parse_time_utc(CONTEST_START_UTC)

        offset = (contest_start - rec_start).total_seconds()

        for i, q in enumerate(self.qsos):
            delta = (q["datetime"] - contest_start).total_seconds()
            abs_sec = offset + delta

            center = abs_sec
            start_play = max(0.0, center - PRE_SECONDS)

            file_name = None
            file_offset = 0.0
            for f in self.audio_index:
                if start_play >= f["start"] and start_play < f["end"]:
                    file_name = f["filename"]
                    file_offset = start_play - f["start"]
                    break

            q["index"] = i + 1
            q["abs_rec_second"] = abs_sec
            q["file"] = file_name
            q["file_offset"] = round(file_offset, 3)

    def _build(self):
        self._build_audio_index()
        self._parse_cabrillo()
        self._attach_audio_positions()

    # -----------------------------------------------------------
    # Build audio snippet for [start_s, end_s]
    # -----------------------------------------------------------
    def build_audio_window(self, start_s, end_s):
        total = self.audio_index[-1]["end"]
        start_s = max(0.0, start_s)
        end_s = min(total, end_s)
        if end_s <= start_s:
            raise RuntimeError("Empty audio window")

        start_ms = int(start_s * 1000)
        end_ms = int(end_s * 1000)

        combined = AudioSegment.silent(duration=0)

        for f in self.audio_index:
            fs, fe = f["start"] * 1000, f["end"] * 1000
            overlap_start = max(start_ms, fs)
            overlap_end = min(end_ms, fe)
            if overlap_end <= overlap_start:
                continue

            local_start = overlap_start - fs
            local_end = overlap_end - fs

            path = os.path.join(self.audio_dir, f["filename"])
            audio = AudioSegment.from_file(path)
            combined += audio[int(local_start):int(local_end)]

        return combined

    # -----------------------------------------------------------
    # Cabrillo subset builder
    # -----------------------------------------------------------
    def build_cabrillo_subset(self, selected_qsos):
        lines = list(self.header_lines)
        if not any(l.startswith("START-OF-LOG") for l in lines):
            lines.insert(0, "START-OF-LOG: 3.0")
        lines.append("")

        for q in selected_qsos:
            date_str = q["datetime"].strftime("%Y-%m-%d")
            time_str = q["datetime"].strftime("%H%M")
            line = (
                f"QSO: {q['freq']:>5} {q['mode']:>2} {date_str} {time_str} "
                f"{q['mycall']:<13} {q['rst_s']:>3} {q['exch_s']:<6} "
                f"{q['hiscall']:<13} {q['rst_r']:>3} {q['exch_r']:<6}"
            )
            lines.append(line)

        lines.append("END-OF-LOG:")
        return "\n".join(lines)


# -------------------------------------------------------------------
# Discover all contests under CONTESTS_ROOT
# -------------------------------------------------------------------

contests = {}  # id -> ContestSession

def init_contests():
    for name in os.listdir(CONTESTS_ROOT):
        base = os.path.join(CONTESTS_ROOT, name)
        if not os.path.isdir(base):
            continue
        audio_dir = os.path.join(base, "audio")
        log_file = os.path.join(base, "logs", "contest.log")
        if os.path.isdir(audio_dir) and os.path.isfile(log_file):
            contests[name] = ContestSession(name, base)

init_contests()


# -------------------------------------------------------------------
# ROUTES
# -------------------------------------------------------------------

@app.route("/")
def home():
    ids = sorted(contests.keys())
    return render_template("home.html", contests=ids)


@app.route("/contest/<contest_id>")
def contest_view(contest_id):
    if contest_id not in contests:
        return "Unknown contest", 404

    sess = contests[contest_id]

    call_query = (request.args.get("call") or "").strip().upper()
    time_from_query = (request.args.get("time_from") or "").strip()
    time_to_query = (request.args.get("time_to") or "").strip()

    time_fmt = "%Y-%m-%d %H:%M"
    t_from = None
    t_to = None

    if time_from_query:
        try: t_from = datetime.strptime(time_from_query, time_fmt)
        except: t_from = None

    if time_to_query:
        try: t_to = datetime.strptime(time_to_query, time_fmt)
        except: t_to = None

    filtered = []
    for q in sess.qsos:
        if call_query and call_query not in q["mycall"].upper() and call_query not in q["hiscall"].upper():
            continue
        if t_from and q["datetime"] < t_from:
            continue
        if t_to and q["datetime"] > t_to:
            continue
        filtered.append(q)

    return render_template(
        "index.html",
        contest_id=contest_id,
        qsos=filtered,
        call_query=call_query,
        time_from_query=time_from_query,
        time_to_query=time_to_query,
    )


@app.route("/contest/<contest_id>/audio/<filename>")
def contest_audio(contest_id, filename):
    if contest_id not in contests:
        return "Unknown contest", 404
    sess = contests[contest_id]
    return send_from_directory(sess.audio_dir, filename)


@app.route("/contest/<contest_id>/download_selection", methods=["POST"])
def contest_download_selection(contest_id):
    if contest_id not in contests:
        return "Unknown contest", 404
    sess = contests[contest_id]

    try:
        start_idx = int(request.form["start_index"])
        end_idx = int(request.form["end_index"])
    except:
        return "Invalid QSO range", 400

    if start_idx <= 0 or end_idx < start_idx:
        return "Invalid range", 400

    selected = [q for q in sess.qsos if start_idx <= q["index"] <= end_idx]
    if not selected:
        return "No QSOs in range", 400

    centers = [q["abs_rec_second"] for q in selected]
    start_s = min(centers) - PRE_SECONDS
    end_s = max(centers) + PRE_SECONDS

    audio_seg = sess.build_audio_window(start_s, end_s)
    cab_text = sess.build_cabrillo_subset(selected)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        audio_bytes = io.BytesIO()
        audio_seg.export(audio_bytes, format="mp3")
        audio_bytes.seek(0)
        zf.writestr("snippet.mp3", audio_bytes.read())
        zf.writestr("snippet.log", cab_text.encode("utf-8"))
    buf.seek(0)

    fname = f"{contest_id}_qsos_{start_idx}_to_{end_idx}.zip"

    if EXPORT_DIR:
        os.makedirs(EXPORT_DIR, exist_ok=True)
        with open(os.path.join(EXPORT_DIR, fname), "wb") as f:
            f.write(buf.getbuffer())

    return send_file(buf, mimetype="application/zip", as_attachment=True, download_name=fname)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)

