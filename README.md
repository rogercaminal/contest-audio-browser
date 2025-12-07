# Contest Audio Browser

This project maps a Cabrillo contest log to a folder of MP3 audio files and provides a web UI to click QSOs and jump directly to their audio.

## Features
- Reads a folder of MP3 recordings and builds a continuous timeline
- Parses a Cabrillo log
- Computes timestamp → audio offset
- Web interface with clickable QSO table
- Plays the correct spot in the browser
- Fully Dockerized

## Usage

### Build
```bash
docker build -t contest-audio-browser .

