import requests

import config


def send_message(text: str, chat_id: str = None):
    chat_id = chat_id or config.TELEGRAM_CHAT_ID
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = requests.post(url, data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
    resp.raise_for_status()
    return resp.json()


def send_photo(photo_path: str, caption: str = "", chat_id: str = None):
    chat_id = chat_id or config.TELEGRAM_CHAT_ID
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendPhoto"
    with open(photo_path, "rb") as f:
        resp = requests.post(
            url,
            data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
            files={"photo": f},
        )
    resp.raise_for_status()
    return resp.json()
