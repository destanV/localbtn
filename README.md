
## Purpose:
Achive members-only videos, don'tlose access once your membership ends.


This script watches a channel's recent uploads, skips anything already recorded
in a plain-text ledger, downloads each new members-only video using your browser
cookies, and records the event to the ledger. Recommended use: a systemd .timer


## Requirements

- Python 3.11 or newer (`tomllib`)
- `ffmpeg` on `PATH` (yt-dlp uses it for merging, remuxing, and audio extraction)
- `yt-dlp` (installed from `requirements.txt`)

## Usage

```bash
python main.py            # download new videos
python main.py --dry-run  # test
```

## The ledger

`urls.txt` is a plain list of video URLs, one per line. Successful downloads are
appended automatically. Pre-populate it (or edit it by hand) to skip videos you
already have or do not want.


## Setup (Linux)

```bash
git clone https://github.com/destanV/localbtn.git
cd localbtn
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config-example config.toml
$EDITOR config.toml
```

`config-example` is a template: fill in every value, then run.
## Example systemd timer

`~/.config/systemd/user/localbtn.service`:

```ini
[Unit]
Description=Download new members-only videos

[Service]
Type=oneshot
WorkingDirectory=/path/to/localbtn
ExecStart=/path/to/localbtn/.venv/bin/python3 -u /path/to/localbtn/main.py
StandardOutput=append:/path/to/localbtn/output.log
StandardError=append:/path/to/localbtn/err.log
```

`~/.config/systemd/user/localbtn.timer`:

```ini
[Unit]
Description=Daily localbtn run

[Timer]
OnCalendar=*-*-* 23:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

## How to enable systemd timer

```bash
systemctl --user daemon-reload
systemctl --user enable --now localbtn.timer
systemctl --user list-timers localbtn.timer
```
