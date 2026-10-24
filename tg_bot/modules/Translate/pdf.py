import asyncio
import io
import logging
import os

import fitz  # PyMuPDF
from telegram import Update, Message
from telegram.ext import ContextTypes

from .translator import translator_service

logger = logging.getLogger(__name__)

# Mipaka (unaweza kubadilisha)
MAX_PAGES = int(os.getenv("PDF_MAX_PAGES", 40))
MAX_SIZE_MB = 20  # Bot API inaruhusu kupakua hadi 20MB


def is_pdf(msg: Message) -> bool:
    """Kagua kama ujumbe una PDF"""
    doc = msg.document
    if not doc:
        return False
    name = (doc.file_name or "").lower()
    return doc.mime_type == "application/pdf" or name.endswith(".pdf")


def _block_text_and_style(block: dict):
    """Toa maandishi + ukubwa wa herufi + rangi kutoka block ya PyMuPDF"""
    lines, size, color = [], 11.0, 0
    first = True
    for line in block.get("lines", []):
        parts = []
        for span in line.get("spans", []):
            parts.append(span["text"])
            if first and span["text"].strip():
                size = span["size"]
                color = span["color"]
                first = False
        lines.append("".join(parts).strip())
    return " ".join(x for x in lines if x), size, color


def _int_to_rgb(c: int):
    return ((c >> 16 & 255) / 255, (c >> 8 & 255) / 255, (c & 255) / 255)


def translate_pdf_bytes(data: bytes) -> tuple[bytes | None, int, int]:
    """
    Tafsiri PDF na uhifadhi mpangilio (layout).
    Inarudisha (pdf_bytes, idadi_ya_kurasa, idadi_ya_blocks) — pdf_bytes=None kama ni scan.
    """
    doc = fitz.open(stream=data, filetype="pdf")
    pages = min(len(doc), MAX_PAGES)

    total_blocks = 0
    for pno in range(pages):
        page = doc[pno]
        blocks = [
            b for b in page.get_text("dict")["blocks"] if b.get("type") == 0
        ]

        items = []  # (rect, original, size, color)
        for b in blocks:
            text, size, color = _block_text_and_style(b)
            if len(text) < 2 or text.replace(".", "").replace(" ", "").isdigit():
                continue
            items.append((fitz.Rect(b["bbox"]), text, size, color))

        if not items:
            continue

        translated = translator_service.translate_batch([i[1] for i in items])

        # 1) Futa maandishi ya asili
        todo = []
        for (rect, orig, size, color), tr in zip(items, translated):
            if translator_service.should_translate(orig, tr):
                page.add_redact_annot(rect, fill=(1, 1, 1))
                todo.append((rect, tr, size, color))
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

        # 2) Andika tafsiri mahali pale pale
        for rect, tr, size, color in todo:
            fs = size
            while fs >= 4:
                rc = page.insert_textbox(
                    rect,
                    tr,
                    fontsize=fs,
                    fontname="helv",
                    color=_int_to_rgb(color),
                )
                if rc >= 0:  # imetosha
                    break
                fs -= 0.5
            total_blocks += 1

    if total_blocks == 0:
        doc.close()
        return None, pages, 0

    out = doc.tobytes(garbage=3, deflate=True)
    doc.close()
    return out, pages, total_blocks


async def translate_pdf(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    target: Message,
):
    """Pakua PDF -> tafsiri -> tuma PDF ya Kiswahili"""
    reply_to = update.effective_message
    doc = target.document

    if doc.file_size and doc.file_size > MAX_SIZE_MB * 1024 * 1024:
        await reply_to.reply_text(f"⚠️ PDF ni kubwa mno. Kikomo ni {MAX_SIZE_MB}MB.")
        return

    status = await reply_to.reply_text("⏳ Napakua na kutafsiri PDF... inaweza kuchukua dakika kidogo.")

    try:
        tg_file = await context.bot.get_file(doc.file_id)
        data = bytes(await tg_file.download_as_bytearray())

        # Kazi nzito iende kwenye thread ili bot isizuiwe
        result, pages, blocks = await asyncio.to_thread(translate_pdf_bytes, data)

        if result is None:
            await status.edit_text(
                "⚠️ Sijapata maandishi kwenye PDF hii (huenda ni scan/picha). "
                "PDF za picha zinahitaji OCR."
            )
            return

        base = os.path.splitext(doc.file_name or "document")[0]
        await reply_to.reply_document(
            document=io.BytesIO(result),
            filename=f"{base}_sw.pdf",
            caption=f"✅ Imetafsiriwa kwenda Kiswahili ({pages} kurasa)",
            message_thread_id=target.message_thread_id,
        )
        await status.delete()

    except Exception as e:
        logger.exception("PDF translate error")
        await status.edit_text(f"❌ Imeshindwa kutafsiri PDF: {e}")
