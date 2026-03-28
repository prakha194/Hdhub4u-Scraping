import os
import re
import logging
from urllib.parse import urljoin, quote
from flask import Flask, request, jsonify
import cloudscraper
from bs4 import BeautifulSoup
import requests

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

# Telegram API URL
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

class HDHub4uScraper:
    def __init__(self):
        self.scraper = cloudscraper.create_scraper()
        
    def search_movies(self, query):
        try:
            search_url = f"{BASE_URL}/?s={quote(query)}"
            logger.info(f"Searching URL: {search_url}")
            
            response = self.scraper.get(search_url, timeout=20)
            logger.info(f"Response status: {response.status_code}")
            
            # Save HTML for debugging (optional - remove in production)
            with open('debug.html', 'w', encoding='utf-8') as f:
                f.write(response.text)
            logger.info("Saved HTML to debug.html")
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Try different selectors to find movies
            movies = []
            
            # Method 1: Look for article tags
            containers = soup.find_all('article')
            logger.info(f"Found {len(containers)} article tags")
            
            # Method 2: Look for divs with movie-related classes
            if not containers:
                containers = soup.find_all('div', class_=re.compile(r'movie|item|post|entry'))
                logger.info(f"Found {len(containers)} divs with movie classes")
            
            # Method 3: Look for li items
            if not containers:
                containers = soup.find_all('li', class_=re.compile(r'movie|item'))
                logger.info(f"Found {len(containers)} li items")
            
            for container in containers[:15]:
                # Try different ways to find title
                title_elem = None
                for tag in ['h3', 'h2', 'h1', 'a']:
                    title_elem = container.find(tag, class_=re.compile(r'title|name|entry-title')) or container.find(tag)
                    if title_elem:
                        break
                
                # Try different ways to find link
                link_elem = container.find('a', href=True)
                
                if title_elem and link_elem:
                    title = title_elem.text.strip()
                    link = link_elem.get('href')
                    
                    logger.info(f"Found movie: {title} - {link}")
                    
                    if link and not link.startswith('#'):
                        qualities = []
                        if '4K' in title: qualities.append('4K')
                        if '1080p' in title: qualities.append('1080p')
                        if '720p' in title: qualities.append('720p')
                        if '480p' in title: qualities.append('480p')
                        
                        year_match = re.search(r'(19|20)\d{2}', title)
                        year = year_match.group() if year_match else 'N/A'
                        
                        movies.append({
                            'title': title[:80],
                            'year': year,
                            'url': link if link.startswith('http') else urljoin(BASE_URL, link),
                            'qualities': qualities if qualities else ['Various']
                        })
            
            logger.info(f"Total movies found: {len(movies)}")
            return movies
            
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []
    
    def get_download_links(self, movie_url):
        try:
            logger.info(f"Getting links from: {movie_url}")
            response = self.scraper.get(movie_url, timeout=20)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            links = []
            
            # Find all download links
            all_links = soup.find_all('a', href=True)
            
            for link in all_links:
                href = link.get('href', '')
                text = link.text.strip().lower()
                
                # Check if it's a download link
                if any(k in href.lower() for k in ['download', 'get', 'file', '.mp4', '.mkv', 'hubcloud', 'drive.google', 'mega']):
                    quality = 'Unknown'
                    if '4k' in href.lower() or '4k' in text:
                        quality = '4K'
                    elif '1080p' in href.lower() or '1080p' in text:
                        quality = '1080p'
                    elif '720p' in href.lower() or '720p' in text:
                        quality = '720p'
                    elif '480p' in href.lower() or '480p' in text:
                        quality = '480p'
                    
                    server = 'Direct'
                    if 'hubcloud' in href.lower():
                        server = 'HubCloud'
                    elif 'drive.google' in href.lower():
                        server = 'GDrive'
                    elif 'mega' in href.lower():
                        server = 'Mega'
                    
                    if href not in [l['url'] for l in links]:
                        links.append({'quality': quality, 'server': server, 'url': href})
                        logger.info(f"Found link: {quality} - {server} - {href[:100]}")
            
            # Sort by quality
            quality_order = {'4K': 0, '1080p': 1, '720p': 2, '480p': 3, 'Unknown': 4}
            links.sort(key=lambda x: quality_order.get(x['quality'], 99))
            
            logger.info(f"Total links found: {len(links)}")
            return links
            
        except Exception as e:
            logger.error(f"Error getting links: {e}")
            return []

scraper = HDHub4uScraper()
user_sessions = {}

# Helper function to send messages
def send_message(chat_id, text, reply_markup=None, parse_mode='Markdown'):
    url = f"{TELEGRAM_API}/sendMessage"
    data = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': parse_mode,
        'disable_web_page_preview': True
    }
    if reply_markup:
        data['reply_markup'] = reply_markup
    try:
        response = requests.post(url, json=data)
        logger.info(f"Send message response: {response.status_code}")
        return response.json()
    except Exception as e:
        logger.error(f"Send message error: {e}")
        return None

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
    url = f"{TELEGRAM_API}/answerCallbackQuery"
    requests.post(url, json={'callback_query_id': callback_id})

def delete_message(chat_id, message_id):
    url = f"{TELEGRAM_API}/deleteMessage"
    requests.post(url, json={'chat_id': chat_id, 'message_id': message_id})

# Webhook handler
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        update = request.get_json()
        
        if not update:
            return jsonify({"status": "ok"}), 200
        
        logger.info(f"Received update: {update.get('message', {}).get('text', 'No text')}")
        
        # Handle callback queries (button clicks)
        if 'callback_query' in update:
            callback = update['callback_query']
            callback_id = callback['id']
            user_id = callback['from']['id']
            data = callback['data']
            message = callback['message']
            chat_id = message['chat']['id']
            message_id = message['message_id']
            
            answer_callback(callback_id)
            
            if data.startswith('movie_'):
                idx = int(data.split('_')[1])
                movie = user_sessions.get(user_id, {}).get('movies', [])[idx]
                
                edit_message(chat_id, message_id, f"📥 Getting links for *{movie['title']}*...")
                
                links = scraper.get_download_links(movie['url'])
                
                if not links:
                    edit_message(chat_id, message_id, "❌ No download links found")
                    return jsonify({"status": "ok"}), 200
                
                user_sessions[user_id]['links'] = links
                user_sessions[user_id]['movie'] = movie
                
                keyboard = {
                    'inline_keyboard': [
                        [{'text': f"📥 {link['quality']} - {link['server']}", 'callback_data': f"link_{i}"}]
                        for i, link in enumerate(links[:10])  # Limit to 10
                    ]
                }
                
                edit_message(chat_id, message_id, f"🎬 *{movie['title']}*\n\nChoose quality:", keyboard)
            
            elif data.startswith('link_'):
                idx = int(data.split('_')[1])
                movie = user_sessions.get(user_id, {}).get('movie', {})
                link = user_sessions.get(user_id, {}).get('links', [])[idx]
                
                send_message(
                    chat_id,
                    f"🎬 *{movie.get('title', 'Movie')}*\n📀 *{link['quality']}* - {link['server']}\n\n🔗 `{link['url']}`\n\n⚠️ Link auto-deletes in 20 seconds"
                )
                delete_message(chat_id, message_id)
        
        # Handle regular messages
        elif 'message' in update:
            message = update['message']
            chat_id = message['chat']['id']
            text = message.get('text', '')
            
            if text.startswith('/start'):
                send_message(chat_id, "🎬 **HDHub4u Movie Bot**\n\nSend me a **movie name** to search\n\n⚠️ Links auto-delete in 20 seconds")
            elif text.startswith('/help'):
                send_message(chat_id, "🔍 **Commands:**\n/start - Start bot\n/help - Help\n\nSimply type any movie name to search!")
            elif not text.startswith('/'):
                # Search for movies
                send_message(chat_id, f"🔍 Searching for *{text}*...")
                
                movies = scraper.search_movies(text)
                
                if not movies:
                    send_message(chat_id, f"❌ No movies found for *{text}*\n\nTry:\n• Different spelling\n• Include year (e.g., The Batman 2022)\n• Shorter title")
                    return jsonify({"status": "ok"}), 200
                
                user_sessions[chat_id] = {'movies': movies}
                
                keyboard = {
                    'inline_keyboard': [
                        [{'text': f"{movie['title'][:40]} ({movie['year']}) [{', '.join(movie['qualities'])}]", 'callback_data': f"movie_{idx}"}]
                        for idx, movie in enumerate(movies[:10])
                    ]
                }
                
                send_message(chat_id, f"✅ Found {len(movies)} movies\n\nSelect one:", keyboard)
        
        return jsonify({"status": "ok"}), 200
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"status": "error"}), 500

@app.route('/')
def index():
    return "Bot is running!", 200

@app.route('/debug')
def debug():
    """Debug endpoint to see what's happening"""
    return f"""
    Bot Status: Running
    Base URL: {BASE_URL}
    Bot Token Set: {bool(BOT_TOKEN)}
    Render Hostname: {os.getenv('RENDER_EXTERNAL_HOSTNAME', 'Not set')}
    """, 200

def setup_webhook():
    """Set webhook on startup"""
    hostname = os.getenv('RENDER_EXTERNAL_HOSTNAME')
    if not hostname:
        logger.error("RENDER_EXTERNAL_HOSTNAME not set!")
        return
    
    webhook_url = f"https://{hostname}/webhook"
    response = requests.post(f"{TELEGRAM_API}/setWebhook", json={'url': webhook_url})
    
    if response.status_code == 200:
        logger.info(f"✅ Webhook set to: {webhook_url}")
    else:
        logger.error(f"Failed to set webhook: {response.text}")

if __name__ == '__main__':
    # Set webhook
    setup_webhook()
    
    # Start Flask server
    logger.info(f"🤖 Bot starting on port {PORT}...")
    print(f"🤖 Bot running on port {PORT}")
    app.run(host='0.0.0.0', port=PORT)