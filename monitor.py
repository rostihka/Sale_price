#!/usr/bin/env python3
"""
Price Monitor — щоденний моніторинг цін на comfy.ua та auto.ria з сповіщеннями в Telegram.

Логіка:
- comfy_product      : бере ціну з <meta property="product:price:amount">
- auto_ria_search     : парсить сторінку ПОШУКУ, бере МІНІМАЛЬНУ ціну серед оголошень
- auto_ria_listing    : парсить сторінку КОНКРЕТНОГО оголошення, бере його поточну ціну

Стан (останні ціни + історія) зберігається у state.json і комітиться назад у репозиторій
воркфлоу GitHub Actions, тому дані не губляться між запусками.
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
STATE_PATH = os.path.join(os.path.dirname(__file__), "state.json")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
}

# Пороги для класифікації падіння ціни (у %)
THRESHOLDS = [
    (25, "🔥 більше 25%"),
    (20, "🔥 20%+"),
    (15, "📉 15%+"),
    (10, "📉 10%+"),
    (0, "🔻 невелике (менше 10%)"),
]


def send_telegram(text: str) -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[!] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID не задані — сповіщення не надіслано")
        print(text)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(
        url,
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        },
        timeout=20,
    )
    if not resp.ok:
        print("[!] Помилка відправки в Telegram:", resp.status_code, resp.text)


def fetch(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


def parse_comfy_price(html: str):
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("meta", attrs={"property": "product:price:amount"})
    if tag and tag.get("content"):
        try:
            return float(tag["content"])
        except ValueError:
            return None
    return None


PRICE_USD_RE = re.compile(r"(\d[\d\s\u00a0]{2,9}\d)\s?\$\s*·")


def parse_auto_ria_prices(html: str):
    """Повертає список поточних (не закреслених) доларових цін, знайдених на сторінці."""
    text = BeautifulSoup(html, "html.parser").get_text(separator=" ")
    prices = []
    for m in PRICE_USD_RE.finditer(text):
        num = m.group(1).replace(" ", "").replace("\u00a0", "")
        try:
            prices.append(float(num))
        except ValueError:
            pass
    return prices


def classify_drop(old_price: float, new_price: float):
    if old_price is None or new_price is None or old_price <= 0:
        return None
    if new_price >= old_price:
        return None
    pct = (old_price - new_price) / old_price * 100
    for threshold, label in THRESHOLDS:
        if pct >= threshold:
            return pct, label
    return pct, "🔻 зменшення"


def check_and_notify(state: dict, key: str, name: str, url: str, new_price: float, currency: str):
    entry = state.get(key, {})
    old_price = entry.get("last_price")
    history = entry.get("history", [])
    now = datetime.now(timezone.utc).isoformat()

    if old_price is not None:
        result = classify_drop(old_price, new_price)
        if result:
            pct, label = result
            msg = (
                f"{label}\n"
                f"<b>{name}</b>\n"
                f"Було: {old_price:,.0f} {currency}\n"
                f"Стало: {new_price:,.0f} {currency}\n"
                f"Падіння: {pct:.1f}%\n"
                f"{url}"
            ).replace(",", " ")
            send_telegram(msg)
            print(f"[{name}] ПАДІННЯ {old_price} -> {new_price} ({pct:.1f}%)")
        elif new_price > old_price:
            print(f"[{name}] ціна зросла: {old_price} -> {new_price}")
        else:
            print(f"[{name}] без змін: {new_price}")
    else:
        print(f"[{name}] перша перевірка, базова ціна = {new_price}")

    history.append({"date": now, "price": new_price})
    state[key] = {"last_price": new_price, "history": history[-180:], "name": name, "url": url}


def process_item(item: dict, state: dict):
    name = item["name"]
    url = item["url"]
    item_type = item["type"]
    key = item["id"]
    currency = item.get("currency", "₴" if item_type == "comfy_product" else "$")

    try:
        html = fetch(url)
    except Exception as e:
        print(f"[{name}] помилка завантаження сторінки: {e}")
        return

    if item_type == "comfy_product":
        price = parse_comfy_price(html)
        if price is None:
            print(f"[{name}] ціну не знайдено — можливо, змінилась структура сторінки")
            send_telegram(f"⚠️ <b>{name}</b>: не вдалось знайти ціну на сторінці.\nПеревір вручну: {url}")
            return
        check_and_notify(state, key, name, url, price, currency)

    elif item_type == "auto_ria_search":
        prices = parse_auto_ria_prices(html)
        if not prices:
            print(f"[{name}] у видачі не знайдено жодної ціни")
            return
        check_and_notify(state, key, f"{name} (мін. ціна в пошуку)", url, min(prices), currency)

    elif item_type == "auto_ria_listing":
        prices = parse_auto_ria_prices(html)
        if not prices:
            print(f"[{name}] ціну оголошення не знайдено")
            return
        check_and_notify(state, key, name, url, prices[0], currency)

    else:
        print(f"[{name}] невідомий тип '{item_type}', пропускаю")


def main():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            state = json.load(f)
    else:
        state = {}

    for item in config["items"]:
        process_item(item, state)
        time.sleep(2)  # ввічлива пауза між запитами

    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    print("Готово.")


if __name__ == "__main__":
    sys.exit(main())
