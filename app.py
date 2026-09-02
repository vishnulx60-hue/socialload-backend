import os
import re
import html
import requests
from flask import Flask, request, jsonify, redirect, Response, render_template_string
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app)

COOKIE_FILE = '/tmp/yt_cookies.txt'
if os.environ.get('YOUTUBE_COOKIES'):
    try:
        with open(COOKIE_FILE, 'w', encoding='utf-8') as f:
            f.write(os.environ.get('YOUTUBE_COOKIES'))
    except Exception:
        pass

DEFAULT_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36'

def get_base_opts():
    opts = {
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'noplaylist': True,
        'http_headers': {
            'User-Agent': DEFAULT_UA,
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9'
        }
    }
    if os.path.exists(COOKIE_FILE) and os.path.getsize(COOKIE_FILE) > 0:
        opts['cookiefile'] = COOKIE_FILE
    return opts

def extract_youtube_id(url):
    pattern = r'(?:youtu\.be\/|youtube\.com\/(?:embed\/|v\/|watch\?v=|shorts\/|live\/|user\/\S+|feeds\/api\/videos\/|.*[?&]v=))([\w-]{11})'
    match = re.search(pattern, url)
    return match.group(1) if match else None

def extract_instagram_shortcode(url):
    match = re.search(r'instagram\.com\/(?:p|reel|reels|tv)\/([A-Za-z0-9_-]+)', url)
    return match.group(1) if match else None

# 1. Instagram Embed Resolver (bypasses Meta datacenter restrictions)
def resolve_instagram(url):
    shortcode = extract_instagram_shortcode(url)
    if not shortcode:
        return None
    try:
        embed_url = f"https://www.instagram.com/p/{shortcode}/embed/captioned/"
        headers = {
            'User-Agent': DEFAULT_UA,
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.instagram.com/'
        }
        res = requests.get(embed_url, headers=headers, timeout=6)
        if res.status_code == 200:
            content = res.text
            
            # Extract video URL
            video_url = None
            v_match = re.search(r'class="EmbeddedMediaVideo"[^>]*src="([^"]+)"', content)
            if not v_match:
                v_match = re.search(r'"video_url":"([^"]+)"', content)
            if v_match:
                video_url = html.unescape(v_match.group(1)).replace('\\u0026', '&')

            # Extract thumbnail
            thumb_url = None
            t_match = re.search(r'class="EmbeddedMediaImage"[^>]*src="([^"]+)"', content)
            if not t_match:
                t_match = re.search(r'"display_url":"([^"]+)"', content)
            if t_match:
                thumb_url = html.unescape(t_match.group(1)).replace('\\u0026', '&')

            # Extract caption/title
            c_match = re.search(r'<div class="Caption"[^>]*>(.*?)<\/div>', content, re.DOTALL)
            title = re.sub(r'<[^>]+>', '', c_match.group(1)).strip() if c_match else f"Instagram Reel ({shortcode})"

            return {
                "title": title[:80] or f"Instagram Reel ({shortcode})",
                "thumbnail": thumb_url or "",
                "stream_url": video_url
            }
    except Exception:
        pass
    return None

# 2. TikTok Resolver via TikWM API (high speed, no watermark, datacenter-proof)
def resolve_tiktok(url):
    try:
        res = requests.post("https://www.tikwm.com/api/", data={"url": url}, headers={"User-Agent": DEFAULT_UA}, timeout=7)
        if res.status_code == 200:
            data = res.json()
            if data.get("code") == 0 and "data" in data:
                d = data["data"]
                return {
                    "title": d.get("title") or "TikTok Video",
                    "thumbnail": d.get("cover") or "",
                    "video_url": d.get("play"),
                    "audio_url": d.get("music")
                }
    except Exception:
        pass
    return None

# 3. YouTube Resolver via Piped / Invidious stream instances (bypasses bot wall)
def resolve_youtube(yt_id, mode='video'):
    piped_instances = [
        "https://pipedapi.kavin.rocks",
        "https://api.piped.privacydev.net",
        "https://piped-api.lunar.icu"
    ]
    for base in piped_instances:
        try:
            res = requests.get(f"{base}/streams/{yt_id}", headers={"User-Agent": DEFAULT_UA}, timeout=5)
            if res.status_code == 200:
                data = res.json()
                if mode == 'audio' and data.get("audioStreams"):
                    return data["audioStreams"][0].get("url")
                if data.get("videoStreams"):
                    for s in data["videoStreams"]:
                        if s.get("format") == "mp4" and not s.get("videoOnly"):
                            return s.get("url")
                    return data["videoStreams"][0].get("url")
        except Exception:
            continue
    return None

@app.route('/')
def home():
    try:
        with open('index.html', 'r', encoding='utf-8') as f:
            return render_template_string(f.read())
    except Exception as e:
        return f"Error loading index.html: {str(e)}", 500

@app.route('/info', methods=['GET'])
def get_media_info():
    url = request.args.get('url')
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    # 1. Instagram
    if 'instagram.com' in url:
        data = resolve_instagram(url)
        if data and (data.get("thumbnail") or data.get("title")):
            return jsonify({
                "title": data["title"],
                "thumbnail": data["thumbnail"],
                "duration": "HD",
                "url": url
            })

    # 2. TikTok
    if 'tiktok.com' in url:
        data = resolve_tiktok(url)
        if data:
            return jsonify({
                "title": data["title"],
                "thumbnail": data["thumbnail"],
                "duration": "HD",
                "url": url
            })

    # 3. YouTube via oEmbed
    yt_id = extract_youtube_id(url)
    if yt_id:
        try:
            oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={yt_id}&format=json"
            resp = requests.get(oembed_url, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                return jsonify({
                    "title": data.get('title', 'YouTube Video'),
                    "thumbnail": f"https://img.youtube.com/vi/{yt_id}/hqdefault.jpg",
                    "duration": "HD",
                    "url": url
                })
        except Exception:
            pass

    # 4. Standard yt-dlp fallback
    try:
        opts = get_base_opts()
        opts['skip_download'] = True
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return jsonify({"error": "Could not extract media info"}), 500
            
            title = info.get('title') or 'FastSnap Media'
            thumbnail = info.get('thumbnail')
            if not thumbnail and info.get('thumbnails'):
                thumbnail = info['thumbnails'][-1].get('url')

            return jsonify({
                "title": title,
                "thumbnail": thumbnail or '',
                "duration": info.get('duration_string') or '',
                "url": url
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/download', methods=['GET'])
def download_media():
    url = request.args.get('url')
    mode = request.args.get('mode', 'video')
    
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    stream_url = None

    # Step 1: TikTok Resolution
    if 'tiktok.com' in url:
        tt_data = resolve_tiktok(url)
        if tt_data:
            stream_url = tt_data.get("audio_url") if mode == 'audio' else tt_data.get("video_url")

    # Step 2: Instagram Resolution
    if not stream_url and 'instagram.com' in url:
        ig_data = resolve_instagram(url)
        if ig_data and ig_data.get("stream_url"):
            stream_url = ig_data["stream_url"]

    # Step 3: YouTube Resolution via Piped
    yt_id = extract_youtube_id(url)
    if not stream_url and yt_id:
        stream_url = resolve_youtube(yt_id, mode)

    # Step 4: yt-dlp fallback
    if not stream_url:
        try:
            opts = get_base_opts()
            opts['format'] = 'bestaudio/best' if mode == 'audio' else 'best[ext=mp4][acodec!=none]/best[acodec!=none]/best'
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info:
                    stream_url = info.get('url')
                    if not stream_url and 'formats' in info:
                        for f in reversed(info['formats']):
                            if mode == 'audio' and f.get('acodec') != 'none':
                                stream_url = f.get('url')
                                break
                            elif f.get('vcodec') != 'none' and f.get('acodec') != 'none':
                                stream_url = f.get('url')
                                break
                        if not stream_url and info['formats']:
                            stream_url = info['formats'][-1].get('url')
        except Exception:
            pass

    if not stream_url:
        return jsonify({"error": "Media stream is temporarily unavailable. Please verify the link or try another."}), 500

    return redirect(stream_url, code=302)

@app.route('/robots.txt')
def robots():
    try:
        with open('robots.txt', 'r', encoding='utf-8') as f:
            return Response(f.read(), mimetype='text/plain')
    except Exception as e:
        return f"Error: {str(e)}", 404

@app.route('/sitemap.xml')
def sitemap():
    try:
        with open('sitemap.xml', 'r', encoding='utf-8') as f:
            return Response(f.read(), mimetype='application/xml')
    except Exception as e:
        return f"Error: {str(e)}", 404

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
