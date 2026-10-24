import re
import time
import threading
from deep_translator import GoogleTranslator


# Translation
TRANSLATION_SOURCE = "auto"
TRANSLATION_TARGET = "sw"


Kata = re.compile(r"🔗\s*(Telegram|X|WhatsApp|Instagram)")


class TranslatorService:
    def __init__(self):
        # Tengeneza kifaa cha kutafsiri kwa kutumia GoogleTranslator
        # source = lugha ya awali
        # target = lugha lengwa
        self.translator = GoogleTranslator(
            source=TRANSLATION_SOURCE,
            target=TRANSLATION_TARGET
        )
    
    # ── Kupunguza kasi + kujaribu tena (Google: ~5 maombi/sekunde) ──
    _lock = threading.Lock()
    _last_call = 0.0
    MIN_INTERVAL = 0.5   # sekunde kati ya maombi
    MAX_RETRIES = 5

    def _call(self, text: str) -> str:
        delay = 2.0
        for attempt in range(self.MAX_RETRIES):
            with self._lock:
                wait = self.MIN_INTERVAL - (time.monotonic() - self._last_call)
                if wait > 0:
                    time.sleep(wait)
                self._last_call = time.monotonic()
            try:
                return self.translator.translate(text)
            except Exception as e:
                too_many = "too many requests" in str(e).lower() or "429" in str(e)
                if not too_many or attempt == self.MAX_RETRIES - 1:
                    raise
                time.sleep(delay)   # subiri kisha jaribu tena
                delay *= 2
        return text

    def translate(self, text: str) -> str:
        """
        Tafsiri maandishi na fanya marekebisho maalum baada ya tafsiri
        """
        # Kama hakuna maandishi, rudisha maandishi tupu
        if not text:
            return ""
        
        text = Kata.split(text, 1)[0]
        # Tafsiri maandishi kwa kutumia Google Translator
        translated = self._call(text)

        # Marekebisho maalum ya maneno baada ya tafsiri
        # Badilisha "Mwenyezi Mungu" kuwa "Allah"
        translated = translated.replace("Mwenyezi Mungu", "Allah")
        
        return translated
    
    def translate_long(self, text: str, limit: int = 4500) -> str:
        """Tafsiri maandishi marefu (Google huruhusu ~5000 herufi kwa mara moja)"""
        if len(text) <= limit:
            return self.translate(text)

        parts, current = [], ""
        for para in text.split("\n"):
            while len(para) > limit:  # aya ndefu mno -> kata vipande
                if current:
                    parts.append(current)
                    current = ""
                parts.append(para[:limit])
                para = para[limit:]
            if len(current) + len(para) + 1 > limit:
                parts.append(current)
                current = para
            else:
                current = f"{current}\n{para}" if current else para
        if current:
            parts.append(current)

        return "\n".join(self.translate(x) for x in parts)

    def translate_batch(self, texts: list[str], limit: int = 4000) -> list[str]:
        """
        Tafsiri vipande vingi kwa maombi machache: kila kipande kinakuwa mstari
        mmoja, vinaunganishwa hadi ~4000 herufi kwa ombi. Idadi ya mistari
        ikibadilika, tunarudi kutafsiri kimoja kimoja.
        """
        flat = [" ".join(x.split()) for x in texts]
        result = list(texts)

        # panga vipande kwenye makundi
        groups, cur, size = [], [], 0
        for i, s in enumerate(flat):
            if not s:
                continue
            if cur and size + len(s) + 1 > limit:
                groups.append(cur)
                cur, size = [], 0
            cur.append(i)
            size += len(s) + 1
        if cur:
            groups.append(cur)

        for idxs in groups:
            joined = "\n".join(flat[i] for i in idxs)
            try:
                out = self._call(joined).split("\n")
                if len(out) == len(idxs):
                    for i, o in zip(idxs, out):
                        result[i] = o.replace("Mwenyezi Mungu", "Allah")
                    continue
            except Exception:
                pass
            # fallback: kimoja kimoja
            for i in idxs:
                try:
                    result[i] = self.translate(flat[i])
                except Exception:
                    result[i] = texts[i]
        return result

    def should_translate(self, original: str, translated: str) -> bool:
        """
        Kagua kama tafsiri ni tofauti na maandishi ya awali
        Inarudisha True kama kuna tofauti, vinginevyo False
        """
        return translated.strip() != original.strip()


'''Instance ya pamoja (global) ya TranslatorService'''
# Inatumika sehemu mbalimbali za programu bila kuunda upya
translator_service = TranslatorService()
