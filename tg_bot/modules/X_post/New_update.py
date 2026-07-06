import re
import asyncio
import httpx
import logging
from typing import Optional, Dict, Any, List
from telegram import Update, InputMediaPhoto
from telegram.ext import ContextTypes

from modules.Translate.translator import translator_service

# Usanidi wa logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Constants
SEMAPHORE = asyncio.Semaphore(5)
MAX_CAPTION_LENGTH = 1024
MAX_MESSAGE_LENGTH = 4096
MAX_MEDIA_GROUP = 10
TIMEOUT_SECONDS = 15

# Chat IDs
CHAT_GROUPS = {
    -1004358606228: -1002227536883,  # Group A → Knowledge
    -1002029795026: -1002029795026,  # Group B → Same group
}


def extract_tweet_id(url: str) -> Optional[str]:
    """Toa Tweet ID kutoka URL yoyote ya X/Twitter/FxTwitter."""
    if not url:
        return None
    match = re.search(r'/status/(\d+)', url)
    return match.group(1) if match else None


async def fetch_tweet_data(tweet_id: str) -> Optional[Dict[str, Any]]:
    """Pata data ya tweet kutoka FxTwitter API."""
    if not tweet_id:
        return None
        
    api_url = f"https://api.fxtwitter.com/status/{tweet_id}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
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


async def delete_original_message(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int
) -> bool:
    """
    Futa ujumbe wa asili kwenye chat.
    
    Args:
        context: Context ya bot
        chat_id: ID ya chat
        message_id: ID ya ujumbe wa kufuta
        
    Returns:
        True ikiwa imefutwa, False vinginevyo
    """
    try:
        await context.bot.delete_message(
            chat_id=chat_id,
            message_id=message_id
        )
        logger.info(f"Ujumbe {message_id} umefutwa kutoka {chat_id}")
        return True
    except Exception as e:
        logger.error(f"Imeshindwa kufuta ujumbe {message_id}: {e}")
        return False


def get_target_chat(chat_id: int) -> int:
    """
    Pata target chat ID kulingana na source chat ID.
    
    Args:
        chat_id: Source chat ID
        
    Returns:
        Target chat ID
    """
    return CHAT_GROUPS.get(chat_id, chat_id)


async def send_video(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    video_url: str,
    caption: str
) -> bool:
    """
    Tuma video kwenye chat.
    
    Args:
        context: Context ya bot
        chat_id: Target chat ID
        video_url: URL ya video
        caption: Caption ya video
        
    Returns:
        True ikiwa imetumwa, False vinginevyo
    """
    try:
        await context.bot.send_video(
            chat_id=chat_id,
            video=video_url,
            caption=caption[:MAX_CAPTION_LENGTH],
            parse_mode="HTML",
            supports_streaming=True
        )
        logger.info(f"Video imetumwa: {video_url[:60]}...")
        return True
    except Exception as e:
        logger.error(f"Imeshindwa kutuma video: {e}")
        return False


async def send_photos(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    photos: List[Dict[str, Any]],
    caption: str
) -> bool:
    """
    Tuma picha kwenye chat.
    
    Args:
        context: Context ya bot
        chat_id: Target chat ID
        photos: Lista ya picha
        caption: Caption ya picha
        
    Returns:
        True ikiwa imetumwa, False vinginevyo
    """
    try:
        if len(photos) == 1:
            # Picha moja
            photo_url = photos[0].get("url")
            if not photo_url:
                logger.warning("Photo URL haipatikani")
                return False
                
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=photo_url,
                caption=caption[:MAX_CAPTION_LENGTH],
                parse_mode="HTML",
            )
            logger.info("Picha moja imetumwa")
            
        else:
            # Picha nyingi
            media_group = []
            for i, photo in enumerate(photos[:MAX_MEDIA_GROUP]):
                photo_url = photo.get("url")
                if not photo_url:
                    continue
                    
                if i == 0:
                    media_group.append(
                        InputMediaPhoto(
                            media=photo_url,
                            caption=caption[:MAX_CAPTION_LENGTH],
                            parse_mode="HTML"
                        )
                    )
                else:
                    media_group.append(InputMediaPhoto(media=photo_url))

            if media_group:
                await context.bot.send_media_group(
                    chat_id=chat_id,
                    media=media_group,
                )
                logger.info(f"Picha {len(media_group)} zimetumwa kama media group")
            else:
                logger.warning("Hakuna picha halali katika media group")
                return False
                
        return True
        
    except Exception as e:
        logger.error(f"Imeshindwa kutuma picha: {e}")
        return False


async def send_text(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    text: str
) -> bool:
    """
    Tuma maandishi kwenye chat.
    
    Args:
        context: Context ya bot
        chat_id: Target chat ID
        text: Maandishi ya kutuma
        
    Returns:
        True ikiwa imetumwa, False vinginevyo
    """
    try:
        # Punguza maandishi ikiwa ni mrefu sana
        if len(text) > MAX_MESSAGE_LENGTH:
            text = text[:MAX_MESSAGE_LENGTH] + "..."
            
        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=False,
        )
        
        # Toa title kwa logging
        title = text.split("\n\n")[0] if "\n\n" in text else text.split(", ")[0]
        title = title.replace("\n", " ").strip()
        logger.info(f"Text imetumwa: {title[:50]}...")
        return True
        
    except Exception as e:
        logger.error(f"Imeshindwa kutuma maandishi: {e}")
        return False


async def x_update(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    new_url: str,
    chat_id: int,
    message_id: Optional[int] = None
):
    """
    Chakata URL ya X/Twitter na itume kwenye chat lengwa.
    
    Args:
        update: Update object
        context: Context ya bot
        new_url: URL ya tweet
        chat_id: ID ya chat ambapo ujumbe ulitolewa
        message_id: ID ya ujumbe wa kufuta (ikiwa inahitajika)
    """
    error_chat_id = chat_id

    try:
        async with SEMAPHORE:
            logger.info(f"Anachakata URL: {new_url}")

            # Toa Tweet ID kutoka URL
            tweet_id = extract_tweet_id(new_url)
            if not tweet_id:
                logger.warning(f"Haiwezi kutoa Tweet ID kutoka: {new_url}")
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"⚠️ URL si sahihi: {new_url}"
                )
                return

            # Pata data kutoka FxTwitter API
            tweet = await fetch_tweet_data(tweet_id)
            if not tweet:
                logger.warning(f"Hakuna data kwa tweet ID: {tweet_id}")
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"⚠️ Imeshindwa kupata tweet: {new_url}"
                )
                return

            # Toa taarifa muhimu
            tweet_text = tweet.get("text", "")
            media = tweet.get("media", {}) or {}
            videos = media.get("videos", []) or []
            photos = media.get("photos", []) or []
            
            logger.info(
                f"Tweet imepatikana: video={len(videos)} picha={len(photos)}"
            )
            
            # Tafsiri maandishi
            translated_text = translator_service.translate(tweet_text)
            
            # Amua target chat
            target_chat_id = get_target_chat(chat_id)
            logger.info(f"Target chat: {target_chat_id} (kutoka {chat_id})")
            
            # Futa ujumbe wa asili ikiwa ni chat ya Group B
            if chat_id == -1002029795026 and message_id:
                await delete_original_message(context, chat_id, message_id)
            
            # Andaa caption
            caption = translated_text[:MAX_CAPTION_LENGTH]

            # ── KAMA INA VIDEO ───
            if videos:
                video_url = videos[0].get("url")
                if not video_url:
                    logger.warning("Video URL haipatikani")
                    return
                    
                await send_video(context, target_chat_id, video_url, caption)
                return

            # ── KAMA INA PICHA ────
            if photos:
                await send_photos(context, target_chat_id, photos, caption)
                return

            # ── TEXT TU (hakuna media) ──
            await send_text(context, target_chat_id, translated_text)

    except Exception as e:
        logger.exception(f"Hitilafu kubwa: {e}")

        error_text = (
            "❌ HITILAFU URL_UPDATE\n"
            f"Chat ID: {chat_id}\n"
            f"Error: {str(e)[:200]}\n"
            f"URL: {new_url}"
        )

        try:
            await context.bot.send_message(
                error_chat_id,
                text=error_text[:MAX_MESSAGE_LENGTH]
            )
        except Exception as e:
            logger.error(f"Imeshindwa kutuma ujumbe wa hitilafu: {e}")
