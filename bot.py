import html
import json as js
import os
import random as rd
from io import BytesIO
from pathlib import Path

import config as cfg
import telebot
from telebot import types

BASE_DIR = Path(__file__).resolve().parent
MESSAGES_FILE = BASE_DIR / "mess.json"

bot = telebot.TeleBot(cfg.TOKEN)
messages = []
selected_cards = {}
pending_cards = {}


def load_messages():
    if not MESSAGES_FILE.exists():
        save_messages([])
        return []
    try:
        with MESSAGES_FILE.open("r", encoding="utf-8") as f:
            data = js.load(f)
    except (js.JSONDecodeError, OSError):
        data = []
    return [normalize_card(card) for card in data if isinstance(card, dict)]


def save_messages(data=None):
    data = messages if data is None else data
    tmp_file = MESSAGES_FILE.with_suffix(".json.tmp")
    with tmp_file.open("w", encoding="utf-8") as f:
        js.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_file, MESSAGES_FILE)


def normalize_card(card):
    normalized = {
        "text": card.get("text") or "",
        "image": card.get("image"),
        "parse_mode": card.get("parse_mode"),
    }
    if card.get("image_file_id"):
        normalized["image_file_id"] = card.get("image_file_id")
    return normalized


def serialize_text(message):
    text = message.text or message.caption or ""
    entities = message.entities or message.caption_entities or []
    if not entities:
        return text, None

    result = []
    cursor = 0
    sorted_entities = sorted(entities, key=lambda entity: entity.offset)
    for entity in sorted_entities:
        start = entity.offset
        end = entity.offset + entity.length
        if start < cursor:
            continue
        result.append(html.escape(text[cursor:start]))
        entity_text = html.escape(text[start:end])
        if entity.type == "spoiler":
            result.append(f"<tg-spoiler>{entity_text}</tg-spoiler>")
        else:
            result.append(entity_text)
        cursor = end
    result.append(html.escape(text[cursor:]))
    return "".join(result), "HTML"


def send_card(chat_id, card, reply_markup=None):
    text = card.get("text") or ""
    parse_mode = card.get("parse_mode")
    image_hex = card.get("image")
    image_file_id = card.get("image_file_id")

    if image_hex:
        try:
            photo = BytesIO(bytes.fromhex(image_hex))
            photo.name = "card.jpg"
            bot.send_photo(chat_id, photo)
        except (ValueError, telebot.apihelper.ApiTelegramException) as exc:
            print(f"Не удалось отправить фото из сохраненных байтов: {exc}")
            if image_file_id:
                bot.send_photo(chat_id, image_file_id)
    elif image_file_id:
        bot.send_photo(chat_id, image_file_id)

    bot.send_message(chat_id, text, parse_mode=parse_mode, reply_markup=reply_markup)


def build_admin_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.row(types.KeyboardButton("Добавить"), types.KeyboardButton("Отмена"))
    return keyboard


def build_card_actions_keyboard(index):
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("Редактировать", callback_data=f"edit:{index}"),
        types.InlineKeyboardButton("Удалить", callback_data=f"delete:{index}"),
    )
    return keyboard


messages = load_messages()


@bot.message_handler(commands=["today"])
def echo_all(message):
    if not messages:
        bot.send_message(message.from_user.id, "Карты пока не добавлены")
        return
    send_card(message.chat.id, rd.choice(messages))


@bot.message_handler(commands=["admin"], func=lambda m: m.from_user.id in cfg.ADMINS)
def admin(message):
    keyboard = build_admin_keyboard()
    bot.send_message(message.from_user.id, "Привет, выбери уже существующий элемент или добавь новый", reply_markup=keyboard)
    variants = "Доступные варианты:\n"
    for i, card in enumerate(messages):
        preview = (card.get("text") or "")[:10]
        variants += f"{i + 1}. {preview}\n"
    bot.send_message(message.from_user.id, variants, reply_markup=keyboard)
    bot.register_next_step_handler(message, actions)


def actions(message):
    data = (message.text or "").strip()
    keyboard = types.ReplyKeyboardRemove()
    if data == "Добавить":
        bot.send_message(message.from_user.id, "Хорошо, напиши текст карты", reply_markup=keyboard)
        bot.register_next_step_handler(message, add)
    elif data == "Отмена":
        bot.send_message(message.from_user.id, "Отмена", reply_markup=keyboard)
    else:
        try:
            index = int(data) - 1
        except ValueError:
            bot.send_message(message.from_user.id, "Нужно отправить номер карты, «Добавить» или «Отмена»", reply_markup=keyboard)
            return
        if index < 0 or index >= len(messages):
            bot.send_message(message.from_user.id, "Карта с таким номером не найдена", reply_markup=keyboard)
            return
        selected_cards[message.from_user.id] = index
        bot.send_message(message.from_user.id, "Хорошо\nВот карта\nЧто делать далее", reply_markup=keyboard)
        send_card(message.chat.id, messages[index], reply_markup=build_card_actions_keyboard(index))


@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    global messages
    action, _, raw_index = call.data.partition(":")
    try:
        index = int(raw_index)
    except ValueError:
        index = selected_cards.get(call.from_user.id, -1)

    if index < 0 or index >= len(messages):
        bot.answer_callback_query(call.id, "Карта не найдена")
        return

    if action in {"yes", "delete"}:
        bot.answer_callback_query(call.id, "Карта удалена")
        messages.pop(index)
        save_messages()
    elif action == "edit":
        bot.answer_callback_query(call.id, "Редактирование карты")
        pending_cards[call.from_user.id] = {"mode": "edit", "index": index, "card": dict(messages[index])}
        bot.send_message(call.message.chat.id, "Отправь новый текст карты. Скрытый текст (spoiler) будет сохранён.")
        bot.register_next_step_handler(call.message, edit_text)


def add(message):
    text, parse_mode = serialize_text(message)
    pending_cards[message.from_user.id] = {"mode": "add", "card": {"text": text, "image": None, "parse_mode": parse_mode}}
    bot.send_message(message.from_user.id, "Хорошо, теперь скинь изображение. Если изображение не нужно — отправь любой текст.")
    bot.register_next_step_handler(message, photo)


def edit_text(message):
    state = pending_cards.get(message.from_user.id)
    if not state or state.get("mode") != "edit":
        bot.send_message(message.from_user.id, "Не найдена карта для редактирования")
        return
    text, parse_mode = serialize_text(message)
    state["card"]["text"] = text
    state["card"]["parse_mode"] = parse_mode
    bot.send_message(message.from_user.id, "Текст обновлён. Пришли новое изображение или отправь любой текст, чтобы оставить старое.")
    bot.register_next_step_handler(message, photo)


def photo(message):
    state = pending_cards.pop(message.from_user.id, None)
    if not state:
        bot.send_message(message.from_user.id, "Не найдена карта для сохранения")
        return

    card = normalize_card(state["card"])
    print(message.content_type)
    if message.content_type == "photo" and message.photo:
        file_id = message.photo[-1].file_id
        file_info = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        card["image"] = downloaded_file.hex()
        card["image_file_id"] = file_id
        print("OK")

    if state.get("mode") == "edit":
        index = state.get("index")
        if index is None or index < 0 or index >= len(messages):
            bot.send_message(message.from_user.id, "Карта для редактирования не найдена")
            return
        messages[index] = card
        bot.send_message(message.from_user.id, "Карта обновлена")
    else:
        messages.append(card)
        bot.send_message(message.from_user.id, "Карта сохранена")
    save_messages()


if __name__ == "__main__":
    print("gu")
    bot.polling()
