from telegram import InputMediaPhoto, InputMediaVideo
from telegram.constants import ParseMode


def make_photo(file_id: str, caption: str = None) -> InputMediaPhoto:
    """Create InputMediaPhoto object"""
    return InputMediaPhoto(
        media=file_id,
        caption=caption,
        parse_mode=ParseMode.HTML
    )


def make_video(file_id: str, caption: str = None) -> InputMediaVideo:
    """Create InputMediaVideo object"""
    return InputMediaVideo(
        media=file_id,
        caption=caption,
        parse_mode=ParseMode.HTML
    )
