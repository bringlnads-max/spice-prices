"""
Spice Price Tracker - Small Cardamom & Black Pepper
====================================================
Collects daily market prices published by the Spices Board of India
(indianspices.com), saves them in data/prices.db and builds dashboard.html.

    python tracker.py                 # daily update (fetches recent days, rebuilds dashboard)
    python tracker.py --backfill 365  # download the last N days of history
    python tracker.py --no-fetch      # only rebuild the dashboard from saved data

Only Python's standard library is used - nothing to install.
"""
import argparse
import datetime as dt
import html
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------- settings ---
# Alert thresholds - change these to make alerts more or less sensitive.
WEEK_MOVE_ALERT_PCT = {"cardamom": 5.0, "pepper_garbled": 3.0, "pepper_ungarbled": 3.0}
LOW_HIGH_WINDOW_DAYS = 90          # "lowest / highest in N days" alerts
HEAVY_ARRIVAL_RATIO = 1.30         # cardamom arrivals 30% above the 30-day average
LIGHT_ARRIVAL_RATIO = 0.70         # cardamom arrivals 30% below the 30-day average
STALE_AFTER_DAYS = 4               # warn if no new data for this many days
DEFAULT_BACKFILL_DAYS = 365        # history downloaded on the very first run

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "data" / "prices.db"
DASHBOARD_PATH = HERE / "site" / "index.html"   # the app page (site/ is what gets published)

CARDAMOM_URL = "https://www.indianspices.com/marketing/price/domestic/daily-price-small.html"
PEPPER_URL = "https://www.indianspices.com/marketing/price/domestic/current-market-price.html"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) SpicePriceTracker/1.0"}

SERIES_NAMES = {
    "cardamom": "Small Cardamom",
    "pepper_garbled": "Black Pepper (Garbled)",
    "pepper_ungarbled": "Black Pepper (Ungarbled)",
}


# ------------------------------------------------------------- downloading ---
def fetch(url, tries=4):
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=90) as resp:
                return resp.read().decode("utf-8", "replace")
        except Exception as exc:  # network hiccups are common on this site
            last = exc
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"Could not download {url}: {last}")


def table_rows(page_html):
    """Every <tr> on the page as a list of plain-text cell values."""
    rows = []
    for tr in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", page_html):
        cells = re.findall(r"(?is)<td[^>]*>(.*?)</td>", tr)
        rows.append([html.unescape(re.sub(r"(?s)<[^>]+>", "", c)).strip() for c in cells])
    return rows


def to_iso(date_text):
    return dt.datetime.strptime(date_text, "%d-%b-%Y").date().isoformat()


def num(text):
    text = (text or "").replace(",", "").strip()
    if text in ("", "-"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


DATE_RE = re.compile(r"^\d{2}-[A-Za-z]{3}-\d{4}$")


def fetch_cardamom(start, end):
    """All small-cardamom e-auctions between two dates (paged, 10 per page)."""
    out, page, pages = [], 1, 1
    while page <= pages:
        query = {"auctioneer": "", "d1": start.strftime("%d/%m/%Y"),
                 "d2": end.strftime("%d/%m/%Y"), "page": page}
        body = fetch(CARDAMOM_URL + "?" + urllib.parse.urlencode(query))
        m = re.search(r"Page \d+ of (\d+) pages", body)
        pages = int(m.group(1)) if m else 1
        for c in table_rows(body):
            if len(c) >= 9 and DATE_RE.match(c[1]):
                out.append({
                    "date": to_iso(c[1]), "auctioneer": c[2], "lots": num(c[3]),
                    "arrived": num(c[4]), "sold": num(c[5]),
                    "max": num(c[6]), "min": num(c[7]), "avg": num(c[8]),
                })
        print(f"  cardamom page {page}/{pages}", flush=True)
        page += 1
        time.sleep(1)  # be polite to the Spices Board server
    return out


def fetch_pepper(start, end):
    """Daily black-pepper market prices (Kochi garbled/ungarbled and others)."""
    query = {"filterState": "", "filterSpice": "Pepper",
             "dateFrom": start.isoformat(), "dateTo": end.isoformat()}
    body = fetch(PEPPER_URL + "?" + urllib.parse.urlencode(query))
    out = []
    for c in table_rows(body):
        if len(c) >= 9 and DATE_RE.match(c[0]) and c[1].lower() == "pepper":
            out.append({
                "date": to_iso(c[0]), "market": c[2], "grade": c[4] or "-",
                "source": c[5], "min": num(c[6]), "max": num(c[7]), "avg": num(c[8]),
            })
    return out


# ------------------------------------------------------------------ storage ---
def open_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS cardamom_auctions (
            date TEXT, auctioneer TEXT, lots REAL, arrived REAL, sold REAL,
            max REAL, min REAL, avg REAL, PRIMARY KEY (date, auctioneer));
        CREATE TABLE IF NOT EXISTS pepper_prices (
            date TEXT, market TEXT, grade TEXT, source TEXT,
            min REAL, max REAL, avg REAL, PRIMARY KEY (date, market, grade));
    """)
    return db


def save(db, cardamom, pepper):
    db.executemany(
        "INSERT OR REPLACE INTO cardamom_auctions VALUES "
        "(:date,:auctioneer,:lots,:arrived,:sold,:max,:min,:avg)", cardamom)
    db.executemany(
        "INSERT OR REPLACE INTO pepper_prices VALUES "
        "(:date,:market,:grade,:source,:min,:max,:avg)", pepper)
    db.commit()


def last_date(db, table):
    row = db.execute(f"SELECT MAX(date) FROM {table}").fetchone()
    return dt.date.fromisoformat(row[0]) if row and row[0] else None


def update(db, backfill_days=None):
    today = dt.date.today()
    for table, fetcher, label in (("cardamom_auctions", fetch_cardamom, "cardamom"),
                                  ("pepper_prices", fetch_pepper, "pepper")):
        latest = last_date(db, table)
        if backfill_days:
            start = today - dt.timedelta(days=backfill_days)
        elif latest is None:
            start = today - dt.timedelta(days=DEFAULT_BACKFILL_DAYS)
        else:
            start = latest - dt.timedelta(days=10)  # re-check recent days for late entries
        print(f"Fetching {label} prices {start} -> {today}")
        rows = fetcher(start, today)
        save(db, rows if label == "cardamom" else [], rows if label == "pepper" else [])
        print(f"  saved {len(rows)} {label} rows")


# ----------------------------------------------------------------- analysis ---
def load_series(db):
    """Daily series: cardamom (qty-weighted auction average) and Kochi pepper."""
    cardamom = []
    for d, wavg, mx, mn, arrived, sold, n in db.execute("""
            SELECT date,
                   CASE WHEN SUM(sold) > 0 THEN SUM(avg * sold) / SUM(sold) ELSE AVG(avg) END,
                   MAX(max), MIN(min), SUM(arrived), SUM(sold), COUNT(*)
            FROM cardamom_auctions WHERE avg IS NOT NULL
            GROUP BY date ORDER BY date"""):
        cardamom.append({"date": d, "avg": round(wavg, 2), "max": mx, "min": mn,
                         "arrived": arrived, "sold": sold, "auctions": n})
    pepper = {}
    for d, grade, avg in db.execute("""
            SELECT date, grade, avg FROM pepper_prices
            WHERE lower(market) IN ('cochin', 'kochi') AND avg IS NOT NULL
              AND lower(grade) IN ('garbled', 'ungarbled') ORDER BY date"""):
        pepper.setdefault(d, {})[grade.lower()] = avg
    pepper_rows = [{"date": d, "garbled": v.get("garbled"), "ungarbled": v.get("ungarbled")}
                   for d, v in sorted(pepper.items())]
    return cardamom, pepper_rows


def points(rows, key):
    return [(dt.date.fromisoformat(r["date"]), r[key]) for r in rows if r.get(key) is not None]


def value_on_or_before(pts, day):
    best = None
    for d, v in pts:
        if d <= day:
            best = (d, v)
        else:
            break
    return best


def summarise(pts):
    if not pts:
        return None
    d, v = pts[-1]
    prev = pts[-2] if len(pts) > 1 else None
    out = {"date": d.isoformat(), "value": v,
           "prev": prev[1] if prev else None, "prev_date": prev[0].isoformat() if prev else None}
    for label, days in (("w", 7), ("m", 30)):
        ref = value_on_or_before(pts, d - dt.timedelta(days=days))
        out[label] = ref[1] if ref else None
    return out


def pct(a, b):
    return (a - b) / b * 100 if a is not None and b else None


def inr(v):
    """Indian digit grouping: 123456 -> 1,23,456"""
    s = f"{abs(round(v)):d}"
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        s = head + "," + tail
    return ("-" if v < 0 else "") + "₹" + s


def build_alerts(cardamom, pepper):
    alerts, today = [], dt.date.today()
    series = {
        "cardamom": points(cardamom, "avg"),
        "pepper_garbled": points(pepper, "garbled"),
        "pepper_ungarbled": points(pepper, "ungarbled"),
    }
    for key, pts in series.items():
        name = SERIES_NAMES[key]
        if not pts:
            continue
        last_d, last_v = pts[-1]
        if (today - last_d).days >= STALE_AFTER_DAYS:
            alerts.append({"kind": "info", "title": f"{name}: no new prices since {last_d:%d %b}",
                           "detail": "The Spices Board has not published newer data yet (holiday or delay)."})
        ref = value_on_or_before(pts, last_d - dt.timedelta(days=7))
        change = pct(last_v, ref[1]) if ref else None
        if change is not None and abs(change) >= WEEK_MOVE_ALERT_PCT[key]:
            word = "up" if change > 0 else "down"
            alerts.append({"kind": word, "title": f"{name} {word} {abs(change):.1f}% in a week",
                           "detail": f"{inr(ref[1])} on {ref[0]:%d %b} → {inr(last_v)} on {last_d:%d %b} (per kg)."})
        window = [v for d, v in pts[:-1] if d >= last_d - dt.timedelta(days=LOW_HIGH_WINDOW_DAYS)]
        if len(window) >= 20:
            if last_v < min(window):
                alerts.append({"kind": "down", "title": f"{name} at its lowest in {LOW_HIGH_WINDOW_DAYS} days",
                               "detail": f"{inr(last_v)}/kg on {last_d:%d %b}. Previous {LOW_HIGH_WINDOW_DAYS}-day low was {inr(min(window))}."})
            elif last_v > max(window):
                alerts.append({"kind": "up", "title": f"{name} at its highest in {LOW_HIGH_WINDOW_DAYS} days",
                               "detail": f"{inr(last_v)}/kg on {last_d:%d %b}. Previous {LOW_HIGH_WINDOW_DAYS}-day high was {inr(max(window))}."})
    # cardamom arrivals: heavy supply usually pulls auction prices down, light supply pushes them up.
    # Daily arrivals swing a lot (big and small auctioneers alternate), so compare the last
    # 7 days' total with the average week of the 4 weeks before that.
    # Today is left out: at 1 PM / 6 PM some of today's auctions may not be published yet.
    arr = [(d, v) for d, v in points(cardamom, "arrived") if d < today]
    if len(arr) >= 30:
        last_d = arr[-1][0]
        week = sum(v for d, v in arr if d > last_d - dt.timedelta(days=7))
        before = [v for d, v in arr if last_d - dt.timedelta(days=35) < d <= last_d - dt.timedelta(days=7)]
        usual = sum(before) / 4 if before else 0
        ratio = week / usual if usual else 1
        if ratio >= HEAVY_ARRIVAL_RATIO or ratio <= LIGHT_ARRIVAL_RATIO:
            heavy = ratio >= HEAVY_ARRIVAL_RATIO
            alerts.append({
                "kind": "info",
                "title": f"Cardamom arrivals {'heavy' if heavy else 'light'} this week",
                "detail": f"{week/1000:,.0f} tonnes in the last 7 days vs {usual/1000:,.0f} t in a usual week "
                          f"(previous 4 weeks). {'More supply often pulls prices down.' if heavy else 'Less supply often pushes prices up.'}"})
    return alerts


# ---------------------------------------------------------------- dashboard ---
def build_dashboard(cardamom, pepper, alerts):
    data = {
        "generated": dt.datetime.now().strftime("%d %b %Y, %I:%M %p"),
        "cardamom": cardamom,
        "pepper": pepper,
        "summary": {
            "cardamom": summarise(points(cardamom, "avg")),
            "pepper_garbled": summarise(points(pepper, "garbled")),
            "pepper_ungarbled": summarise(points(pepper, "ungarbled")),
        },
        "alerts": alerts,
    }
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    template = (HERE / "dashboard_template.html").read_text(encoding="utf-8")
    DASHBOARD_PATH.write_text(template.replace("__DATA__", payload), encoding="utf-8")
    return DASHBOARD_PATH


# ------------------------------------------------ messages: Telegram / WhatsApp ---
TELEGRAM_CONFIG = HERE / "telegram_config.json"
WHATSAPP_CONFIG = HERE / "whatsapp_config.json"
NOTIFY_STATE = HERE / "data" / "notify_state.json"
TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
CALLMEBOT_URL = "https://api.callmebot.com/whatsapp.php"


def _move(cur, ref, as_pct=False):
    if cur is None or ref is None or not ref:
        return "–"
    diff = cur - ref
    if round(diff) == 0:
        return "no change"
    arrow = "▲" if diff > 0 else "▼"
    return f"{arrow} {abs(diff) / ref * 100:.1f}%" if as_pct else f"{arrow} {inr(abs(diff))}"


def build_message(cardamom, pepper, alerts, style="telegram", app_url=None, news=None):
    """Short price update. style='telegram' -> HTML tags, style='whatsapp' -> *bold* / _italic_."""
    if style == "whatsapp":
        b, i, t = (lambda s: f"*{s}*"), (lambda s: f"_{s}_"), (lambda s: s)
    else:
        b = lambda s: f"<b>{html.escape(s, quote=False)}</b>"
        i = lambda s: f"<i>{html.escape(s, quote=False)}</i>"
        t = lambda s: html.escape(s, quote=False)
    summ = {
        "cardamom": summarise(points(cardamom, "avg")),
        "pepper_garbled": summarise(points(pepper, "garbled")),
        "pepper_ungarbled": summarise(points(pepper, "ungarbled")),
    }
    dates = [s["date"] for s in summ.values() if s]
    if not dates:
        return None, None
    latest = max(dates)
    now = dt.datetime.now()
    today_iso = now.date().isoformat()
    lines = [b(f"🌿 Spice Prices · {now:%a, %d %b} · {now:%I:%M %p} update".replace(" 0", " "))]
    if news:
        lines.append(t(news))
    lines.append("")
    blocks = (
        ("cardamom", "Cardamom", "auction avg"),
        ("pepper_garbled", "Pepper Garbled", "Kochi"),
        ("pepper_ungarbled", "Pepper Ungarbled", "Kochi"),
    )
    for key, name, where in blocks:
        s = summ[key]
        if not s:
            continue
        when = "" if s["date"] == today_iso else " " + i(f"(as of {dt.date.fromisoformat(s['date']):%d %b})")
        lines.append(f"{b(name)} ({where}){when}")
        lines.append(f"{inr(s['value'])}/kg  {_move(s['value'], s['prev'])} vs prev day")
        lines.append(f"Week: {_move(s['value'], s['w'], True)} · Month: {_move(s['value'], s['m'], True)}")
        if key == "cardamom" and cardamom:
            last = cardamom[-1]
            if last.get("arrived"):
                label = "Today so far" if last["date"] == today_iso else "Arrivals"
                lines.append(f"{label}: {last['arrived'] / 1000:,.0f} t ({last['auctions']} auction{'s' if last['auctions'] != 1 else ''})")
        lines.append("")
    if alerts:
        lines.append("⚠️ " + b("Alerts"))
        for a in alerts:
            lines.append(f"• {b(a['title'])}: {t(a['detail'])}")
    else:
        lines.append("✅ No alerts today")
    lines += ["", i("Source: Spices Board of India")]
    if app_url:
        lines.append(f"📊 Open app: {app_url}")
    return "\n".join(lines), latest


def load_whatsapp_config():
    if not WHATSAPP_CONFIG.exists():
        return None
    cfg = json.loads(WHATSAPP_CONFIG.read_text(encoding="utf-8"))
    people = [p for p in cfg.get("recipients", [])
              if p.get("phone") and p.get("apikey") and "PUT" not in str(p.get("apikey")).upper()]
    cfg["recipients"] = people
    return cfg if people else None


def send_whatsapp(cfg, text):
    """Send to every recipient. Returns how many messages went through."""
    sent = 0
    for person in cfg["recipients"]:
        query = urllib.parse.urlencode({"phone": person["phone"], "text": text, "apikey": person["apikey"]})
        name = person.get("name") or person["phone"][-4:]
        try:
            body = fetch(f"{CALLMEBOT_URL}?{query}", tries=2)
            reply = re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", body)).strip()
            if re.search(r"error|invalid|not activated|wrong", reply, re.I):
                print(f"  WhatsApp to {name}: FAILED - {reply[:200]}")
            else:
                print(f"  WhatsApp to {name}: sent")
                sent += 1
        except RuntimeError as exc:
            reason = str(exc).rsplit(": ", 1)[-1].replace(person["apikey"], "***")
            print(f"  WhatsApp to {name}: FAILED - could not reach CallMeBot ({reason}). Will retry next run.")
        time.sleep(2)
    return sent


def telegram_call(token, method, params=None):
    """Call the Telegram Bot API. The bot token is never printed."""
    url = TELEGRAM_API.format(token=token, method=method)
    data = urllib.parse.urlencode(params or {}).encode()
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=data, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # Telegram explains errors in the JSON body
            try:
                return json.loads(exc.read().decode("utf-8"))
            except Exception:
                last = f"HTTP {exc.code}"
        except Exception as exc:
            last = str(exc).replace(token, "***")
        time.sleep(3 * (attempt + 1))
    return {"ok": False, "description": f"could not reach Telegram ({last})"}


def load_telegram_config(need_chats=True):
    """Settings come from telegram_config.json on a PC, or from environment
    variables (GitHub repository secrets) when running on GitHub."""
    env_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if env_token:
        chats = []
        for part in os.environ.get("TELEGRAM_CHATS", "").split(","):   # "Ronil:123,Papa:456"
            name, _, chat_id = part.strip().rpartition(":")
            if chat_id.strip():
                chats.append({"name": name.strip() or chat_id.strip(), "chat_id": chat_id.strip()})
        cfg = {"bot_token": env_token, "chats": chats, "send": os.environ.get("TELEGRAM_SEND", "daily")}
    elif TELEGRAM_CONFIG.exists():
        cfg = json.loads(TELEGRAM_CONFIG.read_text(encoding="utf-8"))
    else:
        return None
    if os.environ.get("APP_URL"):
        cfg["app_url"] = os.environ["APP_URL"]
    token = str(cfg.get("bot_token", ""))
    if not token or "PUT" in token.upper() or ":" not in token:
        return None
    cfg["chats"] = [c for c in cfg.get("chats", []) if c.get("chat_id")]
    if need_chats and not cfg["chats"]:
        return None
    return cfg


def telegram_setup():
    """Find everyone who pressed Start on the bot and save their chat ids."""
    cfg = load_telegram_config(need_chats=False)
    if not cfg:
        print("First put your bot token in telegram_config.json (see README, 'Telegram messages').")
        return
    me = telegram_call(cfg["bot_token"], "getMe")
    if not me.get("ok"):
        print(f"The bot token is not working: {me.get('description')}. Check telegram_config.json.")
        return
    bot = me["result"]["username"]
    print(f"Bot found: @{bot}")
    upd = telegram_call(cfg["bot_token"], "getUpdates")
    known = {str(c["chat_id"]) for c in cfg["chats"]}
    added = []
    for u in upd.get("result", []):
        chat = (u.get("message") or u.get("my_chat_member") or {}).get("chat")
        if not chat or str(chat["id"]) in known:
            continue
        name = chat.get("first_name") or chat.get("title") or chat.get("username") or str(chat["id"])
        cfg["chats"].append({"name": name, "chat_id": chat["id"]})
        known.add(str(chat["id"]))
        added.append(name)
    TELEGRAM_CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    if added:
        print("Added: " + ", ".join(added))
    else:
        print(f"No new people found. On the phone, open https://t.me/{bot} , press START, then run this again.")
    print("People who will get messages: " + (", ".join(c["name"] for c in cfg["chats"]) or "nobody yet"))


def send_telegram(cfg, text):
    sent = 0
    for chat in cfg["chats"]:
        res = telegram_call(cfg["bot_token"], "sendMessage", {
            "chat_id": chat["chat_id"], "text": text,
            "parse_mode": "HTML", "disable_web_page_preview": "true"})
        name = chat.get("name") or chat["chat_id"]
        if res.get("ok"):
            print(f"  Telegram to {name}: sent")
            sent += 1
        else:
            print(f"  Telegram to {name}: FAILED - {res.get('description')}")
    return sent


def _channels():
    channels = []
    tg = load_telegram_config()
    if tg:
        channels.append(("telegram", tg, send_telegram))
    wa = load_whatsapp_config()
    if wa:
        channels.append(("whatsapp", wa, send_whatsapp))
    return channels


def _load_state():
    return json.loads(NOTIFY_STATE.read_text()) if NOTIFY_STATE.exists() else {}


def _save_state(state):
    NOTIFY_STATE.parent.mkdir(parents=True, exist_ok=True)
    NOTIFY_STATE.write_text(json.dumps(state))


def notify_problem(reason):
    """Tell the family (once a day) that the Spices Board site could not be read."""
    channels = _channels()
    state = _load_state()
    today = dt.date.today().isoformat()
    if not channels or state.get("problem") == today:
        return
    text = ("⚠️ Spice Price Tracker could not get today's prices from the Spices Board website "
            f"({reason[:120]}). It will try again tomorrow. Older prices are still in the app.")
    for channel, cfg, sender in channels:
        sender(cfg, html.escape(text, quote=False) if channel == "telegram" else text)
    state["problem"] = today
    _save_state(state)


def _fingerprint(cardamom, pepper):
    return {"auctions": sum(r["auctions"] for r in cardamom), "pepper_days": len(pepper)}


def _whats_new(prev, cur, pepper):
    """One line telling what arrived since the last message."""
    if not prev:
        return None
    new_auctions = cur["auctions"] - prev.get("auctions", 0)
    new_pepper = cur["pepper_days"] - prev.get("pepper_days", 0)
    parts = []
    if new_auctions > 0:
        parts.append(f"{new_auctions} new cardamom auction{'s' if new_auctions != 1 else ''}")
    if new_pepper > 0 and pepper:
        parts.append(f"pepper rate for {dt.date.fromisoformat(pepper[-1]['date']):%d %b}")
    if parts:
        return "🆕 New since last update: " + ", ".join(parts)
    return "ℹ️ No new prices since the last update."


def notify(cardamom, pepper, alerts, force=False):
    """Send the price update on each set-up channel.
    send = "every_run": a message every time (GitHub: 1 PM and 6 PM)
    send = "daily":     only when a new day of prices appears
    send = "alerts_only": only when there is an alert"""
    channels = _channels()
    if not channels:
        print("Messages: Telegram/WhatsApp not set up yet (see README).")
        return
    state = _load_state()
    fp = _fingerprint(cardamom, pepper)
    for channel, cfg, sender in channels:
        label = channel.capitalize()
        mode = cfg.get("send", "daily")
        news = _whats_new(state.get(f"{channel}_fp"), fp, pepper)
        text, latest = build_message(cardamom, pepper, alerts, style=channel,
                                     app_url=cfg.get("app_url"), news=news)
        if not text:
            continue
        if not force:
            if mode == "daily" and state.get(channel) and latest <= state[channel]:
                print(f"{label}: prices for {latest} already sent, nothing new.")
                continue
            if mode == "alerts_only" and not alerts:
                print(f"{label}: no alerts today, nothing sent (send = alerts_only).")
                continue
        print(f"Sending {label} message...")
        if sender(cfg, text):
            state[channel] = latest
            state[f"{channel}_fp"] = fp
            _save_state(state)


def main():
    ap = argparse.ArgumentParser(description="Cardamom & black pepper price tracker")
    ap.add_argument("--backfill", type=int, metavar="DAYS", help="download the last DAYS days of history")
    ap.add_argument("--no-fetch", action="store_true", help="skip downloading, just rebuild the dashboard")
    ap.add_argument("--preview-message", action="store_true", help="print today's message without sending")
    ap.add_argument("--send-now", action="store_true", help="send the message now, even if already sent today")
    ap.add_argument("--no-messages", "--no-whatsapp", action="store_true", help="do not send any Telegram/WhatsApp message")
    ap.add_argument("--telegram-setup", action="store_true", help="find people who pressed Start on your bot")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    if args.telegram_setup:
        telegram_setup()
        return

    db = open_db()
    fetch_problem = None
    if not args.no_fetch:
        try:
            update(db, args.backfill)
        except RuntimeError as exc:
            fetch_problem = str(exc).rsplit(": ", 1)[-1]
            print(f"WARNING: {exc}\nBuilding the dashboard from saved data instead.", file=sys.stderr)
    cardamom, pepper = load_series(db)
    alerts = build_alerts(cardamom, pepper)
    path = build_dashboard(cardamom, pepper, alerts)

    print(f"\nDashboard: {path}")
    if alerts:
        print("ALERTS:")
        for a in alerts:
            print(f"  * {a['title']} - {a['detail']}")
    else:
        print("No alerts today.")

    if args.preview_message:
        text, _ = build_message(cardamom, pepper, alerts, style="whatsapp")
        print("\n----- Message preview -----\n" + (text or "(no data)"))
    elif not args.no_messages:
        print()
        if fetch_problem:
            notify_problem(fetch_problem)
        notify(cardamom, pepper, alerts, force=args.send_now)


if __name__ == "__main__":
    main()
