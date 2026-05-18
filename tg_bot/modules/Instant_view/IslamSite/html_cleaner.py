'''


'''


def clean_html(html: str, base_url: str) -> str:
    html = re.sub(r'<\?xml[^>]*\?>', '', html)
    html = re.sub(r'<xml[^>]*>.*?</xml>', '', html, flags=re.DOTALL)

    soup = BeautifulSoup(html, "lxml")

    # Futa sections zisizohitajika kwanza
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

