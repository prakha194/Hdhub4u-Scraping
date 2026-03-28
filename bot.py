import os
import re
import logging
import asyncio
from datetime import datetime
from urllib.parse import urljoin, quote
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.constants import ParseMode
from dotenv import load_dotenv
import cloudscraper
from bs4 import BeautifulSoup
import json

load_dotenv()

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
BOT_TOKEN = os.getenv('BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
BASE_URL = "https://new5.hdhub4u.fo"
DELETE_DELAY = 20  # Auto-delete after 20 seconds

class HDHub4uScraper:
    def __init__(self):
        self.scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'desktop': True
            }
        )
        self.base_url = BASE_URL
        
    def search_movies(self, query):
        """Search for movies on HDHub4u"""
        try:
            search_url = f"{self.base_url}/?s={quote(query)}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': self.base_url
            }
            
            response = self.scraper.get(search_url, headers=headers, timeout=20)
            soup = BeautifulSoup(response.text, 'lxml')
            
            movies = []
            
            # Find all movie entries - based on actual site structure
            # The site shows movies in a list format with titles and qualities
            
            # Look for article or div containers with movie info
            movie_containers = soup.find_all('article') or soup.find_all('div', class_=re.compile(r'item|post|movie'))
            
            for container in movie_containers:
                # Find title link
                title_elem = container.find('h3') or container.find('h2') or container.find('a', class_=re.compile(r'title|name'))
                link_elem = container.find('a', href=True)
                
                if title_elem and link_elem:
                    title = title_elem.text.strip()
                    link = link_elem.get('href')
                    
                    # Skip empty or navigation links
                    if not link or link.startswith('#') or len(title) < 3:
                        continue
                    
                    # Extract quality info from title
                    qualities = self._extract_qualities_from_text(title)
                    
                    # Extract year
                    year_match = re.search(r'(19|20)\d{2}', title)
                    year = year_match.group() if year_match else 'N/A'
                    
                    movies.append({
                        'title': title[:100],  # Limit length
                        'year': year,
                        'url': link if link.startswith('http') else urljoin(self.base_url, link),
                        'qualities': qualities
                    })
            
            # Remove duplicates by URL
            seen_urls = set()
            unique_movies = []
            for movie in movies:
                if movie['url'] not in seen_urls:
                    seen_urls.add(movie['url'])
                    unique_movies.append(movie)
            
            return unique_movies[:15]  # Limit to 15 results
            
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []
    
    def _extract_qualities_from_text(self, text):
        """Extract available qualities from text"""
        qualities = []
        if '4K' in text:
            qualities.append('4K')
        if '1080p' in text:
            qualities.append('1080p')
        if '720p' in text:
            qualities.append('720p')
        if '480p' in text:
            qualities.append('480p')
        return qualities if qualities else ['Unknown']
    
    def get_movie_details(self, movie_url):
        """Extract download links from movie page"""
        try:
            response = self.scraper.get(movie_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
            soup = BeautifulSoup(response.text, 'lxml')
            
            download_links = []
            
            # Find all download links - look for common patterns
            # Pattern 1: Direct download buttons/links
            all_links = soup.find_all('a', href=True)
            
            for link in all_links:
                href = link.get('href', '')
                link_text = link.text.strip().lower()
                
                # Check if it's a download link
                if any(keyword in href.lower() for keyword in ['download', 'get', 'file', '.mp4', '.mkv', 'hubcloud']) or \
                   any(keyword in link_text for keyword in ['download', '4k', '1080p', '720p', '480p', 'hd', 'cam']):
                    
                    # Determine quality
                    quality = 'Unknown'
                    if '4k' in href.lower() or '4k' in link_text:
                        quality = '4K'
                    elif '1080p' in href.lower() or '1080p' in link_text:
                        quality = '1080p'
                    elif '720p' in href.lower() or '720p' in link_text:
                        quality = '720p'
                    elif '480p' in href.lower() or '480p' in link_text:
                        quality = '480p'
                    elif 'hd' in href.lower() or 'hd' in link_text:
                        quality = 'HD'
                    
                    # Determine server/source
                    server = 'Direct'
                    if 'hubcloud' in href.lower():
                        server = 'HubCloud'
                    elif 'drive' in href.lower() or 'google' in href.lower():
                        server = 'GDrive'
                    elif 'mega' in href.lower():
                        server = 'Mega'
                    
                    download_links.append({
                        'quality': quality,
                        'server': server,
                        'url': href,
                        'text': link_text[:50]
                    })
            
            # Remove duplicates (same URL)
            seen_urls = set()
            unique_links = []
            for link in download_links:
                if link['url'] not in seen_urls:
                    seen_urls.add(link['url'])
                    unique_links.append(link)
            
            # Sort by quality (4K first)
            quality_order = {'4K': 0, '1080p': 1, '720p': 2, '480p': 3, 'HD': 4, 'Unknown': 5}
            unique_links.sort(key=lambda x: quality_order.get(x['quality'], 99))
            
            return unique_links
            
        except Exception as e:
            logger.error(f"Error getting download links: {e}")
            return []
    
    def get_trending_movies(self):
        """Get trending/featured movies from homepage"""
        try:
            response = self.scraper.get(self.base_url, timeout=15)
            soup = BeautifulSoup(response.text, 'lxml')
            
            movies = []
            # Find featured movies on homepage
            movie_elements = soup.find_all('article') or soup.find_all('div', class_=re.compile(r'item|post'))
            
            for elem in movie_elements[:10]:
                title_elem = elem.find('h3') or elem.find('h2')
                link_elem = elem.find('a', href=True)
                
                if title_elem and link_elem:
                    title = title_elem.text.strip()
                    link = link_elem.get('href')
                    if link and not link.startswith('#'):
                        movies.append({
                            'title': title[:80],
                            'url': link if link.startswith('http') else urljoin(self.base_url, link)
                        })
            
            return movies[:10]
        except Exception as e:
            logger.error(f"Error getting trending: {e}")
            return []

# Initialize scraper
scraper = HDHub4uScraper()

# Store user sessions
user_sessions = {}

async def delete_message_after_delay(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, delay: int = DELETE_DELAY):
    """Delete a message after specified delay"""
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logger.error(f"Failed to delete message: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler"""
    msg = await update.message.reply_text(
        "🎬 **Welcome to HDHub4u Movie Bot!**\n\n"
        "I can help you find and get download links from HDHub4u.\n\n"
        "🔍 **How to use:**\n"
        "• Send me a **movie name** to search\n"
        "• Use **/trending** to see popular movies\n"
        "• Select quality and get download link\n\n"
        "⚠️ Links auto-delete in 20 seconds for privacy\n"
        "⚡ Fast and easy! Try it now!",
        parse_mode=ParseMode.MARKDOWN
    )
    # Auto-delete start message after 30 seconds
    context.application.create_task(delete_message_after_delay(context, msg.chat_id, msg.message_id, 30))

async def trending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show trending movies"""
    await update.message.chat.send_action(action="typing")
    
    msg = await update.message.reply_text("🔥 Fetching trending movies...")
    context.application.create_task(delete_message_after_delay(context, msg.chat_id, msg.message_id, 10))
    
    movies = scraper.get_trending_movies()
    
    if not movies:
        await update.message.reply_text("❌ Could not fetch trending movies. Try searching instead!")
        return
    
    # Store in user session
    user_id = update.effective_user.id
    user_sessions[user_id] = {'trending': movies}
    
    keyboard = []
    for idx, movie in enumerate(movies):
        keyboard.append([InlineKeyboardButton(f"🎬 {movie['title'][:50]}", callback_data=f"trend_{idx}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"🔥 **Trending Movies**\n\nFound {len(movies)} popular movies. Select one to get download links:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def search_movies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle movie search"""
    query = update.message.text.strip()
    
    # Ignore commands
    if query.startswith('/'):
        return
    
    await update.message.chat.send_action(action="typing")
    
    # Send searching message
    searching_msg = await update.message.reply_text(f"🔍 Searching for *{query}*...", parse_mode=ParseMode.MARKDOWN)
    context.application.create_task(delete_message_after_delay(context, searching_msg.chat_id, searching_msg.message_id, 5))
    
    # Search
    movies = scraper.search_movies(query)
    
    if not movies:
        await update.message.reply_text(
            f"❌ No movies found for *{query}*\n\nTry:\n• Different spelling\n• Add year (e.g., The Batman 2022)\n• Shorter title",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Store search results
    user_id = update.effective_user.id
    user_sessions[user_id] = {'search': movies, 'query': query}
    
    # Create keyboard with results
    keyboard = []
    for idx, movie in enumerate(movies[:12]):
        qualities = ', '.join(movie['qualities']) if movie['qualities'] else 'Various'
        button_text = f"🎬 {movie['title'][:45]} ({movie['year']}) [{qualities}]"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"movie_{idx}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"✅ Found *{len(movies)}* movies for *{query}*\n\nSelect a movie to get download links:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button clicks"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    data = query.data
    
    if data.startswith('movie_'):
        # Get selected movie from search
        idx = int(data.split('_')[1])
        movies = user_sessions.get(user_id, {}).get('search', [])
        
        if idx >= len(movies):
            await query.edit_message_text("❌ Movie not found. Please search again.")
            return
        
        movie = movies[idx]
        
        # Show loading
        await query.edit_message_text(
            f"📥 Fetching download links for *{movie['title']}*...\n\nPlease wait ⏳",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Get download links
        download_links = scraper.get_movie_details(movie['url'])
        
        if not download_links:
            await query.edit_message_text(
                f"❌ No download links found for *{movie['title']}*\n\nPossible reasons:\n• Links expired\n• Server down\n• Try another movie",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # Store links
        user_sessions[user_id]['current_movie'] = movie
        user_sessions[user_id]['download_links'] = download_links
        
        # Create quality selection keyboard
        keyboard = []
        for link in download_links:
            button_text = f"📥 {link['quality']} - {link['server']}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"link_{download_links.index(link)}")])
        
        keyboard.append([InlineKeyboardButton("🔙 New Search", callback_data="new_search")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"🎬 *{movie['title']}* ({movie['year']})\n\n✅ Found *{len(download_links)}* download options:\n\nSelect quality to get link:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    elif data.startswith('trend_'):
        # Handle trending selection
        idx = int(data.split('_')[1])
        movies = user_sessions.get(user_id, {}).get('trending', [])
        
        if idx >= len(movies):
            await query.edit_message_text("❌ Movie not found.")
            return
        
        movie = movies[idx]
        
        await query.edit_message_text(
            f"📥 Fetching download links for *{movie['title']}*...",
            parse_mode=ParseMode.MARKDOWN
        )
        
        download_links = scraper.get_movie_details(movie['url'])
        
        if not download_links:
            await query.edit_message_text(f"❌ No links found for *{movie['title']}*", parse_mode=ParseMode.MARKDOWN)
            return
        
        user_sessions[user_id]['current_movie'] = movie
        user_sessions[user_id]['download_links'] = download_links
        
        keyboard = []
        for link in download_links:
            keyboard.append([InlineKeyboardButton(f"📥 {link['quality']} - {link['server']}", callback_data=f"link_{download_links.index(link)}")])
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_to_trending")])
        
        await query.edit_message_text(
            f"🎬 *{movie['title']}*\n\nSelect quality:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif data.startswith('link_'):
        # Send download link
        idx = int(data.split('_')[1])
        movie = user_sessions.get(user_id, {}).get('current_movie', {})
        download_links = user_sessions.get(user_id, {}).get('download_links', [])
        
        if idx >= len(download_links):
            await query.edit_message_text("❌ Link not found.")
            return
        
        link = download_links[idx]
        
        # Send the download link with auto-delete
        message_text = f"""
🎬 *{movie.get('title', 'Movie')}*

📀 *Quality:* {link['quality']}
🌐 *Server:* {link['server']}

🔗 **Download Link:**
`{link['url']}`

⚠️ *Note:* This link will auto-delete in {DELETE_DELAY} seconds
💡 *Tip:* Copy link quickly or use adblocker
        """
        
        # Send link message
        link_msg = await query.message.reply_text(
            message_text,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True
        )
        
        # Auto-delete after DELETE_DELAY seconds
        context.application.create_task(
            delete_message_after_delay(context, link_msg.chat_id, link_msg.message_id, DELETE_DELAY)
        )
        
        # Also delete the original selection message after sending link
        await query.delete_message()
        
        # Send confirmation
        confirm_msg = await query.message.reply_text(
            f"✅ Link sent! It will disappear in {DELETE_DELAY} seconds.\nUse /start to search again.",
            parse_mode=ParseMode.MARKDOWN
        )
        context.application.create_task(delete_message_after_delay(context, confirm_msg.chat_id, confirm_msg.message_id, 10))
    
    elif data == "new_search":
        # Clear session and prompt new search
        user_sessions[user_id] = {}
        await query.edit_message_text(
            "🔍 Send me a **movie name** to search!\n\nType /start for help.",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif data == "back_to_trending":
        # Go back to trending list
        movies = user_sessions.get(user_id, {}).get('trending', [])
        keyboard = []
        for idx, movie in enumerate(movies):
            keyboard.append([InlineKeyboardButton(f"🎬 {movie['title'][:50]}", callback_data=f"trend_{idx}")])
        
        await query.edit_message_text(
            "🔥 **Trending Movies**\n\nSelect a movie:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command"""
    help_text = """
📖 *HDHub4u Bot Help*

🔍 *Commands:*
/start - Start the bot
/trending - Show trending movies
/help - Show this help

🎬 *How to Search:*
Simply type any movie name and I'll search HDHub4u for you!

📥 *Getting Links:*
1. Search for a movie
2. Select from results
3. Choose quality
4. Get download link (auto-deletes in 20 seconds)

⚠️ *Important:*
• Links auto-delete for privacy
• Only works with HDHub4u content
• Report broken links to @admin

⚡ *Tips:*
• Use specific movie names
• Include year for better results
• Try different qualities if one doesn't work
    """
    msg = await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
    context.application.create_task(delete_message_after_delay(context, msg.chat_id, msg.message_id, 45))

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Update {update} caused error {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "⚠️ An error occurred. Please try again or use /start"
        )

def main():
    """Start the bot"""
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("trending", trending))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_movies))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_error_handler(error_handler)
    
    # Start bot
    print("🤖 HDHub4u Bot is running...")
    print(f"Base URL: {BASE_URL}")
    print(f"Auto-delete delay: {DELETE_DELAY} seconds")
    application.run_polling()

if __name__ == '__main__':
    main()
