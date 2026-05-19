"""
Platform handler — chanzo kimoja cha platform logic yote.
Files zote zinazohitaji platform detection/selectors/cleanup zinaita hapa.
"""

from bs4 import BeautifulSoup


# ── Selectors ─────────────────────────────────────────────────────────────────

PLATFORM_SELECTORS: dict[str, list[str]] = {
    "trtafrika": [
        "article",
    ],
    "firqatunnajia": [
        ".elementor-widget-theme-post-content .elementor-widget-container",
    ],
    "gsmarena": [
        "#specs-list",
        ".specs-cp-wrapper",
        ".review-body",
        "article",
    ],
    "wordpress": [
        ".entry-content",
        ".post-content",
        "article .content",
        "article",
    ],
    "blogger": [
        ".post-body",
        ".entry-content",
        "#post-body",
        "article",
    ],
    "drupal": [
        ".field-name-body .field-item",
        ".field-items",
        ".field-item",
        ".node__content",
        "#main-content",
        ".region-content",
    ],
    "medium": [
        "article",
        ".meteredContent",
        "section",
    ],
    "substack": [
        ".body.markup",
        ".available-content",
        "article",
    ],
    "generic": [
        "article",
        ".entry-content",
        ".post-content",
        ".article-content",
        "main article",
        ".single-content",
        "#content article",
        ".content-area article",
        ".site-content article",
        "main",
    ],
}


# ── Platform detection ─────────────────────────────────────────────────────────

def detect_platform(url: str, soup: BeautifulSoup) -> str:
    """Gundua platform kutoka URL na meta tags."""
    if "trtafrika.com" in url:
        return "trtafrika"
    if "firqatunnajia.com" in url:
        return "firqatunnajia"
    if "gsmarena.com" in url:
        return "gsmarena"
    if "medium.com" in url:
        return "medium"
    if "substack.com" in url:
        return "substack"

    generator = soup.find("meta", attrs={"name": "generator"})
    gen_content = (generator.get("content", "") if generator else "").lower()

    if "wordpress" in gen_content or "elementor" in gen_content:
        return "wordpress"
    if soup.find("link", attrs={"rel": "https://api.w.org/"}):
        return "wordpress"
    if "blogger" in gen_content:
        return "blogger"
    if "drupal" in gen_content:
        return "drupal"

    return "generic"


def get_selectors(platform: str) -> list[str]:
    """Rudisha selectors kulingana na platform."""
    return PLATFORM_SELECTORS.get(platform, PLATFORM_SELECTORS["generic"])


def find_content(soup: BeautifulSoup, selectors: list[str]):
    """Tafuta element ya kwanza inayopatikana kutoka selectors."""
    for selector in selectors:
        el = soup.select_one(selector)
        if el:
            return el
    return soup.find("body")


# ── Platform-specific cleanup ──────────────────────────────────────────────────

def remove_trtafrika_recommended(article_el) -> None:
    """
    Futa sehemu ya 'ZILIZOPENDEKEZWA' ndani ya article ya TRT Afrika.
    Inatambuliwa kwa kutafuta text 'ZILIZOPENDEKEZWA' ndani ya article,
    kisha inafuta mzazi wake wa karibu wa block-level wenye links nyingi.
    """
    for tag in article_el.find_all(string=lambda t: t and "ZILIZOPENDEKEZWA" in t.upper()):
        parent = tag.parent
        while parent and parent != article_el:
            if parent.name in {"div", "section", "aside", "ul", "ol"}:
                links = parent.find_all("a")
                if len(links) >= 2:
                    parent.decompose()
                    break
            parent = parent.parent


def remove_trtafrika_soma_zaidi(article_el) -> None:
    """
    Futa sehemu ya 'Soma zaidi' ndani ya article ya TRT Afrika.
    Inatambuliwa kwa text 'Soma zaidi', kisha inafuta container yake
    pamoja na kila kitu kinachofuata baada yake.
    """
    for tag in article_el.find_all(string=lambda t: t and "soma zaidi" in t.lower()):
        parent = tag.parent
        while parent and parent != article_el:
            if parent.name in {"div", "section", "aside", "ul", "ol", "h2", "h3", "h4"}:
                # Futa siblings zote zinazofuata
                for sibling in list(parent.find_next_siblings()):
                    sibling.decompose()
                # Futa container yenyewe
                parent.decompose()
                break
            parent = parent.parent


def cleanup_platform(platform: str, content_el) -> None:
    """
    Fanya cleanup maalum kulingana na platform.
    Ongeza platform mpya hapa tu — files zingine hazihitaji mabadiliko.
    """
    if platform == "trtafrika":
        remove_trtafrika_recommended(content_el)
        remove_trtafrika_soma_zaidi(content_el)
