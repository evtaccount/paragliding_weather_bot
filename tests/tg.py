"""Builders for incoming Telegram updates and helpers over recorded outgoing calls.

Updates are built from plain dicts (the same shape Telegram sends); the bot instance
is bound by dp.feed_update itself, so no context juggling is needed here.
"""
import itertools

from aiogram.methods import (AnswerCallbackQuery, EditMessageReplyMarkup,
                             SendMediaGroup, SendMessage, SendPhoto)
from aiogram.types import Update

_ids = itertools.count(1000)


def _base_msg(uid: int) -> dict:
    return {"message_id": next(_ids), "date": 1753350000,
            "chat": {"id": uid, "type": "private"},
            "from": {"id": uid, "is_bot": False, "first_name": "Test"}}


def text_update(text: str, uid: int = 1) -> Update:
    m = _base_msg(uid)
    m["text"] = text
    return Update.model_validate({"update_id": next(_ids), "message": m})


def location_update(lat: float, lon: float, uid: int = 1) -> Update:
    m = _base_msg(uid)
    m["location"] = {"latitude": lat, "longitude": lon}
    return Update.model_validate({"update_id": next(_ids), "message": m})


def dice_update(uid: int = 1) -> Update:
    """A non-text, non-location message (🎲) — for the catch-all branch."""
    m = _base_msg(uid)
    m["dice"] = {"emoji": "🎲", "value": 3}
    return Update.model_validate({"update_id": next(_ids), "message": m})


def callback_update(data: str, uid: int = 1, accessible: bool = True) -> Update:
    """Inline-button press. accessible=False models a stale (>48h) source message —
    Telegram omits it, aiogram exposes cb.message as None."""
    cq = {"id": str(next(_ids)), "chat_instance": "ci", "data": data,
          "from": {"id": uid, "is_bot": False, "first_name": "Test"}}
    if accessible:
        cq["message"] = {**_base_msg(uid), "text": "исходное сообщение",
                         "from": {"id": 999, "is_bot": True, "first_name": "Bot"}}
    return Update.model_validate({"update_id": next(_ids), "callback_query": cq})


# ---- helpers over MockSession.requests ----

def texts(session) -> list[str]:
    return [m.text for m in session.requests if isinstance(m, SendMessage)]


def keyboards(session) -> list:
    """reply_markup of every sent message that had one, in send order."""
    return [m.reply_markup for m in session.requests
            if isinstance(m, SendMessage) and m.reply_markup]


def kb_for(session, text: str):
    """Keyboard of the sent message with the given text, or None."""
    for m in session.requests:
        if isinstance(m, SendMessage) and m.text == text and m.reply_markup:
            return m.reply_markup
    return None


def buttons(kb) -> list:
    return [b for row in kb.inline_keyboard for b in row]


def cb_answers(session) -> list:
    return [m for m in session.requests if isinstance(m, AnswerCallbackQuery)]


def photos(session) -> list:
    return [m for m in session.requests if isinstance(m, SendPhoto)]


def media_groups(session) -> list:
    return [m for m in session.requests if isinstance(m, SendMediaGroup)]


def markup_edits(session) -> list:
    return [m for m in session.requests if isinstance(m, EditMessageReplyMarkup)]
