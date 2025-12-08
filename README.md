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

The app runs entirely inside **Docker**, needs no installation, and works in any browser.

---

# ✨ Features

### 🎧 Audio Playback
- Supports **multi-file MP3 recordings**
- Automatically maps QSOs to their correct audio time offsets  
- Sticky audio bar so playback is always visible  
- Click any QSO row to jump to that moment in the recording

### 🔍 Search & Filtering
Search the QSO log by:
- Callsign (`MYCALL` or `DXCALL`)
- Time range using `From` and `To` UTC timestamps

### 📥 Export Snippets
Select a continuous range of QSOs and download a ZIP containing:

```
snippet.mp3     # merged audio window for selected QSOs
snippet.log     # Cabrillo subset containing only selected QSOs
```

If `EXPORT_DIR` is configured, the server also saves a copy there.

### 📂 Multi-Contest Support
Place multiple contests under one main directory:

```
<base-contests-directory>/
  cqwwcw2024/
    audio/
      001.mp3
      002.mp3
    logs/
      contest.log
  wpxcw2025/
    audio/
    logs/
      contest.log
```

Each contest is automatically discovered and available in the UI.

---

# 📁 Contest Folder Requirements

Each contest must follow **exactly** this structure:

```
<contest_id>/
  audio/
    <recording files>.mp3
  logs/
    contest.log
```

Requirements:

| Item | Description |
|------|-------------|
| `audio/` | Must contain MP3 files in chronological order |
| `logs/contest.log` | Must be named **exactly `contest.log`** |
| `contest_id` folder name | Used as the name shown in the UI |

If the filename is not exactly `contest.log`, the contest will **not** be detected.

---

# ⚙️ `.env` Configuration

Create a `.env` file at the project root:

```env
# The recording started a few minutes before contest start
RECORDING_START_UTC=2024-11-30 11:55:00

# Actual contest start (UTC)
CONTEST_START_UTC=2024-11-30 12:00:00

# Seconds of padding before audio playback and snippet export
PRE_SECONDS=10
```

These parameters apply globally for all contests (per-contest metadata support may be added later).

---

# 🐳 Running With Docker Compose

Ensure your project contains:

```
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

```
http://localhost:8000
```

You will see a list of all detected contests under `/data/contests`.

---

# 🐳 Docker Volume Mapping

Your `docker-compose.yml` contains:

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

```
cqwwcw2024
wpxcw2025
arrldxcw2023
```

Click a contest to open the QSO viewer.

## 2. QSO Viewer
Shows:

- QSO table
- Search panel (callsign + time range)
- Sticky audio player
- Selection controls
- Download button

## 3. Audio Playback
Click any QSO:

- Audio jumps to the corresponding moment
- Playback starts immediately
- UI highlights selected rows

## 4. Selecting QSOs for Export
Workflow:

1. Click a QSO → selection start  
2. Click another QSO → selection end  
3. Click **Download selection**

You get:

```
<contest_id>_qsos_<start>_to_<end>.zip
```

Containing:

```
snippet.mp3
snippet.log
```

If `EXPORT_DIR` is set, the ZIP is also saved inside the mapped host folder.

---

# 🧰 Troubleshooting

### ❌ “No contests found under CONTESTS_ROOT”
Possible causes:

- Wrong volume mapping  
- Contest folder missing `audio/` subfolder  
- Log folder missing `logs/contest.log`  
- Log filename is wrong (must be `contest.log`)

### ❌ No audio plays
- MP3 files may not be readable by container
- Wrong audio directory structure
- Check using:
  ```bash
  docker compose exec contest-audio-browser ls /data/contests/<id>/audio
  ```

### ❌ Downloaded ZIP always appears in browser Downloads folder
Browsers cannot write arbitrary filesystem paths for security reasons.

However, the backend also saves the ZIP to:

```
./data/exports/
```

which is configurable in the compose file.

---

# 🙋 FAQ

### Can I store contests anywhere?
Yes — edit:

```yaml
- /absolute/path/to/my/data:/data/contests
```

### Must the log be named `contest.log`?
**Yes.**  
Otherwise the app will skip that contest.

### Can I use WAV?
Not yet; MP3 is the supported format. WAV support can be added easily.

### Does the app support per-contest metadata (start times, durations, categories)?
Not yet, but designed to be extendable.

---

# 🤝 Contributing

Contributions welcome!  
Ideas:

- Per-contest metadata JSON  
- Waveform display in JS  
- Keyboard shortcuts  
- Band/mode filters  
- Visual audio markers for QSOs  

---

# 📜 License

MIT License (recommended)
