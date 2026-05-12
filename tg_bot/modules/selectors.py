import httpx
from telegram import Update
from telegram.ext import ContextTypes
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "sw-TZ,sw;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.google.com/",
    "Cache-Control": "no-cache",
}

def is_url(text: str) -> bool:
    return text.startswith("http://") or text.startswith("https://")


def detect_platform(soup: BeautifulSoup, response_headers: dict, html: str) -> dict:
    """Tambua aina ya platform/CMS kutoka HTML na headers."""
    result = {
        "platform": "Haijulikani",
        "evidence": []
    }

    # 1. Meta generator tag (njia rahisi zaidi)
    generator = soup.find("meta", attrs={"name": "generator"})
    if generator:
        content = generator.get("content", "").lower()
        result["evidence"].append(f"Generator: {generator.get('content', '')}")
        if "wordpress" in content:
            result["platform"] = "WordPress"
            return result
        elif "joomla" in content:
            result["platform"] = "Joomla"
            return result
        elif "drupal" in content:
            result["platform"] = "Drupal"
            return result
        elif "wix" in content:
            result["platform"] = "Wix"
            return result
        elif "squarespace" in content:
            result["platform"] = "Squarespace"
            return result
        elif "ghost" in content:
            result["platform"] = "Ghost"
            return result
        elif "blogger" in content or "blogspot" in content:
            result["platform"] = "Blogger"
            return result

    # 2. HTML class/id signatures
    wp_signs = [
        soup.find(id="wpadminbar"),
        soup.find(class_="wp-block"),
        soup.select_one("link[href*='wp-content']"),
        soup.select_one("script[src*='wp-content']"),
        soup.select_one("script[src*='wp-includes']"),
    ]
    if any(wp_signs):
        result["platform"] = "WordPress"
        result["evidence"].append("wp-content/wp-includes found in source")
        return result

    # WordPress path kwenye HTML raw
    if "wp-content" in html or "wp-includes" in html:
        result["platform"] = "WordPress"
        result["evidence"].append("wp-content found in HTML")
        return result

    # Drupal
    if soup.find(attrs={"data-drupal-selector": True}) or "Drupal.settings" in html:
        result["platform"] = "Drupal"
        result["evidence"].append("Drupal markers found")
        return result

    # Ghost
    if soup.select_one("meta[name='generator'][content*='Ghost']") or "ghost.io" in html:
        result["platform"] = "Ghost"
        result["evidence"].append("Ghost markers found")
        return result

    # Wix
    if "static.wixstatic.com" in html or "_wix" in html:
        result["platform"] = "Wix"
        result["evidence"].append("Wix static assets found")
        return result

    # Squarespace
    if "squarespace.com" in html or "squarespace-cdn" in html:
        result["platform"] = "Squarespace"
        result["evidence"].append("Squarespace CDN found")
        return result

    # Shopify
    if "cdn.shopify.com" in html or "Shopify.theme" in html:
        result["platform"] = "Shopify"
        result["evidence"].append("Shopify CDN found")
        return result

    # Webflow
    if "webflow.com" in html or soup.find(attrs={"data-wf-page": True}):
        result["platform"] = "Webflow"
        result["evidence"].append("Webflow markers found")
        return result

    # Blogger/Blogspot
    if "blogger.com" in html or "blogspot.com" in html:
        result["platform"] = "Blogger"
        result["evidence"].append("Blogger markers found")
        return result

    # 3. HTTP Headers
    x_powered = response_headers.get("x-powered-by", "").lower()
    server = response_headers.get("server", "").lower()

    if "php" in x_powered:
        result["evidence"].append(f"X-Powered-By: {response_headers.get('x-powered-by')}")
    if server:
        result["evidence"].append(f"Server: {response_headers.get('server')}")

    # 4. Detect kama ni blog kwa muundo
    blog_signs = 0
    if soup.find("article"):
        blog_signs += 1
        result["evidence"].append("HTML <article> tags found")
    if soup.select(".post, .blog-post, .entry, .hentry"):
        blog_signs += 1
        result["evidence"].append("Blog post CSS classes found")
    if soup.select("time[datetime]"):
        blog_signs += 1
        result["evidence"].append("Datetime timestamps found")
    if soup.find("a", rel=lambda r: r and "tag" in r):
        blog_signs += 1
        result["evidence"].append("Tag/category links found")

    if blog_signs >= 2:
        result["platform"] = "Blog/CMS (aina haijulikani)"

    return result


async def check_selectors(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("sawa")

    if context.args:
        url = context.args[0]
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        url = update.message.reply_to_message.text.strip()
    else:
        url = "https://www.alhidaaya.com/sw/node/4492"

    if not is_url(url):
        await update.message.reply_text("⚠️ URL si sahihi.")
        return

    async with httpx.AsyncClient(headers=HEADERS, timeout=30, follow_redirects=True) as client:
        response = await client.get(url)
        html = response.text
        soup = BeautifulSoup(html, "html.parser")

        # Tambua platform
        platform_info = detect_platform(soup, dict(response.headers), html)

        # Jenga ujumbe
        msg = f"🌐 *URL:* {url}\n"
        msg += f"📦 *Platform:* `{platform_info['platform']}`\n"

        if platform_info["evidence"]:
            msg += "\n🔍 *Ushahidi:*\n"
            for e in platform_info["evidence"]:
                msg += f"  • {e}\n"

        await update.message.reply_text(msg, parse_mode="Markdown")

        # Pia tuma div classes kama kawaida (optional - unaweza kuondoa)
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
