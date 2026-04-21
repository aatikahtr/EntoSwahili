import re
import asyncio
from urllib.parse import urlparse

from telegram import Update
from telegram.ext import ContextTypes

# =====================
# ZUIA WORDS
# =====================
zuia = {
    "list@rss",
    "your subscriptions:",
    "@rss2tg_bot",
    "removed:",
    "⚠️",
    "added:",
    "/settings@rss",
    "latest record:"
}

# =====================
# URL REGEX
# =====================
url_pattern = re.compile(r'https?://\S+')

# =====================
# DOMAINS ZINAZOKUBALIKA
# =====================
allowed_domains = [
    "tiktok.com",
    "instagram.com",
    "youtube.com",
    "youtu.be"
]

# =====================
# STORAGE
# =====================
url_queues = {}     # chat_id -> list ya urls
running_tasks = {}  # chat_id -> task

DELAY = 120  # seconds

# hizi hapa 👇 post zake zinakwenda kwa MARAFIKI.

# Url Update
rs_Update = -1002153005720
# Media Update 🎞
M_Update = -1002012849938



# Hizi hapa 👇 zinakwenda kwenye Uislamu group
# Islamic rs 🔁 👇
Islamic_rs = -1003298737378
# Islamic 📰 ⬇️ 👇
Islamic_news = -1003778143477



# =====================
# EXTRACT VALID URLS
# =====================
def extract_valid_urls(text: str):
    urls = url_pattern.findall(text)
    valid_urls = []

    for url in urls:
        try:
            domain = urlparse(url).netloc.lower()

            if any(allowed in domain for allowed in allowed_domains):
                valid_urls.append(url)

        except Exception:
            continue

    return valid_urls


# =====================
# PROCESS QUEUE
# =====================
async def process_queue(chat_id: int, context: ContextTypes.DEFAULT_TYPE):

    while url_queues.get(chat_id):
        url = url_queues[chat_id].pop(0)

        # =====================
        # ROUTING: Tuma kwa sahihi
        # =====================
        if chat_id == rs_Update:
            send_chat_id = M_Update
        elif chat_id == Islamic_rs:
            send_chat_id = Islamic_news
        else:
            continue

        try:
            await context.bot.send_message(
                chat_id=send_chat_id,
                text=url
            )

        except Exception as e:
            print(f"[{chat_id}] ❌ Error: {e}")

        await asyncio.sleep(DELAY)

    # Task imeisha
    running_tasks.pop(chat_id, None)


# =====================
# MAIN HANDLER
# =====================
async def mojaone(update: Update, context: ContextTypes.DEFAULT_TYPE):

    message = update.channel_post or update.message
    if not message:
        return

    chat_id = message.chat.id
    
    text = message.text or  ""
    if not text:
        return

    text_lower = text.lower()

    # =====================
    # 1. FILTER YA ZUIA
    # =====================
    if any(neno in text_lower for neno in zuia):
        return

    # =====================
    # 2. CHUKUA URL
    # =====================
    urls = extract_valid_urls(text)

    if not urls:
        return

    # =====================
    # 3. WEKA KWENYE QUEUE
    # =====================
    if chat_id not in url_queues:
        url_queues[chat_id] = []

    added_count = 0

    for url in urls:
        if url not in url_queues[chat_id]:
            url_queues[chat_id].append(url)
            added_count += 1

    # =====================
    # 4. ANZISHA TASK
    # =====================
    if chat_id not in running_tasks:
        task = asyncio.create_task(process_queue(chat_id, context))
        running_tasks[chat_id] = task
