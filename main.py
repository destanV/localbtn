import argparse
import json
import re
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

from yt_dlp import YoutubeDL
from yt_dlp.version import __version__ as YTDLP_VERSION

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.toml"
DOWNLOAD_TIMEOUT = 18000
PYPI_JSON_URL = "https://pypi.org/pypi/yt-dlp/json"


def load_config(path=CONFIG_PATH):
    if not path.exists():
        sys.exit(
            f"config not found: {path}\n"

        )
    try:
        with path.open("rb") as file:
            return tomllib.load(file)
    except tomllib.TOMLDecodeError as exc:
        sys.exit(f"invalid {path.name}: {exc}")
    except OSError as exc:
        sys.exit(f"could not read {path}: {exc}")


def section(cfg, name):
    value = cfg.get(name, {})
    if not isinstance(value, dict):
        sys.exit(f"config: [{name}] must be a table")
    return value


def resolve_path(value):
    path = Path(value).expanduser()
    return path if path.is_absolute() else BASE_DIR / path


def get_settings(cfg):
    channel = section(cfg, "channel")
    paths = section(cfg, "paths")
    download = section(cfg, "download")
    ytdlp = section(cfg, "ytdlp")

    channel_url = str(channel.get("url") or "").strip()
    if not channel_url:
        sys.exit("config: [channel].url is required")

    downloads = str(paths.get("downloads") or "").strip()
    if not downloads:
        sys.exit("config: [paths].downloads is required")

    try:
        list_depth = int(channel.get("list_depth", 4))
        delay = int(download.get("delay", 180))
    except (TypeError, ValueError):
        sys.exit("config: list_depth and delay must be integers")
    if list_depth < 1:
        sys.exit("config: [channel].list_depth must be >= 1")
    if delay < 0:
        sys.exit("config: [download].delay must be >= 0")

    ytdlp_args = ytdlp.get("args") or []
    if not isinstance(ytdlp_args, list) or not all(
        isinstance(arg, str) for arg in ytdlp_args
    ):
        sys.exit("config: [ytdlp].args must be an array of strings")

    return {
        "channel_url": channel_url,
        "list_depth": list_depth,
        "downloads": resolve_path(downloads),
        "ledger": resolve_path(str(paths.get("ledger") or "urls.txt")),
        "delay": delay,
        "ytdlp_args": ytdlp_args,
    }


def version_date(value):
    match = re.match(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", str(value))
    return tuple(int(part) for part in match.groups()) if match else None


def fetch_latest_ytdlp_version():
    try:
        with urllib.request.urlopen(PYPI_JSON_URL, timeout=10) as response:
            payload = json.load(response)
        return str(payload["info"]["version"])
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, TypeError):
        return None


def check_ytdlp_version():
    latest = fetch_latest_ytdlp_version()
    if latest is None:
        print(
            f"warning: could not check for a newer yt-dlp (installed {YTDLP_VERSION})",
            file=sys.stderr,
        )
        return

    installed_date = version_date(YTDLP_VERSION)
    latest_date = version_date(latest)
    if installed_date and latest_date and installed_date < latest_date:
        sys.exit(
            "yt-dlp version is old, update it to run this\n"
            f"installed: {YTDLP_VERSION}, latest: {latest}\n"
            f"update with: {sys.executable} -m pip install -U yt-dlp"
        )


def get_known_urls(urls_file):
    if not urls_file.exists():
        return set()
    with urls_file.open("r", encoding="utf-8") as file:
        return {line.strip() for line in file if line.strip()}


def append_url(url, urls_file):
    urls_file.parent.mkdir(parents=True, exist_ok=True)
    with urls_file.open("a", encoding="utf-8") as file:
        file.write(url.strip() + "\n")


def get_vids(root_url, list_depth):
    # cookie olmadan flatlist, subscriber_only videolar görünür
    opts = {
        "extract_flat": True,
        "quiet": True,
        "playlistend": list_depth,
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(root_url, download=False)

    entries = info.get("entries") or []
    # tab listesi döndürürse Videos u seç
    if entries and entries[0].get("_type") == "playlist":
        entries = entries[0].get("entries") or []

    videos = {}
    for entry in entries:
        if entry.get("availability") != "subscriber_only":
            continue
        vid = entry.get("url")
        if not vid:
            continue
        videos[vid] = {
            "title": entry.get("title"),
            "duration": entry.get("duration"),  # saniye
        }
    return videos


def probe_channel(root_url, urls_file, list_depth):
    vids = get_vids(root_url, list_depth)
    known = get_known_urls(urls_file)
    new_stuff = []
    for url, meta in vids.items():
        if url in known:
            continue
        print(f"New video: {meta.get('title')}")
        new_stuff.append(url)
    return new_stuff


def download_video(path, video, ytdlp_args):
    output = str(path / "%(title)s [%(id)s].%(ext)s")
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-q", "--no-warnings", "--no-progress", "--no-playlist",
        "-o", output,
        *ytdlp_args,
        video,
    ]
    try:
        return subprocess.run(cmd, timeout=DOWNLOAD_TIMEOUT).returncode == 0
    except subprocess.TimeoutExpired:
        print(f"error: download timed out: {video}", file=sys.stderr)
        return False
    except OSError as exc:
        print(f"error: could not run yt-dlp: {exc}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Download new members-only videos from a YouTube channel. "
            "Configuration is read from config.toml; download options belong "
            "in the [ytdlp] args array."
        )
    )
    parser.parse_args()

    settings = get_settings(load_config())
    check_ytdlp_version()

    downloads = settings["downloads"]
    downloads.mkdir(parents=True, exist_ok=True)

    new_stuff = probe_channel(
        settings["channel_url"], settings["ledger"], settings["list_depth"]
    )
    if not new_stuff:
        print("yeni video yok")
        return 0

    failed = []
    for index, video in enumerate(new_stuff):
        if index:
            time.sleep(settings["delay"])
        if download_video(downloads, video, settings["ytdlp_args"]):
            append_url(video, settings["ledger"])
            print(f"Downloaded: {video}")
        else:
            failed.append(video)
            print(f"Failed: {video}", file=sys.stderr)

    if failed:
        print(f"{len(failed)}/{len(new_stuff)} download(s) failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
