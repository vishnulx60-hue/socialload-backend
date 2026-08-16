from flask import Flask, request, jsonify, redirect
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app)

@app.route('/download', methods=['GET'])
def download_tool():
    url = request.args.get('url')
    service = request.args.get('service')
    mode = request.args.get('mode') 
    
    if not url: return jsonify({"error": "No URL"}), 400
    
    try:
        # Configuration
        ydl_opts = {
            'quiet': True,
            'format': 'bestaudio/best' if mode == 'mp3_direct' else 'best[ext=mp4]/best'
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            download_url = info.get('url')
            
            # TikTok NWM Logic
            if service == 'tiktok' and mode != 'mp3_direct':
                formats = info.get('formats', [])
                for f in formats:
                    if 'watermark' not in f.get('format_note', '').lower():
                        download_url = f.get('url')
                        break

            # If user clicked the MP3 button directly from the browser link
            if mode == 'mp3_direct':
                return redirect(download_url)

            return jsonify({
                "result": download_url,
                "title": info.get('title', 'Social Video'),
                "thumbnail": info.get('thumbnail')
            })
                
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(port=5000, debug=True)
