import os
import re
import subprocess
import sys
from yt_dlp import YoutubeDL

CHANNEL_URL = "https://www.youtube.com/@FEYreal"


def get_known_urls():
    with open("urls.txt","r") as file:
        a = file.readlines()
    return set(a)

def append_url(url):
    with open("urls.txt", "a") as file:
        file.write(url)


def get_vids(root_url):
    #cookie olmadan flatlist, subscriber_only videolar görünür
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

def probe_channel(root_url):
    vids = get_vids(root_url)
    old_stuff = get_known_urls()
    new_stuff = []
    for url in vids.keys():
        if (url not in old_stuff):
            print(f"New video: {vids[url]["title"]}")
            new_stuff.append(url)
        return new_stuff

def download_video(path, video, cookie_path):
    # katil videolarinda cookie zorunlu ve sadece katil videolarini indirir
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-q", "--no-warnings", "--no-progress",
        "--no-playlist",
        "-f", "bv*+ba/b",
        "-S", "res:720,vcodec:av01,acodec:opus",
        "--merge-output-format", "webm",
        "-o", "-",
        video,
        "--cookies", cookie_path,
    ]
    result = subprocess.run(cmd,capture_output=True,timeout=18000)

    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8","replace")[-1000:]
        raise RuntimeError(f"yt-dlp indirilemedi:\n{stderr}")
    if not result.stdout:
        raise RuntimeError(f"yt-dlp boş çıktı döndü")


    append_url()
    return result.stdout



if __name__=="__main__":
    new_stuff = probe_channel(CHANNEL_URL)
    if new_stuff:
        for v in new stuff:
            download_video(PATH,v,"cookiefile")

    else: print("yeni video yok")