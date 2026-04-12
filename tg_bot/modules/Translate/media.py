from html import escape
from telegram import Update
from telegram.ext import ContextTypes
from services.translator import translator_service
from utils.media_helpers import make_photo, make_video
from config import MEDIA_GROUP_DEBOUNCE_SECONDS, LOG_CHAT_ID


async def translate_single_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle single photo/video with caption"""
    msg = update.message

    if not msg.caption:
        return

    # Translate caption
    translated = translator_service.translate(msg.caption)

    if not translator_service.should_translate(msg.caption, translated):
        return

    # Reply with appropriate media type
    if msg.photo:
        await msg.reply_photo(
            msg.photo[-1].file_id,
            caption=translated,
            message_thread_id=msg.message_thread_id
        )

    elif msg.video:
        await msg.reply_video(
            msg.video.file_id,
            caption=translated,
            message_thread_id=msg.message_thread_id
        )

    elif msg.animation:
        await msg.reply_animation(
            msg.animation.file_id,
            caption=translated,
            message_thread_id=msg.message_thread_id
        )
        
    elif msg.document:
        await msg.reply_document(
            msg.document.file_id,
            caption=translated,
            message_thread_id=msg.message_thread_id
        )
        
    elif msg.audio:
        await msg.reply_audio(
            msg.audio.file_id,
            caption=translated,
            message_thread_id=msg.message_thread_id
        )


async def handle_media_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Collect media group items and schedule sending"""
    msg = update.effective_message
    group_id = msg.media_group_id

    bot_data = context.application.bot_data
    media_groups = bot_data.setdefault("media_groups", {})
    captions = bot_data.setdefault("media_captions", {})

    # Process caption only once (first message)
    if group_id not in captions:
        original = msg.caption

        if not original:
            captions[group_id] = None
        else:
            translated = translator_service.translate(original)

            if translator_service.should_translate(original, translated):
                captions[group_id] = escape(translated)
            else:
                captions[group_id] = None

    # Caption only on first media item
    caption = captions[group_id] if len(media_groups.get(group_id, [])) == 0 else None
    if caption:
        caption = caption[:1024]

    # Create media object
    if msg.photo:
        media = make_photo(msg.photo[-1].file_id, caption)
    elif msg.video:
        media = make_video(msg.video.file_id, caption)
    else:
        return

    media_groups.setdefault(group_id, []).append(media)

    # Debounce: remove old jobs
    for job in context.job_queue.get_jobs_by_name(str(group_id)):
        job.schedule_removal()

    # Schedule new send job
    context.job_queue.run_once(
        send_media_group,
        when=MEDIA_GROUP_DEBOUNCE_SECONDS,
        data={
            "chat_id": msg.chat.id,
            "group_id": group_id,
            "thread_id": msg.message_thread_id,
        },
        name=str(group_id),
    )


async def send_media_group(context: ContextTypes.DEFAULT_TYPE):
    """Send collected media group"""
    data = context.job.data
    chat_id = data["chat_id"]
    group_id = data["group_id"]
    thread_id = data.get("thread_id")

    bot_data = context.application.bot_data
    media_groups = bot_data.get("media_groups", {})
    captions = bot_data.get("media_captions", {})

    # Skip if no translation needed
    if captions.get(group_id) is None:
        media_groups.pop(group_id, None)
        captions.pop(group_id, None)
        return

    # Send media group
    if group_id in media_groups:
        try:
            await context.bot.send_media_group(
                chat_id=chat_id,
                media=media_groups[group_id],
                message_thread_id=thread_id
            )
        except Exception as e:
            await context.bot.send_message(
                LOG_CHAT_ID,
                f"❌ send_media_group error:\n{e}"
            )
        finally:
            media_groups.pop(group_id, None)
            captions.pop(group_id, None)


