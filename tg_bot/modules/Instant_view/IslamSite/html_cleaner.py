'''
kusafisha HTML — yaani kuondoa vitu visivyohitajika kwenye code ya HTML kama:
tags zisizo muhimu
scripts
matangazo
styles zisizohitajika
formatting chafu
'''

# Standard library
import re

# Third-party
from bs4 import BeautifulSoup

# Local modules
from .clean_node import process_node
from .constants import UNWANTED_SELECTORS


def remove_recommended_links(soup: BeautifulSoup) -> None:
    """
    Futa links za 'ZILIZOPENDEKEZWA' / related articles.
    Zinatambuliwa kwa utm_campaign=recommended kwenye href.
    Inafuta tag nzima ya <a> pamoja na mzazi wake kama mzazi
    ana link moja tu (yaani ni wrapper tu).
    """
    for a_tag in soup.find_all("a", href=True):
        href = a_tag.get("href", "")
        if "utm_campaign=recommended" in href:
            parent = a_tag.parent
            # Kama mzazi ana watoto wengine zaidi ya link hii — futa link tu
            siblings = [s for s in parent.children if str(s).strip()]
            if len(siblings) <= 1:
                parent.decompose()
            else:
                a_tag.decompose()


def clean_html(html: str, base_url: str) -> str:
    html = re.sub(r'<\?xml[^>]*\?>', '', html)
    html = re.sub(r'<xml[^>]*>.*?</xml>', '', html, flags=re.DOTALL)

    soup = BeautifulSoup(html, "lxml")

    # Futa recommended/related article links kwanza
    remove_recommended_links(soup)

    # Futa sections zisizohitajika
    for selector in UNWANTED_SELECTORS:
        for tag in soup.select(selector):
            tag.decompose()

    # Pata body au soup nzima
    body = soup.find("body") or soup

    # Tumia process_node() kwenye kila child wa body
    result_nodes = []
    for child in list(body.children):
        result_nodes.extend(process_node(child, base_url, soup))

    # Jenga HTML mpya kutoka nodes zilizosafishwa
    result_soup = BeautifulSoup("", "lxml")
    wrapper = result_soup.new_tag("div")
    for node in result_nodes:
        wrapper.append(node)

    return wrapper.decode_contents()
