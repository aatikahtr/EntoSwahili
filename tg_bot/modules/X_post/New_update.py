import re
import asyncio
import httpx
import logging
import easyocr
from telegram import Update, InputMediaPhoto
from telegram.ext import ContextTypes

from modules.Translate.translator import translator_service

# ─── Logger setup ───
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

Knowledge = -1002227536883
SEMAPHORE = asyncio.Semaphore(5)

# ─── OCR Reader ───
reader = easyocr.Reader(['en', 'sw'])  # unaweza kuongeza lugha nyingine

def extract_tweet_id(url: str) -> str | None:
    """Toa Tweet ID kutoka URL yoyote ya X/Twitter/FxTwitter."""
    match = re.search(r'/status/(\d+)', url)
    return match.group(1) if match else None


async def fetch_tweet_data(tweet_id: str) -> dict | None:
    """Pata data ya tweet kutoka FxTwitter API."""
    api_url = f"https://api.fxtwitter.com/status/{tweet_id}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                api_url,
                headers={"User-Agent": "TelegramBot/1.0"}
            )
            response.raise_for_status()
            data = response.json()

            if data.get("code") == 200:
                return data.get("tweet")
            else:
                logger.warning(f"API ilikataa: {data.get('message')} kwa ID {tweet_id}")
                return None

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP Error kutoka FxTwitter API: {e.response.status_code}")
        return None
    except Exception as e:
        logger.error(f"Hitilafu ya fetch_tweet_data: {e}")
        return None


async def translate_photo_text(photo_url: str) -> str:
    """Soma maandishi kutoka picha na kutafsiri kwa Kiswahili."""
    try:
        results = reader.readtext(photo_url)
        text_in_photo = " ".join([res[1] for res in results])
        if not text_in_photo.strip():
            return "Hakuna maandishi yaliyopatikana kwenye picha."
        return translator_service.translate(text_in_photo)
    except Exception as e:
        logger.error(f"OCR error: {e}")
        return "Imeshindwa kusoma maandishi kwenye picha."


async def x_update(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    new_url: str,
    chat_id: int
):
    error_chat_id = chat_id

    try:
        async with SEMAPHORE:
            logger.info(f"Anachakata URL: {new_url}")

            # Toa Tweet ID
            tweet_id = extract_tweet_id(new_url)
            if not tweet_id:
                await context.bot.send_message(chat_id=chat_id, text=f"⚠️ URL si sahihi: {new_url}")
                return

            # Pata data
            tweet = await fetch_tweet_data(tweet_id)
            if not tweet:
                await context.bot.send_message(chat_id=chat_id, text=f"⚠️ Imeshindwa kupata tweet: {new_url}")
                return

            # Taarifa muhimu
            tweet_text = tweet.get("text", "")
            media = tweet.get("media", {}) or {}
            videos = media.get("videos", []) or []
            photos = media.get("photos", []) or []

            # Tafsiri maandishi ya tweet
            tweet_text = translator_service.translate(tweet_text)

            # ── VIDEO ──
            if videos:
                video_url = videos[0]["url"]
                caption = tweet_text[:1024]
                await context.bot.send_video(
                    chat_id=Knowledge,
                    video=video_url,
                    caption=caption,
                    parse_mode="HTML",
                )
                return

            # ── PICHA ──
            if photos:
                if len(photos) == 1:
                    translated_caption = await translate_photo_text(photos[0]["url"])
                    await context.bot.send_photo(
                        chat_id=Knowledge,
                        photo=photos[0]["url"],
                        caption=translated_caption[:1024],
                        parse_mode="HTML",
                    )
                else:
                    media_group = []
                    for i, photo in enumerate(photos[:10]):
                        if i == 0:
                            translated_caption = await translate_photo_text(photo["url"])
                            media_group.append(
                                InputMediaPhoto(
                                    media=photo["url"],
                                    caption=translated_caption[:1024],
                                    parse_mode="HTML"
                                )
                            )
                        else:
                            media_group.append(InputMediaPhoto(media=photo["url"]))
                    await context.bot.send_media_group(chat_id=Knowledge, media=media_group)
                return

            # ── TEXT TU ──
            await context.bot.send_message(
                chat_id=Knowledge,
                text=tweet_text[:4096],
                parse_mode="HTML",
                disable_web_page_preview=False,
            )

    except Exception as e:
        logger.exception(f"Hitilafu kubwa: {e}")
        error_text = f"❌ HITILAFU URL_UPDATE\nChat ID: {chat_id}\nError: {str(e)[:200]}\nURL: {new_url}"
        try:
            await context.bot.send_message(error_chat_id, text=error_text[:1000])
        except:
            pass
