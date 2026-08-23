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

@app.route('/download', methods=['GET'])
def download_media():
    url = request.args.get('url')
    service = request.args.get('service', 'all')
    mode = request.args.get('mode', 'video')
    direct = request.args.get('direct', 'false')
    
    if not url:
        return jsonify({"error": "No media URL provided"}), 400
    
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'format': 'bestaudio/best' if mode == 'audio' else 'best[ext=mp4]/best'
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            stream_url = info.get('url')
            title = info.get('title', 'FastSnap_Media').replace('"', '').replace('/', '_')
            
            # Clean TikTok direct stream extraction
            if service == 'tiktok' and mode != 'audio':
                formats = info.get('formats', [])
                for f in formats:
                    if 'watermark' not in f.get('format_note', '').lower():
                        stream_url = f.get('url')
                        break

            # Direct file delivery with Content-Disposition attachment header
            if direct == 'true':
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

            return jsonify({
                "download_url": f"/download?url={requests.utils.quote(url)}&service={service}&mode={mode}&direct=true",
                "title": title,
                "thumbnail": info.get('thumbnail')
            })
                
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)