"""
Hudhibiti taarifa za mtumiaji (author info)
"""

from telegram import User

# storage ya muda (RAM)
_USERS: dict[int, dict[str, str]] = {}


def get_user_profile(tg_user: User) -> tuple[str, str]:
    """
    Rudisha (author_name, author_url)
    """
    user_id = tg_user.id

    if user_id not in _USERS:
        _USERS[user_id] = _default_profile(tg_user)

    profile = _USERS[user_id]
    return profile["name"], profile["url"]


def _default_profile(tg_user: User) -> dict[str, str]:
    """
    Tumia Telegram info kama default
    """
    name = tg_user.full_name or "Telegram User"

    if tg_user.username:
        url = f"https://t.me/{tg_user.username}"
    else:
        url = "https://t.me/telegram"

    return {
        "name": name,
        "url": url,
    }


# ====== BAADAYE ======
def set_author_name(user_id: int, name: str):
    if user_id in _USERS:
        _USERS[user_id]["name"] = name


def set_author_url(user_id: int, url: str):
    if user_id in _USERS:
        _USERS[user_id]["url"] = url
