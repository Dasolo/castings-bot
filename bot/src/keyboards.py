from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

print("keyboards.py loaded")

def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎛 Мои фильтры"), KeyboardButton(text="📢 Предложить канал")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери действие...",
    )