async def get_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    original_message = update.message

    if not context.args:
        await original_message.reply_text(
            "⚠️ Toa URL 🔗. Mfano: /get https://example.com"
        )
        return

    url = context.args[0]

    if not is_url(url):
        await original_message.reply_text(
            "⚠️ URL si sahihi. Lazima ianze na http:// au https://"
        )
        return

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)

            page = await browser.new_page(
                user_agent="Mozilla/5.0"
            )

            await page.goto(
                url,
                wait_until="networkidle",
                timeout=60000
            )

            # Title
            h1 = await page.query_selector("h1")
            title = (
                (await h1.inner_text()).strip()
                if h1 else "Habari"
            )

            # Tafuta main content container
            content_selectors = [
                "article",
                ".entry-content",
                ".post-content",
                ".article-content",
                "main article",
                ".single-content",
                "#content article",
                ".content-area article",
                ".site-content article",
            ]

            content_el = None
            for selector in content_selectors:
                el = await page.query_selector(selector)
                if el:
                    content_el = el
                    break

            # Fallback kwa body kama hakuna selector inayofanya kazi
            if not content_el:
                content_el = await page.query_selector("body")

            if not content_el:
                await browser.close()
                await original_message.reply_text(
                    "⚠️ Imeshindwa kupata content."
                )
                return

            body_html = await content_el.inner_html()

            await browser.close()

        # Safisha content
        html_content = clean_html(
            body_html,
            base_url=url
        )

        if not html_content.strip():
            await original_message.reply_text(
                "⚠️ Imeshindwa kupata content."
            )
            return

        # Telegraph size limit
        if len(html_content.encode("utf-8")) > 64000:
            html_content = html_content[:60000] + "<p>... (imekatwa)</p>"

        # Create Telegraph page
        page_data = await telegraph.create_page(
            title=title,
            html_content=html_content,
        )

        telegraph_url = f"https://telegra.ph/{page_data['path']}"

        await original_message.reply_text(
            f"📄 <b>{title}</b>\n\n"
            f"🔗 <a href='{telegraph_url}'>Soma hapa (Instant View)</a>",
            parse_mode="HTML",
            disable_web_page_preview=False,
        )

    except Exception as e:
        await original_message.reply_text(
            f"❌ Hitilafu: {e}"
        )
