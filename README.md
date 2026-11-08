# Spice Price Tracker: Cardamom & Black Pepper

Every day this tool collects market prices published by the **Spices Board of India**
and shows them on one page with trends and alerts.

| Spice | What it tracks | Source page |
|---|---|---|
| Small cardamom | Every e-auction (Bodinayakanur / Puttady auctioneers): arrivals, quantity sold, max and average price | [Daily auction price](https://www.indianspices.com/marketing/price/domestic/daily-price-small.html) |
| Black pepper | Kochi market rate, garbled and ungarbled | [Current market price](https://www.indianspices.com/marketing/price/domestic/current-market-price.html) |

## Phone app (runs by itself on GitHub)
Every day at **1:00 PM and 6:00 PM India time**, GitHub runs this tracker automatically
(`.github/workflows/daily.yml`). It fetches the prices, saves them in `data/prices.db`, publishes the app,
and sends a Telegram update. Each message says what's new since the previous one
(e.g. "🆕 1 new cardamom auction"). No PC needs to be on.

To change the times, edit the two `cron:` lines in `daily.yml`. They're in UTC: India time minus 5:30.

- **App link:** `https://<github-username>.github.io/<repository-name>/`
- **Install on phone:** open the link in Chrome, then tap ⋮ and **Add to Home screen** (on iPhone: Safari, then Share, then **Add to Home Screen**).
- **Run it now:** on GitHub, go to **Actions**, then **Daily spice prices**, then **Run workflow**.
- **Telegram settings on GitHub:** go to **Settings**, then **Secrets and variables**, then **Actions**:
  - `TELEGRAM_BOT_TOKEN`: the bot token from BotFather
  - `TELEGRAM_CHATS`: who gets messages, like `Ronil:123456789,Papa:987654321`
- GitHub may start the 9 AM run a few minutes late on busy days.

## Daily use on a PC (optional)
Double-click **`run_daily.bat`**. It downloads the latest prices and opens the app page `site/index.html`.

The dashboard shows:
- **Alerts**, for example a price up or down more than 5% in a week, the lowest or highest in 90 days, or heavy or light cardamom arrivals
- Today's rate, with the change since the previous day, 1 week ago and 1 month ago
- Charts for 1 month, 3 months, 6 months or 1 year
- A table of the last 20 days

## Telegram messages (recommended)
After each new day of prices, everyone who joined your bot gets the daily summary on Telegram.
It's free, official and arrives instantly.

**One-time setup:**
1. In Telegram, search **@BotFather** (blue tick) and press **Start**.
2. Send `/newbot`. Give it a name (e.g. `Spice Prices`) and a username ending in `bot`
   (e.g. `jainspices_price_bot`).
3. BotFather replies with a **token** like `123456789:AAH...`. Open `telegram_config.json` in
   Notepad, replace `PUT_BOT_TOKEN_HERE` with it (keep the quotes), and save.
4. Everyone who should get messages opens the bot link BotFather gave (`t.me/<username>`) and presses **START**.
5. Run `python tracker.py --telegram-setup`. It finds everyone who pressed Start and saves them.
6. Run `python tracker.py --send-now` to send the first message.

To add a person later, they press START on the bot, then run step 5 again.
Keep the token private. Anyone with it can control the bot.

## WhatsApp messages (optional, via CallMeBot)
After each new day of prices, everyone on the list gets a WhatsApp message like this:

```
*🌿 Spice Prices · Fri, 06 Nov 2026*

*Cardamom* (auction avg)
₹3,142/kg  ▲ ₹114 vs prev day
Week: ▲ 4.8% · Month: ▼ 1.2%
Arrivals: 82 t (2 auctions)

*Pepper Garbled* (Kochi)
₹758/kg  ▲ ₹1 vs prev day
Week: ▼ 0.3% · Month: ▲ 4.7%
...
✅ No alerts today
```

It uses **CallMeBot**, a free service for sending WhatsApp notifications to your own number.
It's for personal use only, so add only family members.

**One-time setup (2 minutes per person):**
1. On the phone that should get the messages, save **+34 684 728 023** as a contact (any name).
2. From that phone, send this WhatsApp message to the contact: `I allow callmebot to send me messages`
3. Within 2 minutes you get a reply with your **APIKEY**. If no reply comes, try again after 24 hours.
4. Copy `whatsapp_config.example.json` to **`whatsapp_config.json`**. Put each person's phone number (with +91) and APIKEY in it. Remove any extra rows.
5. Run `python tracker.py --send-now` once to test.

**Settings in `whatsapp_config.json`:**
- `"send": "daily"` sends the summary every day new prices come out (default).
- `"send": "alerts_only"` sends only on days with an alert.

Each day's prices are sent only once, even if the tracker runs several times. No auction on a
Sunday or holiday means no message that day.

Other commands:
```
python tracker.py --preview-message   # see the message without sending
python tracker.py --send-now          # send again right now
python tracker.py --no-whatsapp       # update without sending
```

Keep `whatsapp_config.json` private, because it contains the APIKEYs.

## Needs
- Windows PC with Python 3.10 or newer (nothing else to install)
- Internet connection

## Commands
```
python tracker.py                 # daily update + dashboard
python tracker.py --backfill 365  # download a year of history again
python tracker.py --no-fetch      # rebuild dashboard without downloading
```

## Changing alert sensitivity
Edit the numbers at the top of `tracker.py`, such as `WEEK_MOVE_ALERT_PCT`.

## Files
- `tracker.py`: downloads prices, works out alerts, builds the dashboard
- `dashboard_template.html`: dashboard design
- `data/prices.db`: all saved prices (SQLite)
- `data/log.txt`: log from daily runs
- `whatsapp_config.json`: who gets WhatsApp messages (you create this, see above)
- `data/notify_state.json`: remembers what the last message contained, for the "what's new" line
- `site/`: the phone app (published on GitHub Pages)
- `.github/workflows/daily.yml`: the 1 PM / 6 PM automatic run

## Note
The cardamom figure is the average of **all lots and grades** at the auction. Your
7 mm or 8 mm bold rate will be different, but it usually moves in the same direction. Use the
trend, not the exact number.
