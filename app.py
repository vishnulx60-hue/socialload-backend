import io
from flask import Flask, request, jsonify, redirect, render_template_string
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app)

# Display your website interface
@app.route('/')
def home():
    try:
        with open('index.html', 'r', encoding='utf-8') as f:
            return render_template_string(f.read())
    except Exception as e:
        return f"Error loading index.html: {str(e)}", 500

# Download engine
@app.route('/download', methods=['GET'])
def download_tool():
    url = request.args.get('url')
    service = request.args.get('service')
    mode = request.args.get('mode') 
    
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'format': 'bestaudio/best' if mode == 'mp3_direct' else 'best[ext=mp4]/best'
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            download_url = info.get('url')
            
            if service == 'tiktok' and mode != 'mp3_direct':
                formats = info.get('formats', [])
                for f in formats:
                    if 'watermark' not in f.get('format_note', '').lower():
                        download_url = f.get('url')
                        break

            if mode == 'mp3_direct':
                return redirect(download_url)

            return jsonify({
                "result": download_url,
                "title": info.get('title', 'Downloaded Media'),
                "thumbnail": info.get('thumbnail')
            })
                
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
