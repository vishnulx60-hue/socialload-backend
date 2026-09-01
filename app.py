import os
import requests
from flask import Flask, request, jsonify, Response, render_template_string
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app)

COOKIE_FILE = '/tmp/yt_cookies.txt'
if os.environ.get('YOUTUBE_COOKIES'):
    with open(COOKIE_FILE, 'w', encoding='utf-8') as f:
        f.write(os.environ.get('YOUTUBE_COOKIES'))

def get_base_opts():
    opts = {
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'noplaylist': True,
        'ignoreerrors': True
    }
    if os.path.exists(COOKIE_FILE):
        opts['cookiefile'] = COOKIE_FILE
    return opts

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

    try:
        opts = get_base_opts()
        opts['extract_flat'] = 'in_playlist'
        opts['skip_download'] = True
        
        with yt_dlp.YoutubeDL(opts) as ydl:
            # process=False extracts pure metadata without requesting stream format tables
            info = ydl.extract_info(url, download=False, process=False)
            
            title = info.get('title') or 'FastSnap Media'
            thumbnail = info.get('thumbnail') or (info.get('thumbnails', [{}])[-1].get('url') if info.get('thumbnails') else '')
            duration = info.get('duration_string') or ''

            return jsonify({
                "title": title,
                "thumbnail": thumbnail,
                "duration": duration,
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
    
    try:
        opts = get_base_opts()
        opts['format'] = 'bestaudio/best' if mode == 'audio' else 'best'
        
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = (info.get('title') or 'FastSnap_Media').replace('"', '').replace('/', '_')
            
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

            if not stream_url:
                return jsonify({"error": "Direct stream not found"}), 500

            ext = 'mp3' if mode == 'audio' else 'mp4'
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': '*/*'
            }
            
            req = requests.get(stream_url, headers=headers, stream=True, timeout=60)
            
            return Response(
                req.iter_content(chunk_size=1024 * 32),
                content_type=req.headers.get('content-type', 'application/octet-stream'),
                headers={
                    "Content-Disposition": f'attachment; filename="{title}.{ext}"'
                }
            )
    except Exception as e:
        return jsonify({"error": f"Download failed: {str(e)}"}), 500

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
