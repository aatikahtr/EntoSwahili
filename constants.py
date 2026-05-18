'''
Vitu vya kudumu kwenye code
Yaani variables ambazo hazibadiliki mara kwa mara.

'''


from telegraph.aio import Telegraph

telegraph = Telegraph(access_token="522e083178bb4d7511cc1784c3f849b9e71164cdac06d08812181c1945dc")


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
    ".sharedaddy",
    ".jp-relatedposts",
    ".sd-sharing",
    "[class*='share']",
    ".wp-block-buttons",
    ".wp-block-button",
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




