import html
import logging
import os
import re
from urllib.parse import urlparse

import requests
import yt_dlp
from flask import Flask, Response, jsonify, redirect, render_template_string, request
from flask_cors import CORS


logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

COOKIE_FILE = "/tmp/yt_cookies.txt"
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 15


class MediaResolutionError(Exception):
    """A user-safe explanation for an unavailable media URL."""


def configure_cookies():
    cookies = os.environ.get("YOUTUBE_COOKIES")
    if not cookies:
        return
    try:
        with open(COOKIE_FILE, "w", encoding="utf-8") as file:
            file.write(cookies)
        os.chmod(COOKIE_FILE, 0o600)
    except OSError:
        logger.exception("Could not write YouTube cookie file")


configure_cookies()


def validate_media_url(value):
    if not value:
        raise MediaResolutionError("Paste a video URL first.")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise MediaResolutionError("Please paste a complete http or https URL.")
    return value


def get_base_opts():
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": REQUEST_TIMEOUT,
        "retries": 2,
        "fragment_retries": 2,
        "http_headers": {
            "User-Agent": DEFAULT_UA,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
        },
    }
    if os.path.isfile(COOKIE_FILE) and os.path.getsize(COOKIE_FILE):
        options["cookiefile"] = COOKIE_FILE
    return options


def request_json(method, url, **kwargs):
    try:
        response = requests.request(
            method,
            url,
            headers={"User-Agent": DEFAULT_UA, "Accept-Language": "en-US,en;q=0.9"},
            timeout=REQUEST_TIMEOUT,
            **kwargs,
        )
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.info("Resolver request failed for %s: %s", url, exc)
        return None


def extract_youtube_id(url):
    match = re.search(
        r"(?:youtu\.be/|youtube\.com/(?:embed/|v/|watch\?v=|shorts/|live/|.*[?&]v=))([\w-]{11})",
        url,
    )
    return match.group(1) if match else None


def extract_instagram_shortcode(url):
    match = re.search(r"instagram\.com/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)", url)
    return match.group(1) if match else None


def resolve_instagram(url):
    shortcode = extract_instagram_shortcode(url)
    if not shortcode:
        return None
    try:
        response = requests.get(
            f"https://www.instagram.com/p/{shortcode}/embed/captioned/",
            headers={"User-Agent": DEFAULT_UA, "Referer": "https://www.instagram.com/"},
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code != 200:
            logger.info("Instagram embed returned HTTP %s", response.status_code)
            return None
        video = re.search(r'class="EmbeddedMediaVideo"[^>]*src="([^"]+)"', response.text)
        image = re.search(r'class="EmbeddedMediaImage"[^>]*src="([^"]+)"', response.text)
        caption = re.search(r'<div class="Caption"[^>]*>(.*?)</div>', response.text, re.DOTALL)
        return {
            "title": re.sub(r"<[^>]+>", "", caption.group(1)).strip()[:80]
            if caption else f"Instagram media ({shortcode})",
            "thumbnail": html.unescape(image.group(1)).replace("\\u0026", "&") if image else "",
            "stream_url": html.unescape(video.group(1)).replace("\\u0026", "&") if video else None,
        }
    except requests.RequestException as exc:
        logger.info("Instagram resolver failed: %s", exc)
        return None


def resolve_tiktok(url):
    data = request_json("POST", "https://www.tikwm.com/api/", data={"url": url})
    if not data or data.get("code") != 0 or not data.get("data"):
        return None
    media = data["data"]
    return {
        "title": media.get("title") or "TikTok video",
        "thumbnail": media.get("cover") or "",
        "video_url": media.get("play"),
        "audio_url": media.get("music"),
    }


def resolve_with_ytdlp(url, download=False, mode="video"):
    options = get_base_opts()
    options["skip_download"] = not download
    if download:
        options["format"] = (
            "bestaudio/best" if mode == "audio" else "best[ext=mp4][acodec!=none]/best[acodec!=none]/best"
        )
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            return downloader.extract_info(url, download=False)
    except Exception as exc:
        logger.warning("yt-dlp could not resolve media: %s", exc)
        return None


def media_summary(url):
    instagram = resolve_instagram(url) if "instagram.com" in url else None
    if instagram and (instagram["title"] or instagram["thumbnail"]):
        return {"title": instagram["title"], "thumbnail": instagram["thumbnail"], "duration": "", "url": url}
    tiktok = resolve_tiktok(url) if "tiktok.com" in url else None
    if tiktok:
        return {"title": tiktok["title"], "thumbnail": tiktok["thumbnail"], "duration": "", "url": url}
    info = resolve_with_ytdlp(url)
    if not info:
        raise MediaResolutionError("The platform did not provide media details. Try a public link you are allowed to download.")
    thumbnail = info.get("thumbnail") or ""
    return {
        "title": info.get("title") or "Media",
        "thumbnail": thumbnail,
        "duration": info.get("duration_string") or "",
        "url": url,
    }


def resolve_stream(url, mode):
    tiktok = resolve_tiktok(url) if "tiktok.com" in url else None
    if tiktok:
        stream = tiktok["audio_url"] if mode == "audio" else tiktok["video_url"]
        if stream:
            return stream
    instagram = resolve_instagram(url) if "instagram.com" in url else None
    if instagram and instagram["stream_url"]:
        return instagram["stream_url"]
    info = resolve_with_ytdlp(url, download=True, mode=mode)
    if not info:
        raise MediaResolutionError("The platform rejected this request. See the Render logs for the provider's response.")
    stream = info.get("url")
    if not stream:
        formats = info.get("formats") or []
        for item in reversed(formats):
            if mode == "audio" and item.get("acodec") != "none":
                stream = item.get("url")
                break
            if mode == "video" and item.get("vcodec") != "none" and item.get("acodec") != "none":
                stream = item.get("url")
                break
    if not stream:
        raise MediaResolutionError("No compatible media stream was available.")
    return stream


@app.route("/")
def home():
    try:
        with open("index.html", encoding="utf-8") as file:
            return render_template_string(file.read())
    except OSError:
        logger.exception("Could not load index.html")
        return "The site files are unavailable.", 500


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/info")
def get_media_info():
    try:
        url = validate_media_url(request.args.get("url"))
        return jsonify(media_summary(url))
    except MediaResolutionError as exc:
        return jsonify({"error": str(exc)}), 422
    except Exception:
        logger.exception("Unexpected /info failure")
        return jsonify({"error": "Could not inspect this link. Check the service logs."}), 500


@app.route("/download")
def download_media():
    try:
        url = validate_media_url(request.args.get("url"))
        mode = request.args.get("mode", "video")
        if mode not in {"video", "audio"}:
            raise MediaResolutionError("Download type must be video or audio.")
        return redirect(resolve_stream(url, mode), code=302)
    except MediaResolutionError as exc:
        return jsonify({"error": str(exc)}), 422
    except Exception:
        logger.exception("Unexpected /download failure")
        return jsonify({"error": "Could not prepare this download. Check the service logs."}), 500


@app.route("/robots.txt")
def robots():
    try:
        with open("robots.txt", encoding="utf-8") as file:
            return Response(file.read(), mimetype="text/plain")
    except OSError:
        return "Not found", 404


@app.route("/sitemap.xml")
def sitemap():
    try:
        with open("sitemap.xml", encoding="utf-8") as file:
            return Response(file.read(), mimetype="application/xml")
    except OSError:
        return "Not found", 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

