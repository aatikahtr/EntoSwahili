import re
from deep_translator import GoogleTranslator
from config import TRANSLATION_SOURCE, TRANSLATION_TARGET


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
    
    def should_translate(self, original: str, translated: str) -> bool:
        """
        Kagua kama tafsiri ni tofauti na maandishi ya awali
        Inarudisha True kama kuna tofauti, vinginevyo False
        """
        return translated.strip() != original.strip()


'''Instance ya pamoja (global) ya TranslatorService'''
# Inatumika sehemu mbalimbali za programu bila kuunda upya
translator_service = TranslatorService()
