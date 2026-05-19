'''
Vitu vya kudumu kwenye code
Yaani variables ambazo hazibadiliki mara kwa mara.

'''


from telegraph.aio import Telegraph

telegraph = Telegraph(access_token="522e083178bb4d7511cc1784c3f849b9e71164cdac06d08812181c1945dc")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}



NOISE_TEXTS = {
    "table of contents",
    "sign in with google to post a comment",
    "no comments yet. be the first!",
    "write a comment",
    "post comment",
}

ALLOWED_TAGS = {
    "p", "a", "b", "i", "u", "s",
    "h3", "h4", "br", "ul", "ol", "li",
    "blockquote", "pre", "code", "img"
}

UNWANTED_SELECTORS = [
    # ── WordPress ──────────────────────────────────────────
    ".sharedaddy",
    ".jp-relatedposts",
    ".sd-sharing",
    ".wp-block-buttons",
    ".wp-block-button",
    ".wp-block-separator",
    ".wp-caption-text",

    # ── Kushiriki / Share buttons ──────────────────────────
    "[class*='share']",
    "[class*='sharing']",
    "[id*='share']",
    "[class*='social']",
    "[class*='follow']",

    # ── Matangazo / Ads ────────────────────────────────────
    "[class*='advert']",
    "[class*='advertisement']",
    "[class*='ads-']",
    "[id*='advert']",
    "[class*='banner']",
    "[class*='sponsored']",
    ".ad",
    ".ads",

    # ── Related / Recommended articles ────────────────────
    "[class*='related']",
    "[class*='recommended']",
    "[class*='suggestion']",
    "[class*='more-stories']",
    "[class*='more-articles']",
    "[class*='read-more']",
    "[class*='also-read']",
    "[id*='related']",

    # ── Comments ───────────────────────────────────────────
    "[class*='comment']",
    "[id*='comment']",
    "#disqus_thread",
    ".disqus",

    # ── Newsletter / Subscribe ─────────────────────────────
    "[class*='newsletter']",
    "[class*='subscribe']",
    "[class*='signup']",
    "[class*='sign-up']",

    # ── Navigation / Menu ──────────────────────────────────
    "[class*='breadcrumb']",
    "[class*='pagination']",
    "[class*='sidebar']",
    "[class*='widget']",
    "[class*='menu']",
    "[role='navigation']",

    # ── Author / Tags / Category boxes ────────────────────
    "[class*='author-box']",
    "[class*='author-bio']",
    "[class*='post-tags']",
    "[class*='article-tags']",
    "[class*='tag-list']",
    "[class*='category-label']",

    # ── Footer ya makala ───────────────────────────────────
    "[class*='article-footer']",
    "[class*='post-footer']",
    "[class*='entry-footer']",
    "[class*='story-footer']",

    # ── Popup / Modal / Cookie notice ─────────────────────
    "[class*='popup']",
    "[class*='modal']",
    "[class*='cookie']",
    "[class*='gdpr']",
    "[class*='consent']",

    # ── Misc noise ─────────────────────────────────────────
    "[class*='print']",
    "[class*='feedback']",
    "[class*='survey']",
    "[class*='promo']",
    "noscript",
]

BLOCK_TAGS = {
    "p", "div", "section", "article", "aside",
    "header", "footer", "main", "nav",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li", "blockquote", "pre",
    "figure", "figcaption",
}

# Table tags — zinashughulikiwa kabla ya BLOCK_TAGS
TABLE_TAGS = {"table", "thead", "tbody", "tfoot", "tr", "td", "th", "colgroup", "col"}

INLINE_TAGS = {
    "a", "b", "i", "u", "s", "strong", "em",
    "span", "code", "abbr", "mark",
}

SKIP_TAGS = {
    "script", "style", "nav", "footer", "aside",
    "form", "button", "input", "svg", "meta", "link",
    "head", "noscript", "iframe", "header",
    "picture", "source", "video", "audio",
    "select", "textarea", "label", "fieldset",
}

TAG_MAP = {
    "strong": "b",
    "em": "i",
    "h1": "h3",
    "h2": "h3",
    "h5": "h4",
    "h6": "h4",
}
