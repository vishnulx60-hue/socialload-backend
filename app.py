import os
import requests
from flask import Flask, request, jsonify, Response, render_template_string
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app)

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
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Find best direct streams
            stream_url = info.get('url')
            if not stream_url and 'formats' in info:
                # Find combined progressive or best playable video
                for f in reversed(info['formats']):
                    if f.get('vcodec') != 'none' and f.get('acodec') != 'none':
                        stream_url = f.get('url')
                        break
                if not stream_url and info['formats']:
                    stream_url = info['formats'][-1].get('url')

            return jsonify({
                "title": info.get('title', 'FastSnap_Media'),
                "thumbnail": info.get('thumbnail', ''),
                "duration": info.get('duration_string', ''),
                "preview_url": stream_url or info.get('thumbnail', ''),
                "url": url
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/download', methods=['GET'])
def download_media():
    url = request.args.get('url')
    mode = request.args.get('mode', 'video')
    
    if not url:
        return jsonify({"error": "No media URL provided"}), 400
    
    try:
        # Audio extraction or full combined video+audio extraction
        format_rule = 'bestaudio/best' if mode == 'audio' else 'best[ext=mp4][vcodec!=none][acodec!=none]/best[ext=mp4]/best'
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'format': format_rule
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            stream_url = info.get('url')
            title = info.get('title', 'FastSnap_Media').replace('"', '').replace('/', '_')
            
            ext = 'mp3' if mode == 'audio' else 'mp4'
            headers = {'User-Agent': 'Mozilla/5.0'}
            req = requests.get(stream_url, headers=headers, stream=True)
            
            return Response(
                req.iter_content(chunk_size=8192),
                content_type=req.headers.get('content-type', 'application/octet-stream'),
                headers={
                    "Content-Disposition": f'attachment; filename="{title}.{ext}"'
                }
            )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
