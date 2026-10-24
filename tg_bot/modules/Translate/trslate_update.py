import logging
from telegram import Update
from telegram.ext import ContextTypes
from .media import (
    handle_media_group,
    translate_single_media
)
from .pdf import is_pdf, translate_pdf

logger = logging.getLogger(__name__)

LOG_CHAT_ID = -1002158955567

USAGE = (
    "ℹ️ Jinsi ya kutumia /tr:\n\n"
    "• Reply ujumbe wowote kisha andika /tr\n"
    "• /tr maandishi yako hapa\n"
    "• Tuma PDF moja kwa moja (au reply PDF kwa /tr) nikutafsirie"
)


def _is_tr_command(message) -> bool:
    """Ujumbe (au caption) unaanza na /tr au /tr@botname"""
    raw = (message.text or message.caption or "").strip()
    first = raw.split(maxsplit=1)[0].lower() if raw else ""
    return first == "/tr" or first.startswith("/tr@")


async def trslate_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main message router - inashughulikia MessageHandler NA /tr (reply_to)"""
    message = update.effective_message
    try:
        if not message:
            return

        is_cmd = _is_tr_command(message)
        is_private = message.chat.type == "private"

        # Chagua ujumbe wa kutafsiri:
        # - Kama mtumiaji alireply ujumbe → tafsiri ule ujumbe wa asili
        # - Kama ni ujumbe wa kawaida → tafsiri ujumbe huu huu
        target = message.reply_to_message or message

        # /tr maandishi... (bila reply) → tafsiri maandishi yaliyoandikwa
        if is_cmd and not message.reply_to_message and message.text:
            inline = message.text.split(maxsplit=1)
            if len(inline) < 2:
                await message.reply_text(USAGE)
                return
            from .text import translate_text
            # tengeneza "target" bandia kwa kutumia text iliyobaki
            message.text = inline[1]
            await translate_text(update, context, message, force=True)
            return

        # Zuia kujitafsiri (bot haireplyi yenyewe) — isipokuwa /tr ya makusudi
        if not is_cmd and target.from_user and target.from_user.is_bot:
            return

        # ── PDF ──────────────────────────────────────
        # Private: PDF yoyote. Group: pale tu /tr inapotumika.
        if is_pdf(target) and (is_private or is_cmd):
            await translate_pdf(update, context, target)
            return

        # Kama ni media group (album)
        if target.media_group_id:
            await handle_media_group(update, context, target)
            return

        # Kama ni maandishi
        if target.text:
            from .text import translate_text
            await translate_text(update, context, target, force=is_cmd)
            return

        # Media ya single (picha/video yenye caption)
        if is_cmd and not (target.caption or target.document):
            await message.reply_text(USAGE)
            return
        await translate_single_media(update, context, target)

    except Exception as e:
        logger.exception("trslate_message error")
        # Mtumiaji aone kosa, si kimya tu
        try:
            if message:
                await message.reply_text(f"❌ Hitilafu: {e}")
        except Exception:
            pass
        try:
            await context.bot.send_message(
                LOG_CHAT_ID, f"❌ handle_message error:\n{e}"
            )
        except Exception:
            pass
