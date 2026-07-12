from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from database import get_setting
from utils import is_true
from prompts_data import CATEGORY_NAMES
from i18n import (
    t, category_name, prompt_title,
)


def language_keyboard(back=False):
    buttons = [
        [
            InlineKeyboardButton('🇷🇺 Русский', callback_data='lang_ru'),
            InlineKeyboardButton('🇬🇧 English', callback_data='lang_en'),
        ],
        [
            InlineKeyboardButton('🇺🇦 Українська', callback_data='lang_uk'),
            InlineKeyboardButton('🇩🇪 Deutsch', callback_data='lang_de'),
        ],
        [InlineKeyboardButton('🇪🇸 Español', callback_data='lang_es')],
    ]
    if back:
        buttons.append([InlineKeyboardButton('‹ Back', callback_data='more_menu')])
    return InlineKeyboardMarkup(buttons)


def main_menu_keyboard(is_admin=False, language='en'):
    rows = [
        [InlineKeyboardButton(t(language, 'menu_ask'), callback_data="ask_ai")],
        [InlineKeyboardButton(t(language, 'menu_prompts'), callback_data="prompts_menu")],
        [InlineKeyboardButton(t(language, 'menu_buy'), callback_data="buy")],
        [InlineKeyboardButton(t(language, 'menu_more'), callback_data="more_menu")],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton(t(language, 'menu_admin'), callback_data="admin_panel")])
    return InlineKeyboardMarkup(rows)


def more_menu_keyboard(language='en'):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(language, 'menu_profile'), callback_data="profile")],
        [InlineKeyboardButton(t(language, 'menu_referral'), callback_data="referral")],
        [InlineKeyboardButton(t(language, 'menu_language'), callback_data="language")],
        [InlineKeyboardButton(t(language, 'menu_help'), callback_data="help")],
        [InlineKeyboardButton(t(language, 'back_menu'), callback_data="main_menu")],
    ])


def back_to_more_keyboard(language='en'):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(language, 'back'), callback_data="more_menu")]
    ])


def buy_keyboard(language='en'):
    buttons = []
    if is_true(get_setting('card_uah_enabled', 'true')):
        price = get_setting('price_uah', '1050')
        buttons.append([
            InlineKeyboardButton(t(language, 'buy_card_uah', price=price), callback_data="pay_card_uah")
        ])
    if is_true(get_setting('card_eur_enabled', 'true')):
        price = get_setting('price_eur', '25')
        buttons.append([
            InlineKeyboardButton(t(language, 'buy_card_eur', price=price), callback_data="pay_card_eur")
        ])
    if is_true(get_setting('usdt_enabled', 'true')):
        price = get_setting('price_usd', '27')
        buttons.append([
            InlineKeyboardButton(t(language, 'buy_usdt', price=price), callback_data="pay_usdt")
        ])
    buttons.append([InlineKeyboardButton(t(language, 'back'), callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)


def i_paid_keyboard(order_id, language='en'):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✓ {t(language, 'i_paid')}", callback_data=f"i_paid_{order_id}")],
        [InlineKeyboardButton(t(language, 'back_payment'), callback_data="buy")],
    ])


def prompts_categories_keyboard(language='en', counts=None):
    counts = counts or {}
    buttons = []
    row = []
    for key in CATEGORY_NAMES:
        label = category_name(key, language)
        cnt = counts.get(key)
        if cnt:
            label = f"{label} · {cnt}"
        row.append(InlineKeyboardButton(label, callback_data=f"user_cat_{key}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(t(language, 'popular'), callback_data="user_cat_popular")])
    buttons.append([InlineKeyboardButton(t(language, 'back'), callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)


def prompts_list_keyboard(prompts, category, language='en'):
    buttons = []
    for p in prompts:
        icon = p.get('icon') or '📌'
        title = prompt_title(p.get('title') or 'Prompt', language)
        label = f"{icon} {title}"
        if len(label) > 64:
            label = label[:61] + '...'
        buttons.append([
            InlineKeyboardButton(label, callback_data=f"use_prompt_{p['id']}")
        ])
    buttons.append([InlineKeyboardButton(t(language, 'back'), callback_data="prompts_menu")])
    return InlineKeyboardMarkup(buttons)


def back_to_menu_keyboard(language='en'):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(language, 'back_menu'), callback_data="main_menu")]
    ])


def cancel_keyboard(language='en'):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(language, 'cancel'), callback_data="main_menu")]
    ])


def result_keyboard(language='en', category=None, show_upgrade=False):
    rows = [
        [
            InlineKeyboardButton(t(language, 'ask_again'), callback_data='ask_ai'),
            InlineKeyboardButton(t(language, 'open_library'), callback_data='prompts_menu'),
        ],
    ]
    if category:
        rows.append([
            InlineKeyboardButton(t(language, 'similar_scenario'), callback_data=f'user_cat_{category}')
        ])
    if show_upgrade:
        rows.append([InlineKeyboardButton(t(language, 'menu_buy'), callback_data='buy')])
    rows.append([InlineKeyboardButton(t(language, 'back_menu'), callback_data='main_menu')])
    return InlineKeyboardMarkup(rows)


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
