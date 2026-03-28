import os
import re
import logging
import time
from urllib.parse import urljoin, quote
from flask import Flask, request, jsonify
from flask_cors import CORS
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException
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

# Flask app with CORS
app = Flask(__name__)
CORS(app)

# Telegram API URL
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

class HDHub4uScraper:
    def __init__(self):
        self.driver = None
        
    def get_driver(self):
        """Create Chrome driver with proper options for Render"""
        if self.driver is None:
            chrome_options = Options()
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--window-size=1920,1080')
            chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
            
            try:
                self.driver = webdriver.Chrome(options=chrome_options)
                logger.info("Chrome driver created successfully")
            except Exception as e:
                logger.error(f"Failed to create Chrome driver: {e}")
                raise
        return self.driver
    
    def search_movies(self, query):
        driver = None
        try:
            driver = self.get_driver()
            search_url = f"{BASE_URL}/search.html?q={quote(query)}"
            logger.info(f"Searching URL: {search_url}")
            
            # Load the page
            driver.get(search_url)
            
            # Wait for results to load (JavaScript content)
            wait = WebDriverWait(driver, 10)
            try:
                # Wait for any movie links to appear
                wait.until(EC.presence_of_element_located((By.TAG_NAME, "a")))
                time.sleep(2)  # Extra wait for JavaScript
            except TimeoutException:
                logger.warning("Timeout waiting for page to load")
            
            # Get page source after JavaScript execution
            html = driver.page_source
            soup = BeautifulSoup(html, 'html.parser')
            
            movies = []
            
            # Find all links that look like movies
            all_links = soup.find_all('a', href=True)
            
            for link in all_links:
                href = link.get('href', '')
                title = link.text.strip()
                
                # Check if it's a movie title
                if title and len(title) > 15:
                    # Look for movie indicators
                    if any(key in title for key in ['4K', '1080p', '720p', '480p', 'BluRay', 'WEB-DL', 'HDTC', '202', 'Movie', 'Series']):
                        
                        # Extract qualities
                        qualities = []
                        if '4K' in title: qualities.append('4K')
                        if '1080p' in title: qualities.append('1080p')
                        if '720p' in title: qualities.append('720p')
                        if '480p' in title: qualities.append('480p')
                        
                        # Extract year
                        year_match = re.search(r'(19|20)\d{2}', title)
                        year = year_match.group() if year_match else 'N/A'
                        
                        # Build full URL
                        if href.startswith('/'):
                            full_url = urljoin(BASE_URL, href)
                        elif href.startswith('http'):
                            full_url = href
                        else:
                            full_url = urljoin(BASE_URL, '/' + href)
                        
                        # Skip home/trending links
                        if 'home' in full_url.lower() or 'trending' in full_url.lower():
                            continue
                        
                        movies.append({
                            'title': title[:100],
                            'year': year,
                            'url': full_url,
                            'qualities': qualities if qualities else ['HD']
                        })
                        
                        logger.info(f"Found: {title[:60]}")
            
            # Remove duplicates
            seen = set()
            unique_movies = []
            for movie in movies:
                if movie['url'] not in seen:
                    seen.add(movie['url'])
                    unique_movies.append(movie)
            
            logger.info(f"Total movies found: {len(unique_movies)}")
            return unique_movies[:15]
            
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []
        finally:
            # Don't close driver, reuse it
            pass
    
    def get_download_links(self, movie_url):
        driver = None
        try:
            driver = self.get_driver()
            logger.info(f"Getting links from: {movie_url}")
            
            driver.get(movie_url)
            time.sleep(3)  # Wait for page to load
            
            html = driver.page_source
            soup = BeautifulSoup(html, 'html.parser')
            
            links = []
            
            # Find all links
            all_links = soup.find_all('a', href=True)
            
            for link in all_links:
                href = link.get('href', '')
                text = link.text.strip().lower()
                
                # Check for download links
                if any(k in href.lower() for k in ['download', '.mp4', '.mkv', 'hubcloud', 'get', 'file']):
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
                    elif 'drive' in href.lower():
                        server = 'GDrive'
                    
                    if href not in [l['url'] for l in links]:
                        links.append({'quality': quality, 'server': server, 'url': href})
                        logger.info(f"Found link: {quality} - {server}")
            
            # Sort by quality
            quality_order = {'4K': 0, '1080p': 1, '720p': 2, '480p': 3}
            links.sort(key=lambda x: quality_order.get(x['quality'], 99))
            
            logger.info(f"Total links found: {len(links)}")
            return links
            
        except Exception as e:
            logger.error(f"Error getting links: {e}")
            return []

# Create scraper instance
scraper = HDHub4uScraper()
user_sessions = {}

# Helper functions for Telegram
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
    try:
        requests.post(url, json=data, timeout=10)
        logger.info(f"Sent message to {chat_id}")
    except Exception as e:
        logger.error(f"Send error: {e}")

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

# Webhook endpoint
@app.route('/webhook', methods=['POST', 'GET'])
def webhook():
    if request.method == 'GET':
        return jsonify({"status": "ok", "message": "Webhook is active"}), 200
    
    try:
        update = request.get_json()
        
        if not update:
            return jsonify({"status": "ok"}), 200
        
        # Handle callback queries
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
                        for i, link in enumerate(links[:10])
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
                send_message(chat_id, f"🔍 Searching for *{text}*...")
                
                movies = scraper.search_movies(text)
                
                if not movies:
                    send_message(chat_id, f"❌ No movies found for *{text}*\n\nTry:\n• Different spelling\n• Include year (e.g., Animal 2023)")
                    return jsonify({"status": "ok"}), 200
                
                user_sessions[chat_id] = {'movies': movies}
                
                keyboard = {
                    'inline_keyboard': [
                        [{'text': f"{movie['title'][:50]} ({movie['year']}) [{', '.join(movie['qualities'])}]", 'callback_data': f"movie_{idx}"}]
                        for idx, movie in enumerate(movies[:10])
                    ]
                }
                
                send_message(chat_id, f"✅ Found {len(movies)} movies\n\nSelect one:", keyboard)
        
        return jsonify({"status": "ok"}), 200
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/', methods=['GET'])
def index():
    return jsonify({
        "status": "running",
        "bot": "HDHub4u Movie Bot",
        "webhook": "/webhook"
    }), 200

def setup_webhook():
    """Set webhook automatically"""
    hostname = os.getenv('RENDER_EXTERNAL_HOSTNAME')
    if not hostname:
        logger.error("RENDER_EXTERNAL_HOSTNAME not set!")
        return False
    
    webhook_url = f"https://{hostname}/webhook"
    
    try:
        requests.post(f"{TELEGRAM_API}/deleteWebhook")
        response = requests.post(
            f"{TELEGRAM_API}/setWebhook",
            json={'url': webhook_url, 'allowed_updates': ['message', 'callback_query']}
        )
        
        if response.status_code == 200:
            logger.info(f"✅ Webhook set to: {webhook_url}")
            return True
        else:
            logger.error(f"Failed to set webhook: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Webhook setup error: {e}")
        return False

if __name__ == '__main__':
    setup_webhook()
    logger.info(f"🤖 Bot starting on port {PORT}...")
    app.run(host='0.0.0.0', port=PORT)