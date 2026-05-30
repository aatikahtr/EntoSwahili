# rss_scheduler.py (version 2 - with concurrency)
import asyncio
import logging
from typing import List, Dict, Any
from telegram import Bot
from telegram.ext import Application, ContextTypes
from .rss_command import (
    get_all_subscriptions,
    scrape_posts,
    get_seen_ids,
    mark_seen,
    update_last_check,
)

logger = logging.getLogger(__name__)

# Configuration - rahisi kubadilisha
MAX_CONCURRENT_CHECKS = 3  # Tunaanza na 3, baadaye tunaweza kuongeza hadi 5
TIMEOUT_PER_SITE = 45      # sekunde
MAX_RETRIES = 2             # Jaribu mara 2 kama site inafail


async def check_one_subscription(entry: Dict[str, Any], bot: Bot) -> int:
    """
    Kagua site moja tu.
    Return: idadi ya posts mpya zilizopatikana (0 ikiwa hakuna au kuna error)
    """
    chat_id = entry["chat_id"]
    sub = entry["sub"]
    url = sub["url"]
    site_name = sub["name"]
    
    for attempt in range(MAX_RETRIES + 1):
        try:
            # Timeout kwa site inayokwama
            _, posts = await asyncio.wait_for(
                scrape_posts(url),
                timeout=TIMEOUT_PER_SITE
            )
            break  # Success - toka kwenye retry loop
        except asyncio.TimeoutError:
            logger.warning(f"[RSS] Timeout {url} (attempt {attempt + 1}/{MAX_RETRIES + 1})")
            if attempt == MAX_RETRIES:
                logger.error(f"[RSS] Site imekwama kabisa: {url}")
                return 0
            await asyncio.sleep(2)  # Subiri kidogo kabla ya kujaribu tena
        except Exception as e:
            logger.warning(f"[RSS] Imeshindwa {url}: {e} (attempt {attempt + 1})")
            if attempt == MAX_RETRIES:
                return 0
            await asyncio.sleep(1)
    
    # Angalia posts mpya
    seen = await get_seen_ids(chat_id, url)
    new_posts = [p for p in posts if p["id"] not in seen]
    
    await update_last_check(chat_id, url)
    
    if not new_posts:
        return 0
    
    logger.info(f"[RSS] Mpya {len(new_posts)} — {site_name} → {chat_id}")
    
    # Tuma posts 5 za kwanza
    for post in new_posts[:5]:
        try:
            await bot.send_message(
                chat_id=int(chat_id),
                text=(
                    f"🆕 <b>{site_name}</b>\n\n"
                    f"📰 {post['title']}\n\n"
                    f"{post['link']}"
                ),
                parse_mode="HTML",
                disable_web_page_preview=False,
            )
        except Exception as e:
            logger.warning(f"[RSS] Kutuma kumeshindwa {chat_id}: {e}")
    
    # Ikiwa kuna posts zaidi ya 5, tuma muhtasari
    if len(new_posts) > 5:
        try:
            await bot.send_message(
                chat_id=int(chat_id),
                text=(
                    f"📌 <b>{site_name}</b> ina posts "
                    f"<b>{len(new_posts) - 5}</b> zaidi mpya.\n"
                    f"Tembelea: <a href='{url}'>{url}</a>"
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass
    
    # Mark posts kama zimeshaonekana
    await mark_seen(chat_id, url, [p["id"] for p in new_posts])
    
    return len(new_posts)


async def check_all_subscriptions(app: Application):
    """
    Kagua sites zote kwa CONCURRENT (sio sequential)!
    Hii ndio maboresho muhimu.
    """
    bot: Bot = app.bot
    all_subs = await get_all_subscriptions()
    
    if not all_subs:
        logger.info("[RSS] Hakuna subscriptions zozote.")
        return
    
    logger.info(f"[RSS] Inaanza kagua sites {len(all_subs)} kwa concurrent (max {MAX_CONCURRENT_CHECKS} kwa wakati mmoja)")
    
    # Tumia semaphore kudhibiti idadi ya sites zinazokaguliwa kwa wakati mmoja
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_CHECKS)
    
    async def check_with_limit(entry):
        async with semaphore:
            return await check_one_subscription(entry, bot)
    
    # Kaa sites zote kwa wakati mmoja (lakini limited na semaphore)
    tasks = [check_with_limit(entry) for entry in all_subs]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Hesabu posts mpya zilizopatikana
    total_new = 0
    for r in results:
        if isinstance(r, int):
            total_new += r
        elif isinstance(r, Exception):
            logger.error(f"[RSS] Site imeshindwa kabisa: {r}")
    
    logger.info(f"[RSS] Imekamilika! Posts mpya zote: {total_new}")


def setup_scheduler(app: Application, interval_minutes: int = 60):
    """
    Weka scheduler — iitwe mara moja tu ndani ya main.py.
    """
    async def _job_callback(context: ContextTypes.DEFAULT_TYPE):
        await check_all_subscriptions(app)
    
    app.job_queue.run_repeating(
        callback=_job_callback,
        interval=interval_minutes * 60,
        first=30,
        name="rss_checker",
    )
    logger.info(f"[RSS] Scheduler imewaka — kila dakika {interval_minutes}.")
