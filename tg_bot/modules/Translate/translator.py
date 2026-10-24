import re
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
    
    def translate(self, text: str) -> str:
        """
        Tafsiri maandishi na fanya marekebisho maalum baada ya tafsiri
        """
        # Kama hakuna maandishi, rudisha maandishi tupu
        if not text:
            return ""
        
        text = Kata.split(text, 1)[0]
        # Tafsiri maandishi kwa kutumia Google Translator
        translated = self.translator.translate(text)

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

    def translate_batch(self, texts: list[str]) -> list[str]:
        """Tafsiri orodha ya vipande (kwa PDF). Kipande kikishindwa, kinabaki asili."""
        out = []
        for t in texts:
            try:
                out.append(self.translate(t) if t.strip() else t)
            except Exception:
                out.append(t)
        return out

    def should_translate(self, original: str, translated: str) -> bool:
        """
        Kagua kama tafsiri ni tofauti na maandishi ya awali
        Inarudisha True kama kuna tofauti, vinginevyo False
        """
        return translated.strip() != original.strip()


'''Instance ya pamoja (global) ya TranslatorService'''
# Inatumika sehemu mbalimbali za programu bila kuunda upya
translator_service = TranslatorService()
