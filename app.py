import os
import re
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

# Multiple active public resolver instances to bypass datacenter blocks
RESOLVER_INSTANCES = [
    "https://api.cobalt.tools",
    "https://cobalt-api.kwiatekm.tokyo",
    "https://cobalt.kwiatek.xyz",
    "https://dl.khub.win"
]

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
        },
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios', 'mweb']
            }
        }
    }
    if os.path.exists(COOKIE_FILE) and os.path.getsize(COOKIE_FILE) > 0:
        opts['cookiefile'] = COOKIE_FILE
    return opts

def get_youtube_video_id(url):
    pattern = r'(?:youtu\.be\/|youtube\.com\/(?:embed\/|v\/|watch\?v=|shorts\/|live\/|user\/\S+|feeds\/api\/videos\/|.*[?&]v=))([\w-]{11})'
    match = re.search(pattern, url)
    return match.group(1) if match else None

def get_instagram_shortcode(url):
    match = re.search(r'instagram\.com\/(?:p|reel|reels|tv)\/([A-Za-z0-9_-]+)', url)
    return match.group(1) if match else None

def resolve_external_media(url, mode='video'):
    for base in RESOLVER_INSTANCES:
        try:
            payload = {
                "url": url,
                "downloadMode": "audio" if mode == "audio" else "auto",
                "videoQuality": "720"
            }
            res = requests.post(
                f"{base}/",
                json=payload,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "User-Agent": DEFAULT_UA
                },
                timeout=6
            )
            if res.status_code == 200:
                data = res.json()
                # Direct stream URL (redirect or tunnel)
                if "url" in data:
                    return {
                        "stream_url": data["url"],
                        "thumb": data.get("thumb", ""),
                        "title": data.get("title", "")
                    }
                # Multi-item / Picker response (common for Instagram reels & carousels)
                if "picker" in data and len(data["picker"]) > 0:
                    item = data["picker"][0]
                    return {
                        "stream_url": item.get("url"),
                        "thumb": item.get("thumb", ""),
                        "title": data.get("title", "")
                    }
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

    # 1. Fast Path: YouTube via official oEmbed
    yt_id = get_youtube_video_id(url)
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

    # 2. Fast Path: Instagram (Resolves external proxy to avoid Meta datacenter bans)
    if 'instagram.com' in url:
        shortcode = get_instagram_shortcode(url) or "Reel"
        media_data = resolve_external_media(url)
        
        thumbnail = ""
        title = "Instagram Reel"
        
        if media_data:
            thumbnail = media_data.get("thumb") or ""
            title = media_data.get("title") or f"Instagram Post ({shortcode})"
            
        return jsonify({
            "title": title,
            "thumbnail": thumbnail,
            "duration": "HD",
            "url": url
        })

    # 3. Fast Path: TikTok via oEmbed
    if 'tiktok.com' in url:
        try:
            tt_oembed = f"https://www.tiktok.com/oembed?url={url}"
            resp = requests.get(tt_oembed, headers={'User-Agent': DEFAULT_UA}, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                return jsonify({
                    "title": data.get('title', 'TikTok Video'),
                    "thumbnail": data.get('thumbnail_url', ''),
                    "duration": "HD",
                    "url": url
                })
        except Exception:
            pass

    # 4. Fallback for other platforms via yt-dlp
    try:
        opts = get_base_opts()
        opts['skip_download'] = True
        
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return jsonify({"error": "Could not extract media details"}), 500
            
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

    # Step 1: Resolve via external network to avoid datacenter IP bans
    resolved = resolve_external_media(url, mode)
    if resolved and resolved.get("stream_url"):
        stream_url = resolved["stream_url"]

    # Step 2: yt-dlp fallback if external resolution didn't catch it
    if not stream_url and 'instagram.com' not in url:
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
        return jsonify({"error": "This video stream is currently restricted by the platform. Please try again shortly."}), 500

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
