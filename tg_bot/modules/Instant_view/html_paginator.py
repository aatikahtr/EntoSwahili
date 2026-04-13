from bs4 import BeautifulSoup

MAX_PAGE_SIZE = 38000


def paginate_html(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")

    pages: list[str] = []
    current_parts: list[str] = []
    current_len = 0

    for el in soup.contents:
        part = str(el)
        part_len = len(part)

        # Kama block moja ni kubwa sana, bado iruhusu peke yake
        if part_len > MAX_PAGE_SIZE:
            if current_parts:
                pages.append("".join(current_parts))
                current_parts = []
                current_len = 0
            pages.append(part)
            continue

        if current_len + part_len > MAX_PAGE_SIZE:
            pages.append("".join(current_parts))
            current_parts = [part]
            current_len = part_len
        else:
            current_parts.append(part)
            current_len += part_len

    if current_parts:
        pages.append("".join(current_parts))

    return pages
