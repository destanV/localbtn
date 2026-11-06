import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from yt_dlp import YoutubeDL

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

DEFAULT_CHANNEL_URL = "https://www.youtube.com/@FEYreal"
CHANNEL_URL = (os.getenv("CHANNEL_URL") or DEFAULT_CHANNEL_URL).strip()
AUDIO_EXTS = {"mp3", "opus", "m4a", "flac", "wav", "aac", "vorbis"}
VIDEO_EXTS = {"webm", "mp4", "mkv"}
DOWNLOAD_DELAY = 180


def env_path(name, default):
    value = os.getenv(name)
    if not value:
        return default
    path = Path(value).expanduser()
    return path if path.is_absolute() else BASE_DIR / path


def get_known_urls(urls_file):
    if not urls_file.exists():
        return set()
    with urls_file.open("r", encoding="utf-8") as file:
        return {line.strip() for line in file if line.strip()}


def append_url(url, urls_file):
    urls_file.parent.mkdir(parents=True, exist_ok=True)
    with urls_file.open("a", encoding="utf-8") as file:
        file.write(url.strip() + "\n")


def get_vids(root_url):
    # cookie olmadan flatlist, subscriber_only videolar görünür
    opts = {
        "extract_flat": True,
        "quiet": True,
        "playlistend": int(os.getenv("LIST_DEPTH") or "4"),
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


def probe_channel(root_url, urls_file):
    vids = get_vids(root_url)
    known = get_known_urls(urls_file)
    new_stuff = []
    for url, meta in vids.items():
        if url in known:
            continue
        print(f"New video: {meta.get('title')}")
        new_stuff.append(url)
    return new_stuff


def parse_resolution(value):
    text = value.strip().lower()
    if text == "best":
        return "best"
    # 720, 1080p, 1080p60 -> 720, 1080, 1080
    match = re.fullmatch(r"(\d{3,4})(?:p\d*)?", text)
    if not match:
        raise argparse.ArgumentTypeError(
            f"invalid resolution {value!r}; use e.g. 720, 1080p, 1080p60 or best"
        )
    return match.group(1)


def parse_ext(value):
    ext = value.strip().lower().lstrip(".")
    if ext == "ogg":
        ext = "vorbis"
    if ext not in VIDEO_EXTS | AUDIO_EXTS:
        choices = ", ".join(sorted(VIDEO_EXTS | AUDIO_EXTS))
        raise argparse.ArgumentTypeError(
            f"unsupported extension {value!r}; choose one of: {choices}"
        )
    return ext


def download_video(path, video, cookies_from_browser, resolution, ext):
    output = str(path / "%(title)s [%(id)s].%(ext)s")
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-q", "--no-warnings", "--no-progress",
        "--no-playlist",
        "-o", output,
    ]

    if ext in AUDIO_EXTS:
        cmd += ["-f", "bestaudio/b", "-x", "--audio-format", ext, "--audio-quality", "0"]
    else:
        sort = [] if resolution == "best" else [f"res:{resolution}"]
        if ext == "webm":
            sort += ["vcodec:av01", "acodec:opus"]
        elif ext == "mp4":
            sort += ["vcodec:h264", "acodec:aac"]
        if sort:
            cmd += ["-S", ",".join(sort)]
        # bv*+ba/b forces a separate video+audio merge, so --merge-output-format
        # always applies; --remux-video guarantees the container even when the
        # `/b` fallback picks a single pre-muxed file.
        cmd += [
            "-f", "bv*+ba/b",
            "--merge-output-format", ext,
            "--remux-video", ext,
        ]

    cmd += ["--cookies-from-browser", cookies_from_browser, video]
    try:
        return subprocess.run(cmd, timeout=18000).returncode == 0
    except subprocess.TimeoutExpired:
        print(f"error: download timed out: {video}", file=sys.stderr)
        return False
    except OSError as exc:
        print(f"error: could not run yt-dlp: {exc}", file=sys.stderr)
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download new subscriber-only videos from a YouTube channel."
    )
    parser.add_argument("path", type=Path, help="directory to save downloads into")
    parser.add_argument(
        "-r", "--resolution", type=parse_resolution, default=None,
        help="video height (default 720), e.g. 1080p, 1080p60 or best",
    )
    parser.add_argument(
        "-e", "--ext", type=parse_ext, default="webm",
        help="extension: webm (default), mp4, mkv, or audio: mp3, opus, ...",
    )
    args = parser.parse_args()

    path = args.path.expanduser()
    path.mkdir(parents=True, exist_ok=True)

    cookies_from_browser = (os.getenv("COOKIES_FROM_BROWSER", "firefox:prf") or "").strip()
    if not cookies_from_browser:
        sys.exit("COOKIES_FROM_BROWSER bos; ornek: firefox:prf")

    urls_file = env_path("URLS_FILE", BASE_DIR / "urls.txt")
    resolution = args.resolution or "720"
    ext = args.ext

    if ext in AUDIO_EXTS and args.resolution is not None:
        print(
            f"warning: -e {ext} is audio-only; resolution {args.resolution} is ignored",
            file=sys.stderr,
        )

    new_stuff = probe_channel(CHANNEL_URL, urls_file)
    if not new_stuff:
        print("yeni video yok")
        sys.exit(0)

    failed = []
    for index, video in enumerate(new_stuff):
        if index:
            time.sleep(DOWNLOAD_DELAY)
        if download_video(path, video, cookies_from_browser, resolution, ext):
            append_url(video, urls_file)
            print(f"Downloaded: {video}")
        else:
            failed.append(video)
            print(f"Failed: {video}", file=sys.stderr)

    if failed:
        print(f"{len(failed)}/{len(new_stuff)} download(s) failed", file=sys.stderr)
        sys.exit(1)
