import os
import re
import logging
from urllib.parse import urljoin, quote
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup  # ← THIS WAS MISSING

# Simple logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')
BASE_URL = "https://new5.hdhub4u.fo"
DELETE_DELAY = 20
PORT = int(os.getenv('PORT', 8080))

if not BOT_TOKEN:
    logger.error("BOT_TOKEN environment variable not set!")
    exit(1)

# Flask app
app = Flask(__name__)
CORS(app)

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

class HDHub4uScraper:
    def search_movies(self, query):
        try:
            search_url = f"{BASE_URL}/search.html?q={quote(query)}"
            logger.info(f"Searching: {search_url}")
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(search_url, headers=headers, timeout=15)
            logger.info(f"Status: {response.status_code}")
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            movies = []
            
            # Find all links that could be movies
            all_links = soup.find_all('a', href=True)
            
            for link in all_links:
                href = link.get('href', '')
                title = link.text.strip()
                
                # Look for movie titles with quality indicators
                if title and len(title) > 20:
                    if any(key in title for key in ['4K', '1080p', '720p', '480p', 'BluRay', 'WEB-DL', 'HDTC']):
                        
                        # Extract quality
                        qualities = []
                        if '4K' in title: qualities.append('4K')
                        if '1080p' in title: qualities.append('1080p')
                        if '720p' in title: qualities.append('720p')
                        if '480p' in title: qualities.append('480p')
                        
                        # Extract year
                        year_match = re.search(r'(19|20)\d{2}', title)
                        year = year_match.group() if year_match else 'N/A'
                        
                        # Build URL
                        if href.startswith('/'):
                            full_url = urljoin(BASE_URL, href)
                        else:
                            full_url = href
                        
                        movies.append({
                            'title': title[:80],
                            'year': year,
                            'url': full_url,
                            'qualities': qualities if qualities else ['HD']
                        })
                        
                        logger.info(f"Found: {title[:50]}")
            
            # Remove duplicates
            seen = set()
            unique = []
            for m in movies:
                if m['url'] not in seen:
                    seen.add(m['url'])
                    unique.append(m)
            
            logger.info(f"Total: {len(unique)} movies")
            return unique[:10]
            
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []
    
    def get_download_links(self, movie_url):
        try:
            logger.info(f"Getting links from: {movie_url}")
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            response = requests.get(movie_url, headers=headers, timeout=15)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            links = []
            
            for link in soup.find_all('a', href=True):
                href = link.get('href', '')
                
                if any(k in href.lower() for k in ['download', '.mp4', '.mkv', 'hubcloud']):
                    quality = 'HD'
                    if '4k' in href.lower(): quality = '4K'
                    elif '1080p' in href.lower(): quality = '1080p'
                    elif '720p' in href.lower(): quality = '720p'
                    elif '480p' in href.lower(): quality = '480p'
                    
                    server = 'Direct'
                    if 'hubcloud' in href.lower(): server = 'HubCloud'
                    
                    if href not in [l['url'] for l in links]:
                        links.append({'quality': quality, 'server': server, 'url': href})
            
            return links[:10]
        except Exception as e:
            logger.error(f"Links error: {e}")
            return []

scraper = HDHub4uScraper()
user_sessions = {}

def send_message(chat_id, text, reply_markup=None):
    url = f"{TELEGRAM_API}/sendMessage"
    data = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'Markdown',
        'disable_web_page_preview': True
    }
    if reply_markup:
        data['reply_markup'] = reply_markup
    requests.post(url, json=data)

def edit_message(chat_id, message_id, text, reply_markup=None):
    url = f"{TELEGRAM_API}/editMessageText"
    data = {
        'chat_id': chat_id,
        'message_id': message_id,
        'text': text,
        'parse_mode': 'Markdown',
        'disable_web_page_preview': True
    }
    if reply_markup:
        data['reply_markup'] = reply_markup
    requests.post(url, json=data)

def answer_callback(callback_id):
    requests.post(f"{TELEGRAM_API}/answerCallbackQuery", json={'callback_query_id': callback_id})

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        update = request.get_json()
        if not update:
            return jsonify({"status": "ok"}), 200
        
        # Handle button clicks
        if 'callback_query' in update:
            callback = update['callback_query']
            user_id = callback['from']['id']
            data = callback['data']
            msg = callback['message']
            chat_id = msg['chat']['id']
            msg_id = msg['message_id']
            
            answer_callback(callback['id'])
            
            if data.startswith('movie_'):
                idx = int(data.split('_')[1])
                movie = user_sessions.get(user_id, {}).get('movies', [])[idx]
                
                edit_message(chat_id, msg_id, f"📥 Getting links for *{movie['title']}*...")
                
                links = scraper.get_download_links(movie['url'])
                
                if not links:
                    edit_message(chat_id, msg_id, "❌ No download links found")
                    return jsonify({"status": "ok"}), 200
                
                user_sessions[user_id]['links'] = links
                user_sessions[user_id]['movie'] = movie
                
                keyboard = {
                    'inline_keyboard': [[{'text': f"📥 {l['quality']} - {l['server']}", 'callback_data': f"link_{i}"}] for i, l in enumerate(links)]
                }
                edit_message(chat_id, msg_id, f"🎬 *{movie['title']}*\n\nChoose quality:", keyboard)
            
            elif data.startswith('link_'):
                idx = int(data.split('_')[1])
                movie = user_sessions.get(user_id, {}).get('movie', {})
                link = user_sessions.get(user_id, {}).get('links', [])[idx]
                
                send_message(chat_id, f"🎬 *{movie.get('title', 'Movie')}*\n📀 *{link['quality']}*\n\n🔗 `{link['url']}`")
        
        # Handle text messages
        elif 'message' in update:
            msg = update['message']
            chat_id = msg['chat']['id']
            text = msg.get('text', '')
            
            if text == '/start':
                send_message(chat_id, "🎬 Send me a **movie name** to search!")
            elif text and not text.startswith('/'):
                send_message(chat_id, f"🔍 Searching for *{text}*...")
                
                movies = scraper.search_movies(text)
                
                if not movies:
                    send_message(chat_id, f"❌ No movies found for *{text}*")
                    return jsonify({"status": "ok"}), 200
                
                user_sessions[chat_id] = {'movies': movies}
                
                keyboard = {
                    'inline_keyboard': [[{'text': f"{m['title'][:45]} ({m['year']})", 'callback_data': f"movie_{i}"}] for i, m in enumerate(movies[:10])]
                }
                send_message(chat_id, f"✅ Found {len(movies)} movies:", keyboard)
        
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify({"status": "error"}), 500

@app.route('/')
def index():
    return "Bot running!", 200

def setup_webhook():
    hostname = os.getenv('RENDER_EXTERNAL_HOSTNAME')
    if hostname:
        webhook_url = f"https://{hostname}/webhook"
        requests.post(f"{TELEGRAM_API}/setWebhook", json={'url': webhook_url})
        logger.info(f"Webhook set to: {webhook_url}")

if __name__ == '__main__':
    setup_webhook()
    app.run(host='0.0.0.0', port=PORT)