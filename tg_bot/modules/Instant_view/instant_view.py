import os
from telegraph.aio import Telegraph

from .services.users import get_user_profile
from html_paginator import paginate_html

ACCESS_TOKEN = os.getenv("INSTANT_TOKEN")
telegraph = Telegraph(access_token=ACCESS_TOKEN)

MAX_TITLE_LENGTH = 64


async def create_instant_view(
    title: str,
    html: str,
    tg_user,
) -> str:
    """
    Hutengeneza Telegraph Instant View
    - Ikiwa content ni fupi → page moja
    - Ikiwa ndefu → multi-page na Next / Previous
    """

    author_name, author_url = get_user_profile(tg_user)
    short_title = title[:MAX_TITLE_LENGTH]

    pages = paginate_html(html)

    # =====================
    # SINGLE PAGE
    # =====================
    if len(pages) == 1:
        response = await telegraph.create_page(
            title=short_title,
            html_content=pages[0],
            author_name=author_name,
            author_url=author_url,
        )

        path = response["path"]

        # Rekebisha title kamili
        await telegraph.edit_page(
            path=path,
            title=title,
            html_content=pages[0],
            author_name=author_name,
            author_url=author_url,
        )

        return f"https://telegra.ph/{path}"

    # =====================
    # MULTI PAGE
    # =====================
    paths: list[str] = []

    # Hatua ya 1: tengeneza pages
    for i, content in enumerate(pages):
        nav_top = ""
        if i > 0:
            nav_top = (
                f'<p><a href="https://telegra.ph/{paths[i-1]}">'
                f'⬅️ Previous page</a></p>'
            )

        response = await telegraph.create_page(
            title=short_title if i == 0 else f"{short_title} (Page {i+1})",
            html_content=nav_top + content,
            author_name=author_name,
            author_url=author_url,
        )

        paths.append(response["path"])

    # Hatua ya 2: rekebisha navigation (Next / Previous)
    for i, path in enumerate(paths):
        nav = ""

        if i > 0:
            nav += (
                f'<p><a href="https://telegra.ph/{paths[i-1]}">'
                f'⬅️ Previous page</a></p>'
            )

        if i < len(paths) - 1:
            nav += (
                f'<p><a href="https://telegra.ph/{paths[i+1]}">'
                f'➡️ Next page</a></p>'
            )

        await telegraph.edit_page(
            path=path,
            title=title if i == 0 else f"{title} (Page {i+1})",
            html_content=nav + pages[i],
            author_name=author_name,
            author_url=author_url,
        )

    return f"https://telegra.ph/{paths[0]}"
