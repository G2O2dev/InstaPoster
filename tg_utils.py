from telebot import types

def tuple_to_btn(t) -> types.InlineKeyboardButton:
    return types.InlineKeyboardButton(t[0], callback_data=t[1])


def build_markup(rows):
    keyboard = types.InlineKeyboardMarkup()
    for row in rows:
        keyboard.row(*list(map(tuple_to_btn, row)))
    return keyboard



