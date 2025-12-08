import os
import io
import json
import zipfile
from datetime import datetime

from flask import (
    Flask,
    render_template,
    request,
    send_file,
    send_from_directory,
)
from mutagen.mp3 import MP3
from pydub import AudioSegment

app = Flask(__name__)

# Root folder inside the container where contests live
# Each contest is a subfolder: /data/contests/<contest_id>
CONTESTS_ROOT = os.environ.get("CONTESTS_ROOT", "/data/contests")

# Where to save exported ZIPs server-side (optional)
EXPORT_DIR = os.environ.get("EXPORT_DIR")

# Global default padding (can be overridden per contest in metadata.json)
PRE_SECONDS_DEFAULT = float(os.environ.get("PRE_SECONDS", "10"))


# -------------------------------------------------------------------
# ContestSession: one per contest
# -------------------------------------------------------------------

class ContestSession:
    def __init__(self, contest_id: str, base_dir: str):
        self.id = contest_id
        self.base_dir = base_dir

        self.audio_dir = os.path.join(base_dir, "audio")
        self.log_path = os.path.join(base_dir, "logs", "contest.log")
        self.metadata_path = os.path.join(base_dir, "metadata.json")

        # Data containers
        self.audio_index = []   # list of {filename, start, end}
        self.header_lines = []  # Cabrillo header lines
        self.qsos = []          # list of QSO dicts

        # Per-contest timing
        self.recording_start_utc = None  # string
        self.contest_start_utc = None    # string
        self.pre_seconds = PRE_SECONDS_DEFAULT

        self._build()

    # ------------- helpers -------------

    @staticmethod
    def _parse_time_utc(s: str) -> datetime:
        """
        Accept either 'YYYY-MM-DD HH:MM:SS' or 'YYYY-MM-DD HH:MM'.
        """
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        raise ValueError(f"Invalid datetime format for '{s}', expected 'YYYY-MM-DD HH:MM[:SS]'")

    # ------------- metadata -------------

    def _load_metadata(self):
        if not os.path.isfile(self.metadata_path):
            raise RuntimeError(f"Missing metadata.json for contest {self.id}")

        with open(self.metadata_path, encoding="utf-8") as f:
            meta = json.load(f)

        try:
            self.recording_start_utc = meta["recording_start_utc"]
            self.contest_start_utc = meta["contest_start_utc"]
        except KeyError as e:
            raise RuntimeError(f"metadata.json for {self.id} missing key: {e}")

        if "pre_seconds" in meta:
            try:
                self.pre_seconds = float(meta["pre_seconds"])
            except (ValueError, TypeError):
                self.pre_seconds = PRE_SECONDS_DEFAULT

    # ------------- audio index -------------

    def _build_audio_index(self):
        files = [f for f in os.listdir(self.audio_dir) if f.lower().endswith(".mp3")]
        files.sort()
        if not files:
            raise RuntimeError(f"No MP3 files in {self.audio_dir} for contest {self.id}")

        index = []
        start = 0.0  # seconds
        for name in files:
            path = os.path.join(self.audio_dir, name)
            audio = MP3(path)
            duration = float(audio.info.length)  # seconds
            index.append({
                "filename": name,
                "start": start,
                "end": start + duration,
            })
            start += duration

        self.audio_index = index

    # ------------- Cabrillo parsing -------------

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

                    freq = parts[1]
                    mode = parts[2]
                    date = parts[3]   # YYYY-MM-DD
                    time = parts[4]   # HHMM
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

        self.header_lines = headers
        self.qsos = qsos

    # ------------- attach audio offsets -------------

    def _attach_audio_positions(self):
        """
        Compute file + offset for each QSO.
        We are tolerant: we clamp into the total audio duration so each QSO gets mapped.
        """
        rec_start = self._parse_time_utc(self.recording_start_utc)
        contest_start = self._parse_time_utc(self.contest_start_utc)

        if not self.audio_index:
            return

        total_duration = self.audio_index[-1]["end"]  # seconds

        offset_rec_vs_contest = (contest_start - rec_start).total_seconds()

        for i, q in enumerate(self.qsos):
            delta_qso_vs_contest = (q["datetime"] - contest_start).total_seconds()
            abs_rec_second = offset_rec_vs_contest + delta_qso_vs_contest

            # Where we want to center playback
            center = abs_rec_second
            # Start a bit before, then clamp into [0, total_duration)
            start_play = center - self.pre_seconds

            if total_duration <= 0:
                file_name = None
                file_offset = 0.0
            else:
                # clamp to valid range
                start_play = max(0.0, min(start_play, total_duration - 0.001))

                file_name = None
                file_offset = 0.0
                for f in self.audio_index:
                    if start_play >= f["start"] and start_play < f["end"]:
                        file_name = f["filename"]
                        file_offset = start_play - f["start"]
                        break

            q["index"] = i + 1
            q["abs_rec_second"] = abs_rec_second
            q["file"] = file_name
            q["file_offset"] = round(file_offset, 3)

    # ------------- public build -------------

    def _build(self):
        self._load_metadata()
        self._build_audio_index()
        self._parse_cabrillo()
        self._attach_audio_positions()

    # ------------- audio snippet builder -------------

    def build_audio_window(self, start_s: float, end_s: float) -> AudioSegment:
        """
        Build an AudioSegment for [start_s, end_s] seconds over the whole recording.
        """
        if not self.audio_index:
            raise RuntimeError("No audio index for contest")

        total = self.audio_index[-1]["end"]

        start_s = max(0.0, start_s)
        end_s = min(total, end_s)

        if end_s <= start_s:
            raise RuntimeError("Requested audio window is empty or out of range.")

        start_ms = int(start_s * 1000)
        end_ms = int(end_s * 1000)

        combined = AudioSegment.silent(duration=0)

        for f in self.audio_index:
            file_start_ms = int(f["start"] * 1000)
            file_end_ms = int(f["end"] * 1000)

            overlap_start = max(start_ms, file_start_ms)
            overlap_end = min(end_ms, file_end_ms)
            if overlap_end <= overlap_start:
                continue

            local_start = overlap_start - file_start_ms
            local_end = overlap_end - file_start_ms

            path = os.path.join(self.audio_dir, f["filename"])
            audio = AudioSegment.from_file(path)
            combined += audio[int(local_start):int(local_end)]

        if len(combined) == 0:
            raise RuntimeError("No audio in requested window.")
        return combined

    # ------------- Cabrillo subset builder -------------

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

contests = {}  # contest_id -> ContestSession


def init_contests():
    app.logger.info("Scanning contests in %s", CONTESTS_ROOT)
    if not os.path.isdir(CONTESTS_ROOT):
        app.logger.warning("CONTESTS_ROOT does not exist or is not a directory.")
        return

    for name in sorted(os.listdir(CONTESTS_ROOT)):
        base = os.path.join(CONTESTS_ROOT, name)
        if not os.path.isdir(base):
            continue

        audio_dir = os.path.join(base, "audio")
        log_file = os.path.join(base, "logs", "contest.log")
        meta_file = os.path.join(base, "metadata.json")

        if not os.path.isdir(audio_dir) or not os.path.isfile(log_file):
            app.logger.warning("Skipping %s: missing audio/ or logs/contest.log", name)
            continue

        if not os.path.isfile(meta_file):
            app.logger.warning("Skipping %s: missing metadata.json", name)
            continue

        try:
            contests[name] = ContestSession(name, base)
            app.logger.info("Loaded contest %s", name)
        except Exception as e:
            app.logger.error("Error loading contest %s: %s", name, e)


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
        try:
            t_from = datetime.strptime(time_from_query, time_fmt)
        except ValueError:
            t_from = None

    if time_to_query:
        try:
            t_to = datetime.strptime(time_to_query, time_fmt)
        except ValueError:
            t_to = None

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


@app.route("/contest/<contest_id>/audio/<path:filename>")
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
        start_idx = int(request.form.get("start_index", "0"))
        end_idx = int(request.form.get("end_index", "0"))
    except ValueError:
        return "Invalid indices", 400

    if start_idx <= 0 or end_idx <= 0 or end_idx < start_idx:
        return "Invalid range", 400

    selected = [q for q in sess.qsos if start_idx <= q["index"] <= end_idx]
    if not selected:
        return "No QSOs in selected range", 400

    centers = [q["abs_rec_second"] for q in selected]
    start_s = min(centers) - sess.pre_seconds
    end_s = max(centers) + sess.pre_seconds

    try:
        audio_seg = sess.build_audio_window(start_s, end_s)
    except Exception as e:
        return f"Error building audio: {e}", 500

    cab_text = sess.build_cabrillo_subset(selected)

    # Build ZIP in memory
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # audio
        audio_bytes = io.BytesIO()
        audio_seg.export(audio_bytes, format="mp3")
        audio_bytes.seek(0)
        zf.writestr("snippet.mp3", audio_bytes.read())

        # cabrillo
        zf.writestr("snippet.log", cab_text.encode("utf-8"))

    buf.seek(0)

    filename = f"{contest_id}_qsos_{start_idx}_to_{end_idx}.zip"

    # Optionally save server-side
    if EXPORT_DIR:
        try:
            os.makedirs(EXPORT_DIR, exist_ok=True)
            server_path = os.path.join(EXPORT_DIR, filename)
            with open(server_path, "wb") as f:
                f.write(buf.getbuffer())
            app.logger.info("Saved export to %s", server_path)
        except Exception as e:
            app.logger.error("Error saving export to EXPORT_DIR: %s", e)

    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=filename,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)

