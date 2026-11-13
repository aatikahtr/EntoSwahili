"""
sites.py — SHERIA ZA KILA WEBSITE (data tu, hakuna logic).

Kuongeza website mpya = kuongeza mstari mmoja kwenye SITES hapo chini.
Hakuna haja ya kutengeneza file jipya.

Funguo zinazoruhusiwa kwa kila site:
    content   : list ya CSS selectors za mahali makala ilipo (ya kwanza inayofaa inatumika)
    remove    : list ya CSS selectors za vitu vya kufuta ndani ya makala
    stop_at   : maneno — block fupi yenye neno hili inakata makala (kila kitu baada yake kinaondoka)
    drop_text : regex — block yenye maandishi yanayolingana inaondolewa tu (haikati)
    title     : list ya CSS selectors za title (kama og:title/h1 haitoshi)
    images    : False = site hii iwe text tu
"""

from urllib.parse import urlparse

# ──────────────────────────────────────────────────────────────
# 1. SHERIA ZA WEBSITE MAALUM  (domain bila "www.")
# ──────────────────────────────────────────────────────────────
SITES: dict[str, dict] = {
    "trtafrika.com": {
        "content": ["article"],
        "stop_at": ["zilizopendekezwa"],
    },
    "firqatunnajia.com": {
        "content": [".elementor-widget-theme-post-content .elementor-widget-container"],
    },
    "gsmarena.com": {
        "content": ["#specs-list", ".specs-cp-wrapper", ".review-body", "article"],
    },
    # Mfano wa kuongeza site:
    # "example.co.tz": {
    #     "content": [".post-body"],
    #     "remove": [".mid-article-ad"],
    #     "stop_at": ["makala zinazohusiana"],
    #     "drop_text": [r"^picha:\s"],
    #     "images": False,
    # },
}

# ──────────────────────────────────────────────────────────────
# 2. PLATFORM (CMS) — inatambulika kutoka meta/generator
# ──────────────────────────────────────────────────────────────
PLATFORMS: dict[str, dict] = {
    "blogger": {"content": [".post-body", ".entry-content", "#post-body"]},
    "drupal": {
        "content": [
            ".field-name-body .field-item", ".field-items", ".node__content",
            "#main-content", ".region-content",
        ]
    },
    "medium": {"content": ["article", ".meteredContent"]},
    "substack": {"content": [".body.markup", ".available-content", "article"]},
}

# ──────────────────────────────────────────────────────────────
# 3. SELECTORS ZA KAWAIDA (zinatumika kama hakuna sheria maalum)
#    Elementor ya kwanza — inafaa websites nyingi sana.
# ──────────────────────────────────────────────────────────────
DEFAULT_CONTENT = [
    ".elementor-widget-theme-post-content .elementor-widget-container",
    ".entry-content",
    ".post-content",
    ".article-content",
    ".td-post-content",
    ".single-content",
    ".post-body",
    "[itemprop='articleBody']",
    "article",
    "main",
    "#content",
]

# ──────────────────────────────────────────────────────────────
# 4. VITU VYA KUFUTA KILA MAHALI (share, matangazo, comments, n.k.)
# ──────────────────────────────────────────────────────────────
GLOBAL_REMOVE = [
    # share / social
    ".sharedaddy", ".sd-sharing", ".addtoany_share_save_container", ".a2a_kit",
    ".post-share", ".share-buttons", ".social-share", ".social-links", ".entry-share",
    "[class*='sharing']", "[class*='share-']", "[class*='-share']",
    # related / navigation
    ".jp-relatedposts", ".related-posts", ".related-articles", "[class*='related-']",
    ".post-navigation", ".nav-links", ".breadcrumb", ".breadcrumbs",
    # comments
    "#comments", ".comments-area", ".comment-respond", "#respond",
    # ads / newsletter / buttons
    ".advertisement", ".adsbygoogle", "[class*='advert']", "[id*='google_ads']",
    "[class*='newsletter']", ".wp-block-buttons", ".wp-block-button",
    # meta
    ".entry-meta", ".post-meta", ".post-tags", ".tags-links", ".author-box",
    # elementor
    ".elementor-widget-share-buttons", ".elementor-widget-post-navigation",
]

# Block fupi (≤ 80 herufi) yenye maneno haya inakata makala
GLOBAL_STOP = (
    "bonyeza", "soma zaidi", "endelea kusoma", "read more", "continue reading",
    "zilizopendekezwa", "makala zinazohusiana", "related posts",
    "related articles", "you may also like",
)

# Maandishi yanayokuwa noise (block nzima ikiwa hivi inaondolewa)
NOISE_TEXTS = {
    "table of contents", "share", "tweet", "facebook", "twitter", "whatsapp",
    "telegram", "pinterest", "linkedin", "print", "email", "shiriki",
    "sign in with google to post a comment", "no comments yet. be the first!",
    "write a comment", "post comment", "advertisement", "matangazo",
}

MIN_ROOT_CHARS = 200  # selector inakubalika kama ina maandishi angalau haya


def _host(url: str) -> str:
    host = urlparse(url).netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def detect_platform(soup) -> str | None:
    gen = soup.find("meta", attrs={"name": "generator"})
    gen = (gen.get("content", "") if gen else "").lower()
    for name in PLATFORMS:
        if name in gen:
            return name
    return None


def get_rules(url: str, soup) -> dict:
    """Unganisha: sheria za site + platform + defaults → dict moja kamili."""
    host = _host(url)
    site = {}
    for domain, rules in SITES.items():
        if host == domain or host.endswith("." + domain):
            site = rules
            break

    platform = PLATFORMS.get(detect_platform(soup) or "", {})

    return {
        "content": list(site.get("content", []))
        + platform.get("content", [])
        + DEFAULT_CONTENT,
        "remove": GLOBAL_REMOVE + list(site.get("remove", [])),
        "stop_at": tuple(GLOBAL_STOP) + tuple(w.lower() for w in site.get("stop_at", [])),
        "drop_text": list(site.get("drop_text", [])),
        "title": list(site.get("title", [])),
        "images": site.get("images", True),
    }
