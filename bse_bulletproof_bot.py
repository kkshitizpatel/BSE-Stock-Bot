import datetime
import os
from flask import Flask
import threading
import time
import requests

# ----------------- CONFIGURATION -----------------
# Ab Token aur ID yahan hardcode nahi karenge, server ke environment se uthayenge
TELEGRAM_BOT_TOKEN = os.environ.get("8670885960:AAGF_3ByQ8VJ4IzRnay8VW1TUG5PiNW703I", "LOCAL_TEST_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("7587873393","LOCAL_CHAT_ID")
ALLOWED_USERNAME = "Xitiz92"

# 8 Category Catalyst Keywords
KEYWORDS = [
    # 1. Results
    "pat up", "profit surges", "q1 profit", "revenue jumps", "multi-fold", 
    "financial results", "profit up",
    # 2. Orders & Contracts
    "bags order", "emerges l1 bidder", "signs mou", "wins contract", 
    "order", "bags", "contract", "l1 bidder", "mou", "work order",
    # 3. Buying (Bulk/Block & Institutional)
    "bulk deal", "block deal", "fii buys", "fund buys stake", 
    "fii", "stake", "preferential issue", "qip", "allotment of equity",
    # 4. Corporate Actions
    "board approves bonus", "stock split", "special dividend", 
    "bonus", "sub-division", "buyback",
    # 5. M&A
    "acquires", "merger approved", "takes over", 
    "acquisition", "merger", "takeover", "amalgamation",
    # 6. Approvals & Regulatory
    "fda approval", "receives nod", "environmental clearance", "eir report", 
    "fda", "usfda", "approval", "clearance", "nod", "eir",
    # 7. Sarkari Policy
    "pli scheme", "cabinet approves", "subsidy", "anti-dumping duty", "anti-dumping"
]

# In-memory storage & locks
night_news_queue = []
recent_catalysts = []  # /check command ke liye pichle 10 triggers
last_update_id = 0
lock = threading.Lock()

# ----------------- PERSISTENCE HELPERS -----------------
def load_seen_ids():
    """Bot restart hone par purane IDs load karta hai taaki repeat na ho"""
    if not os.path.exists(SEEN_IDS_FILE):
        return set()
    with open(SEEN_IDS_FILE, "r") as f:
        return set(line.strip() for line in f if line.strip())

def mark_id_as_seen(news_id):
    """Naye news ID ko permanent file mein save karta hai"""
    with open(SEEN_IDS_FILE, "a") as f:
        f.write(f"{news_id}\n")

seen_news_ids = load_seen_ids()

# ----------------- TIMEZONE HELPER -----------------
def get_ist_time():
    """Server chahe kahin bhi ho, exact Indian Standard Time nikalta hai"""
    ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    return datetime.datetime.now(ist)

def is_night_time():
    """10:00 PM (22:00) se 8:00 AM IST check karta hai"""
    current_hour = get_ist_time().hour
    return current_hour >= 22 or current_hour < 8

# ----------------- TELEGRAM HELPERS -----------------
def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def format_alert_card(item):
    card = (
        f"🚨 <b>BSE Catalyst Alert</b>\n"
        f"🏢 <b>Company:</b> {item['company']}\n"
        f"📂 <b>Category:</b> {item['category']}\n"
        f"⏰ <b>Time:</b> {item['time_str']}\n\n"
        f"📝 <b>Headline:</b>\n{item['headline']}\n"
    )
    if item.get("pdf_link"):
        card += f"📄 <a href='{item['pdf_link']}'>Exchange Filing PDF</a>\n"
    return card

def flush_night_queue():
    """Subah 8 AM hote hi raat ki saari news bhej deta hai"""
    global night_news_queue
    with lock:
        if not night_news_queue:
            return
        items_to_send = list(night_news_queue)
        night_news_queue.clear()

    send_telegram_message(
        TELEGRAM_CHAT_ID, 
        f"🌅 <b>Good Morning @{ALLOWED_USERNAME}!</b>\n"
        f"Raat (10 PM - 8 AM) ke dauran aayi <b>{len(items_to_send)}</b> matching announcements:"
    )

    for item in items_to_send:
        send_telegram_message(TELEGRAM_CHAT_ID, format_alert_card(item))
        time.sleep(0.5)

# ----------------- BSE SCANNER -----------------
def scan_bse():
    global seen_news_ids, night_news_queue, recent_catalysts

    api_url = "https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w?pageno=1&strCat=-1&strPrevDate=&strScrip=&strSearch=P&strToDate=&strType=C"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://www.bseindia.com/",
        "Accept": "application/json, text/plain, */*",
    }

    try:
        response = requests.get(api_url, headers=headers, timeout=10)
        if response.status_code != 200:
            return

        announcements = response.json().get("Table", [])
        new_matches = []

        for item in announcements:
            news_id = str(item.get("NEWSID", ""))
            headline = item.get("NEWSSUB", "")
            company = item.get("SLONGNAME", "Unknown")
            category = item.get("CATEGORYNAME", "General")
            time_str = item.get("NEWS_DT", "")
            attachment = item.get("ATTACHMENTNAME", "")

            if not news_id or news_id in seen_news_ids:
                continue

            headline_lower = headline.lower()
            if any(k in headline_lower for k in KEYWORDS):
                seen_news_ids.add(news_id)
                mark_id_as_seen(news_id)

                pdf_link = f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{attachment}" if attachment else ""
                
                alert_obj = {
                    "news_id": news_id,
                    "company": company,
                    "headline": headline,
                    "category": category,
                    "time_str": time_str,
                    "pdf_link": pdf_link
                }
                new_matches.append(alert_obj)

                # Recent list mein add karein (max 10)
                recent_catalysts.insert(0, alert_obj)
                if len(recent_catalysts) > 10:
                    recent_catalysts.pop()

        # Alert Routing
        if is_night_time():
            with lock:
                night_news_queue.extend(new_matches)
        else:
            # Subah 8 AM hote hi pehle raat ka backlog clear karo
            if night_news_queue:
                flush_night_queue()

            # Din ke real-time alerts
            for match in new_matches:
                send_telegram_message(TELEGRAM_CHAT_ID, format_alert_card(match))
                time.sleep(0.3)

    except Exception as e:
        print(f"Scanner fetch error: {e}")

# ----------------- COMMAND HANDLER -----------------
def handle_user_command(chat_id, text):
    """Jab user manually command deta hai"""
    if text in ["/start", "/help"]:
        send_telegram_message(
            chat_id,
            f"👋 Hello <b>@{ALLOWED_USERNAME}</b>!\n\n"
            "• <b>Live Alerts:</b> 8:00 AM se 10:00 PM IST tak real-time aayenge.\n"
            "• <b>Night Mode:</b> 10:00 PM se 8:00 AM IST silent rahega (8 AM ko digest aayega).\n"
            "• <b>On-Demand:</b> Kisi bhi waqt <code>/check</code> bhejein."
        )
    elif text == "/check":
        send_telegram_message(chat_id, "🔍 <i>Checking latest triggers...</i>")
        scan_bse()  # Ek instant check run karein

        if is_night_time() and night_news_queue:
            send_telegram_message(chat_id, f"🌙 <b>Night Mode Active:</b> Abhi tak queue mein {len(night_news_queue)} announcements hain jo subah 8 AM ko aayengi. Ye rahe latest:")
            for item in night_news_queue[-3:]:
                send_telegram_message(chat_id, format_alert_card(item))
        elif recent_catalysts:
            send_telegram_message(chat_id, f"📋 <b>Pichle {len(recent_catalysts)} matched triggers:</b>")
            for item in recent_catalysts[:5]:
                send_telegram_message(chat_id, format_alert_card(item))
                time.sleep(0.3)
        else:
            send_telegram_message(chat_id, "✅ Filhal koi naya trigger match nahi hua hai.")

def command_listener():
    global last_update_id
    while True:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        params = {"offset": last_update_id + 1, "timeout": 20}
        try:
            resp = requests.get(url, params=params, timeout=25)
            if resp.status_code == 200:
                for update in resp.json().get("result", []):
                    last_update_id = update["update_id"]
                    msg = update.get("message")
                    if not msg:
                        continue

                    sender_username = msg.get("from", {}).get("username", "")
                    chat_id = msg["chat"]["id"]
                    text = msg.get("text", "").strip()

                    # Authorization Check
                    if sender_username != ALLOWED_USERNAME:
                        send_telegram_message(chat_id, "⛔ <b>You are not authorized to use this bot.</b>")
                        continue

                    handle_user_command(chat_id, text)
        except Exception as e:
            print(f"Listener error: {e}")
        time.sleep(1)

def background_loop():
    while True:
        scan_bse()
        time.sleep(45)
# ----------------- KEEP-ALIVE WEB SERVER -----------------
app = Flask(__name__)

@app.route('/')
def home():
    return "🚀 BSE Bot is running 24/7!"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
# ----------------- MAIN RUNNER -----------------
if __name__ == "__main__":
    print(f"🔒 Secure Bot Started for @{ALLOWED_USERNAME}")
    
    t_scan = threading.Thread(target=background_loop, daemon=True)
    t_listen = threading.Thread(target=command_listener, daemon=True)
    t_web = threading.Thread(target=run_web_server, daemon=True)  # Naya thread

    t_scan.start()
    t_listen.start()
    t_web.start()

    while True:
        time.sleep(1)
