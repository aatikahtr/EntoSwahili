async def check_selectors(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = context.args[0] if context.args else "https://www.alhidaaya.com/sw/node/4492"
    url = update.message.reply_to_message
    
    async with httpx.AsyncClient(headers=HEADERS, timeout=30, follow_redirects=True) as client:
        response = await client.get(url)
        soup = BeautifulSoup(response.text, "html.parser")
        
        results = []
        for div in soup.find_all("div", class_=True):
            classes = " ".join(div.get("class", []))
            text = div.get_text().strip()[:50]
            if text:
                results.append(f"• {classes[:50]} → {text[:30]}")
        
        # Tuma matokeo kwa vikundi - Telegram ina limit ya herufi
        chunk = ""
        for line in results[:50]:  # Kwanza 50 tu
            chunk += line + "\n"
            if len(chunk) > 3000:
                await update.message.reply_text(chunk)
                chunk = ""
        
        if chunk:
            await update.message.reply_text(chunk)
