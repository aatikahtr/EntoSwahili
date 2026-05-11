import httpx                          
from telegram import Update           
from telegram.ext import ContextTypes 
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

def is_url(text: str) -> bool:
    return text.startswith("http://") or text.startswith("https://")
    


async def check_selectors(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("sawa")
    
    # Njia 1 - URL kwenye command: /check https://example.com
    if context.args:
        url = context.args[0]
    
    # Njia 2 - Reply kwenye ujumbe wenye URL
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        url = update.message.reply_to_message.text.strip()
    
    # Njia 3 - URL ya default
    else:
        url = "https://www.alhidaaya.com/sw/node/4492"
    
    if not is_url(url):
        await update.message.reply_text("⚠️ URL si sahihi.")
        return

    async with httpx.AsyncClient(headers=HEADERS, timeout=30, follow_redirects=True) as client:
        response = await client.get(url)
        soup = BeautifulSoup(response.text, "html.parser")
        
        results = []
        for div in soup.find_all("div", class_=True):
            classes = " ".join(div.get("class", []))
            text = div.get_text().strip()[:50]
            if text:
                results.append(f"• {classes[:50]} → {text[:30]}")
        
        chunk = ""
        for line in results[:50]:
            chunk += line + "\n"
            if len(chunk) > 3000:
                await update.message.reply_text(chunk)
                chunk = ""
        
        if chunk:
            await update.message.reply_text(chunk)
