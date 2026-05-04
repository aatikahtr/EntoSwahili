async def get_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    original_message = update.message

    # Kagua kama URL imetolewa
    if not context.args:
        await original_message.reply_text("⚠️ Toa URL. Mfano: /get https://example.com")
        return

    url = context.args[0]

    if not is_url(url):
        await original_message.reply_text("⚠️ URL si sahihi. Lazima ianze na http:// au https://")
        return

    try:
        import requests
        from bs4 import BeautifulSoup

        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # Title
        h1 = soup.find("h1")
        title = h1.text.strip() if h1 else "Hakuna title"

        # Paragraphs
        paragraphs = soup.find_all("p")
        lines = []
        for p in paragraphs:
            text = p.text.strip()
            if text:
                lines.append(text)

        content = "\n\n".join(lines)

        if not content:
            await original_message.reply_text("⚠️ Imeshindwa kupata content.")
            return

        # Tuma title na content
        full_text = f"<b>{title}</b>\n\n{content}"

        # Telegram ina limit ya 4096 characters
        if len(full_text) > 4096:
            full_text = full_text[:4090] + "..."

        await original_message.reply_text(full_text, parse_mode="HTML")

    except Exception as e:
        await original_message.reply_text(f"❌ Hitilafu: {e}")
