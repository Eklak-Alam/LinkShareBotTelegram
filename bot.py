import os
import telebot
import threading
import time
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_IDS = [int(id.strip()) for id in os.getenv("ADMIN_IDS").split(",")] if os.getenv("ADMIN_IDS") else []
DEFAULT_LINK = os.getenv("DEFAULT_LINK")
MESSAGE_INTERVAL = int(os.getenv("MESSAGE_INTERVAL", 24)) * 3600  # Convert to seconds

# Initialize bot
bot = telebot.TeleBot(BOT_TOKEN)

# In-memory storage
ACTIVE_GROUPS = set()  # Stores active group IDs
GROUP_LINKS = {}       # {group_id: custom_link}
GROUP_INFO = {}        # {group_id: {"title": group_name, "link": current_link}}
LAST_MESSAGE_TIMES = {}

# Helper functions
def is_admin(user_id):
    return user_id in ADMIN_IDS

def is_group_admin(message):
    if message.chat.type not in ['group', 'supergroup']:
        return False
    try:
        admins = bot.get_chat_administrators(message.chat.id)
        return any(admin.user.id == message.from_user.id for admin in admins)
    except Exception as e:
        logger.error(f"Error checking admin status: {e}")
        return False

def get_next_post_time(chat_id):
    if chat_id not in LAST_MESSAGE_TIMES:
        return "soon (not posted yet)"
    next_time = LAST_MESSAGE_TIMES[chat_id] + timedelta(seconds=MESSAGE_INTERVAL)
    return next_time.strftime("%Y-%m-%d %H:%M:%S")

def send_welcome_and_link(chat_id):
    try:
        chat = bot.get_chat(chat_id)
        GROUP_INFO[chat_id] = {
            "title": chat.title,
            "link": GROUP_LINKS.get(chat_id, DEFAULT_LINK)
        }
        
        welcome_msg = "🤖 *Link Sharing Bot Activated!* \n\n" \
                     "I'll automatically share links in this group.\n" \
                     f"Current link: {GROUP_INFO[chat_id]['link']}\n\n" \
                     "Admins can use /setlink to change the URL"
        
        bot.send_message(chat_id, welcome_msg, parse_mode="Markdown")
        
        # Send first link immediately
        send_link_to_group(chat_id)
    except Exception as e:
        logger.error(f"Error sending welcome to {chat_id}: {e}")

def send_link_to_group(chat_id):
    try:
        current_link = GROUP_LINKS.get(chat_id, DEFAULT_LINK)
        message = f"📢 *Group Link*\n\n🔗 {current_link}\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        bot.send_message(chat_id, message, parse_mode="Markdown")
        LAST_MESSAGE_TIMES[chat_id] = datetime.now()
        logger.info(f"Sent link to group {chat_id}")
    except Exception as e:
        logger.error(f"Error sending to group {chat_id}: {e}")
        ACTIVE_GROUPS.discard(chat_id)

# Command handlers
@bot.message_handler(commands=['help'])
def send_help(message):
    help_text = """
🤖 *Bot Commands*:

/help - Show this help
/link - Show current link
/setlink [url] - Set custom link (admins)
/defaultlink - Reset to default link (admins)
/interval [hours] - Change interval (admins)
/stats - Show statistics (admins)
"""
    bot.reply_to(message, help_text, parse_mode="Markdown")

@bot.message_handler(commands=['myid'])
def show_user_id(message):
    bot.reply_to(message, f"👤 Your Telegram ID: `{message.from_user.id}`", parse_mode="Markdown")

@bot.message_handler(commands=['link'])
def show_link(message):
    current_link = GROUP_LINKS.get(message.chat.id, DEFAULT_LINK)
    bot.reply_to(message, f"🔗 Current link:\n{current_link}")

@bot.message_handler(commands=['setlink'])
def set_link(message):
    if not (is_admin(message.from_user.id) or is_group_admin(message)):
        bot.reply_to(message, "🚫 Admin only command!")
        return
    
    try:
        new_link = message.text.split()[1]
        if not new_link.startswith(('http://', 'https://')):
            raise ValueError("Invalid URL format")
        
        GROUP_LINKS[message.chat.id] = new_link
        if message.chat.id in GROUP_INFO:
            GROUP_INFO[message.chat.id]["link"] = new_link
        bot.reply_to(message, f"✅ Link updated to:\n{new_link}")
    except (IndexError, ValueError):
        bot.reply_to(message, "Usage: /setlink https://example.com")

@bot.message_handler(commands=['defaultlink'])
def default_link(message):
    if not (is_admin(message.from_user.id) or is_group_admin(message)):
        bot.reply_to(message, "🚫 Admin only command!")
        return
    
    if message.chat.id in GROUP_LINKS:
        del GROUP_LINKS[message.chat.id]
    if message.chat.id in GROUP_INFO:
        GROUP_INFO[message.chat.id]["link"] = DEFAULT_LINK
    bot.reply_to(message, f"✅ Reset to default link:\n{DEFAULT_LINK}")

@bot.message_handler(commands=['interval'])
def set_interval(message):
    if not (is_admin(message.from_user.id) or is_group_admin(message)):
        bot.reply_to(message, "🚫 Admin only command!")
        return
    
    try:
        hours = int(message.text.split()[1])
        global MESSAGE_INTERVAL
        MESSAGE_INTERVAL = hours * 3600
        bot.reply_to(message, f"⏰ Posting interval set to {hours} hours")
    except (IndexError, ValueError):
        bot.reply_to(message, "Usage: /interval 24 (sets to 24 hours)")

@bot.message_handler(commands=['stats'])
def show_stats(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "🚫 Admin only command!")
        return
    
    stats_text = f"""
📊 *Bot Statistics*:

• Active groups: {len(ACTIVE_GROUPS)}
• Posting interval: {MESSAGE_INTERVAL//3600} hours
• Next post here: {get_next_post_time(message.chat.id)}

📋 *Group Links*:
"""
    for group_id, info in GROUP_INFO.items():
        stats_text += f"\n- {info['title']}: {info['link']}"
    
    bot.reply_to(message, stats_text, parse_mode="Markdown")

# Automatic link sending
def send_links_periodically():
    while True:
        try:
            for group_id in list(ACTIVE_GROUPS):
                send_link_to_group(group_id)
            time.sleep(MESSAGE_INTERVAL)
        except Exception as e:
            logger.error(f"Error in scheduler: {e}")
            time.sleep(60)

# Group management
@bot.message_handler(content_types=['new_chat_members'])
def new_member(message):
    for member in message.new_chat_members:
        if member.id == bot.get_me().id:
            ACTIVE_GROUPS.add(message.chat.id)
            send_welcome_and_link(message.chat.id)

@bot.message_handler(content_types=['left_chat_member'])
def left_member(message):
    if message.left_chat_member.id == bot.get_me().id:
        ACTIVE_GROUPS.discard(message.chat.id)
        if message.chat.id in GROUP_INFO:
            del GROUP_INFO[message.chat.id]
        logger.info(f"Removed from group {message.chat.id}")


# Enhanced start command
@bot.message_handler(commands=['start'])
def start_command(message):
    if is_admin(message.from_user.id):
        # Admin menu
        admin_text = """
👑 *Admin Control Panel* 👑

📊 *Bot Management*:
/start - Show this panel
/stats - View bot statistics
/interval [hours] - Change posting interval

🔗 *Link Management*:
/setlink [url] - Set custom link for this group
/defaultlink - Reset to default link
/link - Show current link

👥 *User Tools*:
/myid - Show your Telegram ID
/help - Show help for all users
"""
        bot.reply_to(message, admin_text, parse_mode="Markdown")
    else:
        # User menu
        user_text = """
🤖 *Welcome to Link Sharing Bot* 🌐

🔗 *Available Commands*:
/link - Show current group link
/help - Show detailed help
/myid - Show your Telegram ID

📢 The bot automatically shares links in this group.
Admins can customize the link using /setlink
"""
        bot.reply_to(message, user_text, parse_mode="Markdown")
    
    # Activate group if in a group chat
    if message.chat.type in ['group', 'supergroup']:
        ACTIVE_GROUPS.add(message.chat.id)
        if message.chat.id not in GROUP_INFO:
            send_welcome_and_link(message.chat.id)

# Update help command to be user-friendly
@bot.message_handler(commands=['help'])
def send_help(message):
    if is_admin(message.from_user.id):
        help_text = """
🛠️ *Admin Help Menu* 🛠️

I'm a link-sharing bot that automatically posts links in groups.

🔧 *Admin Commands*:
/stats - View bot statistics
/interval [hours] - Change posting frequency
/setlink [url] - Set custom group link
/defaultlink - Reset to default link

ℹ️ *General Commands*:
/link - Show current link
/myid - Show your Telegram ID
/help - Show this message
"""
    else:
        help_text = """
ℹ️ *User Help Menu* ℹ️

I'm a link-sharing bot that automatically posts links in this group.

📋 *Available Commands*:
/link - Show current group link
/myid - Show your Telegram ID
/help - Show this message

Need help? Contact the group admins.
"""
    bot.reply_to(message, help_text, parse_mode="Markdown")



def send_welcome_and_link(chat_id):
    try:
        chat = bot.get_chat(chat_id)
        GROUP_INFO[chat_id] = {
            "title": chat.title,
            "link": GROUP_LINKS.get(chat_id, DEFAULT_LINK)
        }
        
        # Send the link immediately in clean format
        link_msg = f"""
🌟 *Welcome to {chat.title}!* 🌟

Here's our group link:
🔗 {GROUP_INFO[chat_id]['link']}

• Share with friends
• Join anytime
• Link never expires
"""
        bot.send_message(chat_id, link_msg, parse_mode="Markdown")
        
        # Update last message time
        LAST_MESSAGE_TIMES[chat_id] = datetime.now()
        logger.info(f"Auto-sent link to new group {chat_id}")
    except Exception as e:
        logger.error(f"Error sending welcome to {chat_id}: {e}")

# Modified group join handler
@bot.message_handler(content_types=['new_chat_members'])
def new_member(message):
    for member in message.new_chat_members:
        if member.id == bot.get_me().id:
            ACTIVE_GROUPS.add(message.chat.id)
            # Send link immediately without any command
            send_welcome_and_link(message.chat.id)
            # Also send brief help for admins
            if is_admin(message.from_user.id) or is_group_admin(message):
                bot.send_message(
                    message.chat.id,
                    "🛠 *Admin Tip*: Use /setlink to change this group's link",
                    parse_mode="Markdown"
                )

# Start the bot
if __name__ == "__main__":
    logger.info("Starting bot...")
    scheduler = threading.Thread(target=send_links_periodically)
    scheduler.daemon = True
    scheduler.start()
    
    while True:
        try:
            bot.polling(none_stop=True)
        except Exception as e:
            logger.error(f"Bot crashed: {e}")
            time.sleep(15)