'''
engine kuu ya kusafisha na kubadilisha HTML ili iwe compatible na Telegraph au mfumo mwingine wa article formatting.
Kazi kuu ya function hii:
Inafanya:
1. Kusoma kila node moja moja
Text
Links
Images
Paragraphs
Lists
Tables
2. Kuondoa vitu visivyohitajika:
<script>
<style>
comments
ads
noise text
empty nodes


'''

import re

from bs4 import (
    BeautifulSoup,
    NavigableString,
    Tag,
    Comment,
)

from urllib.parse import urljoin

from .table_converter import convert_table_to_telegraph
from constants import (
    NOISE_TEXTS,
    SKIP_TAGS,
    TAG_MAP,
    INLINE_TAGS,
    ALLOWED_TAGS,
    TABLE_TAGS,
    BLOCK_TAGS,
)




def is_noise_text(text: str) -> bool:
    """Angalia kama text ni noise/boilerplate."""
    cleaned = text.strip().lower()
    if not cleaned:
        return True
    if cleaned in NOISE_TEXTS:
        return True
    # Fupi sana na haina maana
    if len(cleaned) < 3:
        return True
    return False



def get_node_text(node) -> str:
    """Pata text yote kutoka node bila tags."""
    if isinstance(node, NavigableString):
        return str(node)
    return node.get_text(separator=" ", strip=True)



def process_node(node, base_url: str, soup: BeautifulSoup) -> list:
    """
    Traverse DOM node kwa node, isafishe na irudishe list ya
    nodes zilizosafishwa tayari kwa Telegraph.

    Strategy:
    - NavigableString  → rudisha text node moja kwa moja (baada ya kusafisha)
    - Comment          → skip kabisa
    - SKIP_TAGS        → skip tag na watoto wake wote
    - img              → normalize src, rudisha tag
    - a                → normalize href, process watoto wake recursively
    - INLINE_TAGS      → map jina, process watoto recursively
    - BLOCK_TAGS       → wrap content ya watoto katika tag inayofaa
    - Kingine chochote → unwrap: process watoto tu bila tag
    """

    # 1. Comment nodes — ziache kabisa
    if isinstance(node, Comment):
        return []

    # 2. Text nodes (NavigableString)
    if isinstance(node, NavigableString):
        text = str(node)
        # Safisha whitespace nyingi lakini hifadhi newlines muhimu
        text = re.sub(r'[^\S\n]+', ' ', text)
        if is_noise_text(text):
            return []
        return [NavigableString(text)]

    # Kutoka hapa node ni Tag
    if not isinstance(node, Tag):
        return []

    tag_name = node.name.lower() if node.name else ""

    # 3. Tags za hatari — skip kabisa pamoja na watoto
    if tag_name in SKIP_TAGS:
        return []

    # 4. Angalia kama node nzima ni noise kwa text yake
    node_text = get_node_text(node).strip().lower()
    if node_text in NOISE_TEXTS:
        return []

    # 5. Map tag kwenda Telegraph-compatible tag
    mapped_tag = TAG_MAP.get(tag_name, tag_name)

    # 6. Img — special handling
    if tag_name == "img":
        src = node.get("src", "").strip()
        if not src:
            return []
        full_src = urljoin(base_url, src)
        new_img = soup.new_tag("img", src=full_src)
        # Alt text kama ipo
        alt = node.get("alt", "").strip()
        if alt:
            new_img["alt"] = alt
        return [new_img]

    # 7. Process watoto recursively
    processed_children = []
    for child in node.children:
        processed_children.extend(process_node(child, base_url, soup))

    # Kama hakuna children zilizobaki baada ya kusafisha, rudisha empty
    if not processed_children:
        return []

    # 8. Anchor tags — normalize href, hifadhi tag
    if tag_name == "a":
        href = node.get("href", "").strip()
        if not href:
            # Link bila href — unwrap tu, rudisha content
            return processed_children
        full_href = urljoin(base_url, href)
        # Skip anchor za ndani ya ukurasa (jump links)
        if full_href.startswith("#"):
            return processed_children
        new_a = soup.new_tag("a", href=full_href)
        for child in processed_children:
            new_a.append(child.__copy__() if hasattr(child, '__copy__') else child)
        return [new_a]

    # 9. Inline tags — wrap watoto katika tag iliyomapwa
    if tag_name in INLINE_TAGS:
        if mapped_tag not in ALLOWED_TAGS:
            # Unwrap — rudisha content bila tag
            return processed_children
        new_tag = soup.new_tag(mapped_tag)
        for child in processed_children:
            new_tag.append(child)
        return [new_tag]

    # 10. Table tags — special conversion
    if tag_name == "table":
        return convert_table_to_telegraph(node, base_url, soup)

    if tag_name in TABLE_TAGS:
        # thead/tbody/tr/td/th zinafika hapa tu kama ziko nje ya <table>
        # (hali nadra) — unwrap tu
        return processed_children

    # 11. Block tags — jenga tag mpya na watoto waliiosafishwa
    if tag_name in BLOCK_TAGS:
        # Determine final tag kwa Telegraph
        if mapped_tag in ALLOWED_TAGS:
            final_tag = mapped_tag
        elif tag_name in {"ul", "ol", "li"}:
            final_tag = tag_name  # hizi zinaruhusiwa moja kwa moja
        elif tag_name in {"figure", "figcaption"}:
            final_tag = "p"
        else:
            # Unwrap — content peke yake
            return processed_children

        new_tag = soup.new_tag(final_tag)
        for child in processed_children:
            new_tag.append(child)

        # Safisha: kama p/h3/h4 ina text tupu ya noise — skip
        inner_text = new_tag.get_text(strip=True).lower()
        if inner_text in NOISE_TEXTS or not inner_text:
            return []

        return [new_tag]

    # 12. Chochote kingine — unwrap, rudisha watoto tu
    return processed_children




