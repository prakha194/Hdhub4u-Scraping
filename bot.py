import os
import re
import logging
import asyncio
from urllib.parse import urljoin, quote
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.constants import ParseMode
import cloudscraper
from bs4 import BeautifulSoup

# Configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')
BASE_URL = "https://new5.hdhub4u.fo"
DELETE_DELAY = 20

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class HDHub4uScraper:
    def __init__(self):
        self.scraper = cloudscraper.create_scraper()
        self.base_url = BASE_URL
        
    def search_movies(self, query):
        try:
            search_url = f"{self.base_url}/?s={quote(query)}"
            response = self.scraper.get(search_url, timeout=20)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            movies = []
            containers = soup.find_all('article') or soup.find_all('div', class_=re.compile(r'item|post'))
            
            for container in containers[:15]:
                title_elem = container.find('h3') or container.find('h2')
                link_elem = container.find('a', href=True)
                
                if title_elem and link_elem:
                    title = title_elem.text.strip()
                    link = link_elem.get('href')
                    
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
                            'url': link if link.startswith('http') else urljoin(self.base_url, link),
                            'qualities': qualities if qualities else ['Various']
                        })
            
            return movies
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []
    
    def get_download_links(self, movie_url):
        try:
            response = self.scraper.get(movie_url, timeout=20)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            links = []
            all_links = soup.find_all('a', href=True)
            
            for link in all_links:
                href = link.get('href', '')
                text = link.text.strip().lower()
                
                if any(k in href.lower() for k in ['download', '.mp4', '.mkv', 'hubcloud']) or \
                   any(k in text for k in ['download', '4k', '1080p', '720p', '480p']):
                    
                    quality = 'Unknown'
                    if '4k' in href.lower() or '4k' in text: quality = '4K'
                    elif '1080p' in href.lower() or '1080p' in text: quality = '1080p'
                    elif '720p' in href.lower() or '720p' in text: quality = '720p'
                    elif '480p' in href.lower() or '480p' in text: quality = '480p'
                    
                    server = 'Direct'
                    if 'hubcloud' in href.lower(): server = 'HubCloud'
                    elif 'drive' in href.lower(): server = 'GDrive'
                    
                    if href not in [l['url'] for l in links]:
                        links.append({'quality': quality, 'server': server, 'url': href})
            
            quality_order = {'4K': 0, '1080p': 1, '720p': 2, '480p': 3}
            links.sort(key=lambda x: quality_order.get(x['quality'], 99))
            return links
        except Exception as e:
            logger.error(f"Error getting links: {e}")
            return []

scraper = HDHub4uScraper()
user_sessions = {}

async def delete_message_after(context, chat_id, message_id, delay=DELETE_DELAY):
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except:
        pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 **HDHub4u Movie Bot**\n\nSend me a **movie name** to search\nUse /help for commands\n\n⚠️ Links auto-delete in 20 seconds",
        parse_mode=ParseMode.MARKDOWN
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔍 **Commands:**\n/start - Start bot\n/help - Help\n\nSimply type any movie name to search!",
        parse_mode=ParseMode.MARKDOWN
    )

async def search_movies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.startswith('/'):
        return
    
    query = update.message.text.strip()
    await update.message.chat.send_action(action="typing")
    
    msg = await update.message.reply_text(f"🔍 Searching for *{query}*...", parse_mode=ParseMode.MARKDOWN)
    await delete_message_after(context, msg.chat_id, msg.message_id, 5)
    
    movies = scraper.search_movies(query)
    
    if not movies:
        await update.message.reply_text(f"❌ No movies found for *{query}*", parse_mode=ParseMode.MARKDOWN)
        return
    
    user_id = update.effective_user.id
    user_sessions[user_id] = {'movies': movies}
    
    keyboard = []
    for idx, movie in enumerate(movies[:10]):
        qualities = ', '.join(movie['qualities'])
        keyboard.append([InlineKeyboardButton(f"{movie['title'][:40]} ({movie['year']}) [{qualities}]", callback_data=f"movie_{idx}")])
    
    await update.message.reply_text(
        f"✅ Found {len(movies)} movies\n\nSelect one:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    data = query.data
    
    if data.startswith('movie_'):
        idx = int(data.split('_')[1])
        movie = user_sessions.get(user_id, {}).get('movies', [])[idx]
        
        await query.edit_message_text(f"📥 Getting links for *{movie['title']}*...", parse_mode=ParseMode.MARKDOWN)
        
        links = scraper.get_download_links(movie['url'])
        
        if not links:
            await query.edit_message_text("❌ No download links found", parse_mode=ParseMode.MARKDOWN)
            return
        
        user_sessions[user_id]['links'] = links
        user_sessions[user_id]['movie'] = movie
        
        keyboard = []
        for i, link in enumerate(links):
            keyboard.append([InlineKeyboardButton(f"📥 {link['quality']} - {link['server']}", callback_data=f"link_{i}")])
        
        await query.edit_message_text(
            f"🎬 *{movie['title']}*\n\nChoose quality:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif data.startswith('link_'):
        idx = int(data.split('_')[1])
        movie = user_sessions.get(user_id, {}).get('movie', {})
        link = user_sessions.get(user_id, {}).get('links', [])[idx]
        
        msg = await query.message.reply_text(
            f"🎬 *{movie.get('title', 'Movie')}*\n📀 *{link['quality']}* - {link['server']}\n\n🔗 `{link['url']}`\n\n⚠️ Link auto-deletes in {DELETE_DELAY} seconds",
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True
        )
        
        await delete_message_after(context, msg.chat_id, msg.message_id, DELETE_DELAY)
        await query.delete_message()

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text("⚠️ Error occurred. Try again.")

def main():
    """Start bot with proper event loop handling"""
    try:
        # Create the Application
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_movies))
        application.add_handler(CallbackQueryHandler(button_callback))
        application.add_error_handler(error_handler)
        
        logger.info("🤖 Bot is starting...")
        print("🤖 Bot is running...")
        
        # Start the bot with polling - handles event loop internally
        application.run_polling()
        
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        print(f"Error: {e}")

if __name__ == '__main__':
    # Fix for Python 3.10+ event loop issues
    try:
        # Try to get the current event loop
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop, create one
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    main()