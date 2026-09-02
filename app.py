import os
import re
import requests
from flask import Flask, request, jsonify, Response, render_template_string
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
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Sec-Fetch-Mode': 'navigate'
        }
    }
    if os.path.exists(COOKIE_FILE) and os.path.getsize(COOKIE_FILE) > 0:
        opts['cookiefile'] = COOKIE_FILE
    return opts

def get_youtube_video_id(url):
    pattern = r'(?:youtu\.be\/|youtube\.com\/(?:embed\/|v\/|watch\?v=|shorts\/|live\/|user\/\S+|feeds\/api\/videos\/|.*[?&]v=))([\w-]{11})'
    match = re.search(pattern, url)
    return match.group(1) if match else None

# Fallback resolver using Cobalt API when datacenter IPs are bot-blocked
def resolve_via_cobalt(url, mode='video'):
    try:
        payload = {
            'url': url,
            'downloadMode': 'audio' if mode == 'audio' else 'auto'
        }
        res = requests.post(
            'https://api.cobalt.tools/',
            json=payload,
            headers={
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'User-Agent': DEFAULT_UA
            },
            timeout=10
        )
        if res.status_code == 200:
            data = res.json()
            return data.get('url')
    except Exception:
        pass
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

    # TikTok oEmbed quick path
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
    clean_title = 'FastSnap_Media'
    
    # 1. Try yt-dlp first
    try:
        opts = get_base_opts()
        opts['format'] = 'bestaudio/best' if mode == 'audio' else 'best[ext=mp4]/best'
        
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info:
                raw_title = info.get('title', 'FastSnap_Media')
                clean_title = re.sub(r'[^a-zA-Z0-9_\-\s]', '', raw_title).strip() or 'FastSnap_Media'
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

    # 2. Resilient fallback for YouTube / TikTok blocks
    if not stream_url:
        stream_url = resolve_via_cobalt(url, mode)

    if not stream_url:
        return jsonify({"error": "Download failed. The platform blocked this datacenter request. Try again shortly."}), 500

    ext = 'mp3' if mode == 'audio' else 'mp4'
    mime = 'audio/mpeg' if mode == 'audio' else 'video/mp4'

    headers = {'User-Agent': DEFAULT_UA, 'Accept': '*/*'}
    try:
        upstream = requests.get(stream_url, headers=headers, stream=True, timeout=25)
        
        def generate_stream():
            for chunk in upstream.iter_content(chunk_size=1024 * 64):
                if chunk:
                    yield chunk

        return Response(
            generate_stream(),
            content_type=mime,
            headers={
                "Content-Disposition": f'attachment; filename="{clean_title}.{ext}"',
                "Cache-Control": "no-cache"
            }
        )
    except Exception as e:
        return jsonify({"error": f"Failed to stream file: {str(e)}"}), 500

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
