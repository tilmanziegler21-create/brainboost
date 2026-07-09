from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from database import get_setting
from utils import is_true, format_tokens
from prompts_data import CATEGORY_NAMES


def main_menu_keyboard(is_admin=False):
    rows = [
        [InlineKeyboardButton("💬 Спросить AI", callback_data="ask_ai")],
        [InlineKeyboardButton("📝 Готовые промты", callback_data="prompts_menu")],
        [
            InlineKeyboardButton("👤 Профиль", callback_data="profile"),
            InlineKeyboardButton("💳 Купить", callback_data="buy"),
        ],
        [InlineKeyboardButton("🎁 Рефералка", callback_data="referral")],
        [InlineKeyboardButton("❓ Помощь", callback_data="help")],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton("🛠 Админ-панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(rows)


def buy_keyboard():
    buttons = []
    if is_true(get_setting('card_uah_enabled', 'true')):
        price = get_setting('price_uah', '1050')
        buttons.append([
            InlineKeyboardButton(f"💳 Карта UAH — {price} ₴", callback_data="pay_card_uah")
        ])
    if is_true(get_setting('card_eur_enabled', 'true')):
        price = get_setting('price_eur', '25')
        buttons.append([
            InlineKeyboardButton(f"💳 Карта EUR — {price} €", callback_data="pay_card_eur")
        ])
    if is_true(get_setting('usdt_enabled', 'true')):
        price = get_setting('price_usd', '27')
        buttons.append([
            InlineKeyboardButton(f"🪙 USDT TRC20 — {price} $", callback_data="pay_usdt")
        ])
    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)


def i_paid_keyboard(order_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Я оплатил", callback_data=f"i_paid_{order_id}")],
        [InlineKeyboardButton("⬅️ Назад к способам", callback_data="buy")],
    ])


def prompts_categories_keyboard():
    buttons = []
    for key, name in CATEGORY_NAMES.items():
        buttons.append([InlineKeyboardButton(name, callback_data=f"user_cat_{key}")])
    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)


def prompts_list_keyboard(prompts, category):
    buttons = []
    for p in prompts:
        buttons.append([
            InlineKeyboardButton(f"📌 {p['title']}", callback_data=f"use_prompt_{p['id']}")
        ])
    buttons.append([InlineKeyboardButton("⬅️ К категориям", callback_data="prompts_menu")])
    return InlineKeyboardMarkup(buttons)


def back_to_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Главное меню", callback_data="main_menu")]
    ])


def cancel_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отмена", callback_data="main_menu")]
    ])


# --- Админ ---

def get_admin_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("🎟 Токены", callback_data="admin_tokens")],
        [InlineKeyboardButton("💳 Новые оплаты", callback_data="admin_payments")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="admin_settings")],
        [InlineKeyboardButton("📝 Управление промтами", callback_data="admin_prompts")],
        [InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🔑 Claude API", callback_data="admin_claude")],
        [InlineKeyboardButton("📋 Логи", callback_data="admin_logs")],
        [InlineKeyboardButton("🔄 Обновить", callback_data="admin_refresh")],
        [InlineKeyboardButton("⬅️ В бот", callback_data="main_menu")],
    ])


def get_admin_tokens_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Мои токены", callback_data="admin_tokens_me")],
        [InlineKeyboardButton("📈 Сводка", callback_data="admin_tokens")],
        [InlineKeyboardButton("🔥 Топ расход", callback_data="admin_tokens_top")],
        [InlineKeyboardButton("⚠️ Мало токенов", callback_data="admin_tokens_low")],
        [InlineKeyboardButton("🔍 Найти юзера", callback_data="admin_tokens_find")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin_back")],
    ])


def get_settings_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Цены", callback_data="admin_settings_prices")],
        [InlineKeyboardButton("💳 Способы оплаты", callback_data="admin_settings_payment")],
        [InlineKeyboardButton("🎯 Лимиты", callback_data="admin_settings_limits")],
        [InlineKeyboardButton("🔑 Claude API", callback_data="admin_claude")],
        [InlineKeyboardButton("📝 Приветствие", callback_data="admin_settings_welcome")],
        [InlineKeyboardButton("🛠 Режим обслуживания", callback_data="admin_settings_maintenance")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin_back")],
    ])


def get_payment_methods_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Карта UAH", callback_data="admin_payment_card_uah")],
        [InlineKeyboardButton("💳 Карта EUR", callback_data="admin_payment_card_eur")],
        [InlineKeyboardButton("🪙 USDT (TRC20)", callback_data="admin_payment_usdt")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin_settings")],
    ])


def payment_admin_keyboard(order_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_{order_id}")],
        [InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{order_id}")],
        [InlineKeyboardButton("📸 Посмотреть скрин", callback_data=f"view_screenshot_{order_id}")],
    ])


def toggle_button(label, key, current):
    status = "✅" if is_true(current) else "❌"
    return InlineKeyboardButton(
        f"{status} {label}",
        callback_data=f"toggle_{key}"
    )
