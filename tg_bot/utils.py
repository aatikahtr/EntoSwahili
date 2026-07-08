import re

"""
utils.py — Zana za msingi zinazo hitajika kati ya files zote.
"""

# -----------------------------------
# BLOCK WORDS
# -----------------------------------
BLOCK_WORDS = {
    "MillardAyoMagazetiTz&Kenya",
    "#Magazetiyaleo",
    "list@rss",
    "Your subscriptions:",
    "@rss2tg_bot",
    "Removed:",
    "⚠️",
    "Added:",
    "latest record:",
}

BLOCK_PREFIXES = (
    "/",
    "/settings@rss",
)


# Fafanua URL_REGEX
URL_REGEX = re.compile(r'https?://[^\s]+')


nitter_tu = {
    -1003925774049,  # X rs 📰
    -1004328806786,  # X rs 👬 rafiki

} 

