# 📘 Contest Audio Browser

## Overview

**Contest Audio Browser** is a web application that lets you:

- Browse and search QSOs from **multiple ham radio contests**  
- Play back audio from **long contest recordings** (split MP3 files)  
- Jump to the exact moment of a QSO with **click-to-play**  
- Filter QSOs by **callsign** or **time range**  
- Select a range of QSOs and **download**:
  - an audio snippet (MP3) containing the chosen contacts  
  - a matching **Cabrillo subset** containing only those QSOs  

The app runs entirely inside **Docker**, needs no local Python install, and works in any modern browser.

---

# ✨ Features

### 🎧 Audio Playback
- Supports **multi-file MP3 recordings** per contest
- Automatically maps QSOs to their correct audio time offsets using per-contest metadata  
- Sticky audio bar so playback is always visible  
- Click any QSO row to jump to that moment in the recording

### 🔍 Search & Filtering
Search the QSO log by:
- **Callsign** (`MYCALL` or `DXCALL`)
- **Time range** using `From` and `To` UTC timestamps

### 📥 Export Snippets
Select a continuous range of QSOs and download a ZIP containing:

```text
snippet.mp3     # merged audio window for selected QSOs
snippet.log     # Cabrillo subset containing only selected QSOs
```

If `EXPORT_DIR` is configured, the server also saves a copy there.

### 📂 Multi-Contest Support
Place multiple contests under one main directory:

```text
<base-contests-directory>/
  cqwwcw2024/
    audio/
      001.mp3
      002.mp3
    logs/
      contest.log
    metadata.json
  wpxcw2025/
    audio/
    logs/
      contest.log
    metadata.json
```

Each contest is automatically discovered and available in the UI.

---

# 📁 Contest Folder Requirements

Each contest must follow **exactly** this structure:

```text
<contest_id>/
  audio/
    <recording files>.mp3
  logs/
    contest.log
  metadata.json
```

Requirements:

| Item | Description |
|------|-------------|
| `audio/` | Must contain MP3 files in chronological order (filenames sorted alphabetically = chronological order) |
| `logs/contest.log` | Must be named **exactly `contest.log`** (Cabrillo format) |
| `metadata.json` | Per-contest timing info (see below) |
| `contest_id` folder name | Used as the contest name shown in the UI |

If either `audio/`, `logs/contest.log` or `metadata.json` is missing, the contest will **not** be detected.

---

## 🧾 `metadata.json` format (per contest)

Each contest folder must contain a `metadata.json` file that describes how the audio aligns with the log.

Example:

```json
{
  "recording_start_utc": "2024-11-30 11:55:00",
  "contest_start_utc":   "2024-11-30 12:00:00",
  "pre_seconds": 10
}
```

Fields:

| Field | Type | Description |
|-------|------|-------------|
| `recording_start_utc` | string | UTC time when the audio recording actually started (`YYYY-MM-DD HH:MM[:SS]`) |
| `contest_start_utc`   | string | UTC time when the contest started (`YYYY-MM-DD HH:MM[:SS]`) |
| `pre_seconds`         | number | Optional. Number of seconds of audio **before** each QSO to include on playback/export (default from env `PRE_SECONDS`, usually 10) |

**Important:**

- Both `recording_start_utc` and `contest_start_utc` must be **UTC times** and must be consistent with the timestamps in the Cabrillo log.
- If the metadata is wrong (e.g. contest start in local time instead of UTC, or wrong recording start), clicks may jump to the very beginning or very end of the file. See Troubleshooting below.

---

# ⚙️ `.env` Configuration

Create a `.env` file at the project root (optional, used for global defaults):

```env
# Global default padding in seconds before each QSO
PRE_SECONDS=10
```

Most timing is now per-contest in `metadata.json`. The `PRE_SECONDS` env is only used as a fallback if `pre_seconds` is not defined in a given contest's `metadata.json`.

---

# 🐳 Running With Docker Compose

Ensure your project contains:

```text
docker-compose.yml
Dockerfile
requirements.txt
app.py
templates/
contests/      # your contest folders
```

## 1. Build the Docker image

```bash
docker compose build
```

## 2. Start the server

```bash
docker compose up
```

(Or detached mode:)

```bash
docker compose up -d
```

## 3. Access the web UI

Open:

```text
http://localhost:8000
```

You will see a list of all detected contests under `/data/contests`.

---

# 🐳 Docker Volume Mapping

Typical `docker-compose.yml` includes:

```yaml
volumes:
  - ./contests:/data/contests
  - ./data/exports:/data/exports
```

Meaning:

| Host path | Container path | Purpose |
|-----------|----------------|---------|
| `./contests` | `/data/contests` | All contest folders live here |
| `./data/exports` | `/data/exports` | Optional server-side ZIP export folder |

To inspect inside the container:

```bash
docker compose exec contest-audio-browser bash
ls -R /data/contests
```

---

# 🌐 Web Application Usage

## 1. Contest Selection

Homepage displays all available contests:

```text
cqwwcw2024
wpxcw2025
arrldxcw2023
```

Click a contest to open its QSO viewer.

## 2. QSO Viewer

Shows:

- QSO table (parsed from `logs/contest.log`)
- Search panel (callsign + time range)
- Sticky audio player at the top
- Selection controls
- Download button

## 3. Audio Playback

Click any QSO row:

- The app computes the corresponding position in the recording (using `metadata.json`).
- The browser audio player jumps to that time and starts playback.
- Selection is updated (used for export).

## 4. Selecting QSOs for Export

Workflow:

1. Click a QSO → selection **start**  
2. Click another QSO → selection **end** (inclusive range)  
3. Click **Download selection**

You get:

```text
<contest_id>_qsos_<start>_to_<end>.zip
```

Containing:

```text
snippet.mp3
snippet.log
```

If `EXPORT_DIR` is set, the ZIP is also saved inside the mapped host folder (e.g. `./data/exports`).

---

# 🧰 Troubleshooting

### ❌ “No contests found under CONTESTS_ROOT”

Possible causes:

- Wrong volume mapping in `docker-compose.yml`
- Contest folder missing `audio/` subfolder
- Contest folder missing `logs/contest.log`
- Contest folder missing `metadata.json`
- Log filename is not exactly `contest.log`

Check inside the container:

```bash
docker compose exec contest-audio-browser bash
ls -R /data/contests
```

You should see something like:

```text
/data/contests/cqwwcw2024/audio/*.mp3
/data/contests/cqwwcw2024/logs/contest.log
/data/contests/cqwwcw2024/metadata.json
```

---

### ❌ “No audio file mapped for this QSO”

This means the app could not find any audio segment corresponding to the computed playback time.

Most common reasons:

- `recording_start_utc` or `contest_start_utc` in `metadata.json` is **wrong**
- The recording does not actually cover the time range of the log
- The MP3 files are empty / corrupted

**Fix:**

1. Double-check `metadata.json` for that contest.
2. Make sure both times are **UTC** and match your Cabrillo times.  
   - If Cabrillo is in UTC (as it should be), `contest_start_utc` must also be in UTC.
3. Approximate:  
   - Find the time of your **first QSO** in the log.  
   - Listen to the recording and find roughly when that QSO occurs in the audio (e.g. 8 minutes after recording start).  
   - Adjust `recording_start_utc` so that the computed offset matches this.

---

### ❌ Clicking a QSO jumps near the **end** of the audio

This almost always means that the computed “absolute recording second” for that QSO is **outside** the total audio duration and gets clamped to the end.

Most common reasons:

- `contest_start_utc` is off by hours (e.g. local time instead of UTC)
- `recording_start_utc` is too late/too early compared to when the MP3 actually started
- The log covers more time than the available audio (e.g. partial recording)

**What to check:**

1. Confirm your Cabrillo times are **UTC**.
2. Confirm `metadata.json` times are **also UTC**.
3. Verify approximate durations:
   - Total recording duration (sum of MP3s)  
   - Time span between first and last QSO in the log  

If they are wildly different, many QSOs will map out of range.

---

### ❌ No audio plays at all

- Check that MP3 files exist and are readable:
  ```bash
  docker compose exec contest-audio-browser ls /data/contests/<id>/audio
  ```
- Verify ffmpeg is installed inside the container (it is, via Dockerfile).
- Confirm the browser Network tab shows HTTP 200 for `/contest/<id>/audio/<file>.mp3`.

---

### ❌ Downloaded ZIP always appears in browser Downloads folder

Browsers cannot write arbitrary filesystem paths for security reasons.

However, the backend also saves the ZIP to (if `EXPORT_DIR` is set):

```text
./data/exports/
```

You can change this host path in `docker-compose.yml`.

---

# 🙋 FAQ

### Can I store contests anywhere?

Yes — update the volume mapping in `docker-compose.yml`:

```yaml
- /absolute/path/to/my/contests:/data/contests
```

### Must the log be named `contest.log`?

**Yes** — the app expects `logs/contest.log`.  
If you need a different name, you must update `app.py` accordingly.

### Can I use WAV?

Currently the app expects MP3.  
Adding WAV support is straightforward with `pydub` (just adjust the loader and export).

### Does the app support per-contest metadata?

Yes — timing is controlled by `metadata.json` in each contest folder, so each contest is self-contained.

---

# 🤝 Contributing

Contributions are welcome!  
Ideas:

- More fields in `metadata.json` (contest name, band, mode, operator, notes)
- Waveform display in the browser
- Keyboard shortcuts for QSO navigation
- Band/mode filters in the UI
- Visual markers for QSOs on a timeline

---

# 📜 License

MIT License (recommended)
