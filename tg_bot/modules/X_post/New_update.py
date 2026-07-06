import re
import asyncio
import httpx
import logging
from telegram import Update
from telegram.ext import ContextTypes
from telegram import InputMediaPhoto

from modules.Translate.translator import translator_service



logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

SEMAPHORE = asyncio.Semaphore(5)


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
            
            tweet_text = translator_service.translate(tweet_text)
            
            if chat_id == -1004358606228:
                send_id = -1002227536883

            if chat_id == -1002029795026:
                send_id = -1002029795026
            # ── KAMA INA VIDEO ───
            if videos:
                video_url = videos[0]["url"]
                caption = tweet_text[:1024]

                await context.bot.send_video(
                    chat_id=send_id,
                    video=video_url,
                    caption=caption,
                    parse_mode="HTML",
                )
                logger.info(f"Video imetumwa: {video_url[:60]}")
                return

            # ── KAMA INA PICHA MOJA AU NYINGI ────
            if photos:
                if len(photos) == 1:
                    # Picha moja — tuma kama photo na caption
                    caption = tweet_text[:1024]

                    await context.bot.send_photo(
                        chat_id=send_id,
                        photo=photos[0]["url"],
                        caption=caption,
                        parse_mode="HTML",
                    )
                    logger.info("Picha moja imetumwa")

                else:
                    # Picha nyingi — tuma kama media group
                    media_group = []
                    for i, photo in enumerate(photos[:10]):  # Telegram max ni 10
                        if i == 0:
                            # Caption kwenye picha ya kwanza tu
                            caption = tweet_text[:1024]
                            media_group.append(
                                InputMediaPhoto(
                                    media=photo["url"],
                                    caption=caption,
                                    parse_mode="HTML"
                                )
                            )
                        else:
                            media_group.append(InputMediaPhoto(media=photo["url"]))

                    await context.bot.send_media_group(
                        chat_id=send_id,
                        media=media_group,
                    )
                    logger.info(f"Picha {len(media_group)} zimetumwa kama media group")

                return

            # ── TEXT TU (hakuna media) ──
            title = tweet_text.split("\n\n")[0] if "\n\n" in tweet_text else tweet_text.split(", ")[0]
            title = title.replace("\n", " ").strip()

            message = tweet_text

            await context.bot.send_message(
                chat_id=send_id,
                text=message[:4096],
                parse_mode="HTML",
                disable_web_page_preview=False,
            )
            logger.info(f"Text imetumwa: {title[:50]}")

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
                text=error_text[:1000]
            )
        except:
            pass
