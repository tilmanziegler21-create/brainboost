import asyncio
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import ADMIN_IDS
from database import (
    get_admin_stats, get_all_settings, get_setting, set_setting,
    get_pending_payments, get_payment, confirm_payment, reject_payment,
    get_prompt_categories, get_prompts_by_category, get_prompt,
    add_prompt, update_prompt, delete_prompt, get_logs, get_all_users,
    create_broadcast, update_broadcast_status, log_action,
    check_and_expire_subscriptions, get_user, get_user_token_info,
    get_tokens_usage_summary, get_top_token_users, get_low_token_users,
)
from keyboards import (
    get_admin_main_keyboard, get_settings_keyboard, get_payment_methods_keyboard,
    payment_admin_keyboard, get_admin_tokens_keyboard, result_keyboard,
)
from utils import is_true, format_tokens, format_token_bar, format_status, truncate
from i18n import t


def is_admin(user_id):
    return user_id in ADMIN_IDS


def admin_panel_text():
    stats = get_admin_stats()
    return (
        "🧠 *BrainBoost — Админ-панель*\n\n"
        f"📊 *Статистика:*\n"
        f"👥 Всего пользователей: {stats['total_users']}\n"
        f"✅ Активных подписок: {stats['active_subs']}\n"
        f"📝 Пробный период: {stats['trial_users']}\n"
        f"⏰ Просрочено: {stats['expired']}\n"
        f"📊 Запросов сегодня: {stats['today_requests']}\n"
        f"📈 Всего запросов: {stats['total_requests']}\n"
        f"🎟 Токенов списано: {format_tokens(stats.get('total_tokens_used', 0))}\n"
        f"💰 Ожидающих оплат: {stats['pending_payments']}\n"
        f"💳 Доход: {stats['total_revenue']:.2f}\n\n"
        "Выбери действие:"
    )


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        if update.message:
            await update.message.reply_text("⛔ Доступ запрещен")
        elif update.callback_query:
            await update.callback_query.answer("⛔ Доступ запрещен", show_alert=True)
        return

    text = admin_panel_text()
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text, reply_markup=get_admin_main_keyboard(), parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            text, reply_markup=get_admin_main_keyboard(), parse_mode='Markdown'
        )


async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    stats = get_admin_stats()
    text = (
        "📊 *Детальная статистика*\n\n"
        f"👥 Всего пользователей: {stats['total_users']}\n"
        f"   ├─ Активных подписок: {stats['active_subs']}\n"
        f"   ├─ Пробный период: {stats['trial_users']}\n"
        f"   └─ Просрочено: {stats['expired']}\n\n"
        f"📊 Запросов:\n"
        f"   ├─ Сегодня: {stats['today_requests']}\n"
        f"   └─ Всего: {stats['total_requests']}\n\n"
        f"🎟 Токены (всего списано): {format_tokens(stats.get('total_tokens_used', 0))}\n\n"
        f"💰 Финансы:\n"
        f"   ├─ Доход всего: {stats['total_revenue']:.2f}\n"
        f"   └─ Ожидает оплаты: {stats['pending_payments']}\n"
    )
    await query.edit_message_text(
        text, reply_markup=get_admin_main_keyboard(), parse_mode='Markdown'
    )


def _format_user_tokens_block(info):
    """Блок токенов в стиле клиентского профиля"""
    name = info['first_name'] or '—'
    uname = f"@{info['username']}" if info['username'] else '—'
    return (
        f"🆔 ID: `{info['user_id']}`\n"
        f"👤 {name} ({uname})\n"
        f"📊 Статус: {format_status(info['subscription_status'])}\n"
        f"📅 До: {info['subscription_end_date'] or '—'}\n\n"
        f"🎟 *Токены:*\n"
        f"   Использовано: `{format_tokens(info['tokens_used'])}`\n"
        f"   Лимит: `{format_tokens(info['tokens_limit'])}`\n"
        f"   Осталось: `{format_tokens(info['tokens_remaining'])}`\n"
        f"   {format_token_bar(info['percent_used'])}\n"
        f"🎁 Бонус: `{format_tokens(info['bonus_tokens'])}`"
    )


async def admin_tokens(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сводка по токенам — чтобы вовремя переключить ключ/лимиты"""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    summary = get_tokens_usage_summary()
    my_info = get_user_token_info(query.from_user.id)

    my_block = ""
    if my_info:
        my_block = (
            f"👤 *Мои токены:*\n"
            f"   {format_tokens(my_info['tokens_used'])} / {format_tokens(my_info['tokens_limit'])}\n"
            f"   Осталось: `{format_tokens(my_info['tokens_remaining'])}`\n"
            f"   {format_token_bar(my_info['percent_used'])}\n\n"
        )

    text = (
        "🎟 *Мониторинг токенов*\n\n"
        f"{my_block}"
        f"📈 *Общая сводка:*\n"
        f"   Всего списано: `{format_tokens(summary['total_used'])}`\n"
        f"   ├─ Активные: `{format_tokens(summary['active_used'])}`\n"
        f"   └─ Trial: `{format_tokens(summary['trial_used'])}`\n"
        f"   Юзеров с расходом: {summary['users_with_usage']}\n\n"
        f"📅 *Сегодня:*\n"
        f"   Запросов: {summary['today_requests']}\n"
        f"   Токенов: `{format_tokens(summary['today_tokens'])}`\n\n"
        "Выбери действие:"
    )
    await query.edit_message_text(
        text, reply_markup=get_admin_tokens_keyboard(), parse_mode='Markdown'
    )


async def admin_tokens_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просмотр своих токенов — как у клиента в /profile"""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    info = get_user_token_info(query.from_user.id)
    if not info:
        await query.edit_message_text(
            "❌ Сначала напиши /start, чтобы создать профиль.",
            reply_markup=get_admin_tokens_keyboard(),
        )
        return

    text = (
        "👤 *Мои токены (админ)*\n\n"
        f"{_format_user_tokens_block(info)}\n\n"
        f"👥 Рефералов: {info['total_referrals']}\n"
        f"🔗 Код: `{info['referral_code']}`"
    )
    await query.edit_message_text(
        text, reply_markup=get_admin_tokens_keyboard(), parse_mode='Markdown'
    )


async def admin_tokens_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Топ пользователей по расходу токенов"""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    top = get_top_token_users(10)
    if not top:
        await query.edit_message_text(
            "📭 Пока никто не тратил токены.",
            reply_markup=get_admin_tokens_keyboard(),
        )
        return

    text = "🔥 *Топ по расходу токенов*\n\n"
    for i, u in enumerate(top, 1):
        name = u['first_name'] or u['username'] or str(u['user_id'])
        text += (
            f"{i}. `{u['user_id']}` {name}\n"
            f"   {format_tokens(u['tokens_used'])}/{format_tokens(u['tokens_limit'])} "
            f"| {format_token_bar(u['percent_used'])}\n"
        )

    if len(text) > 4000:
        text = text[:4000] + "\n..."

    await query.edit_message_text(
        text, reply_markup=get_admin_tokens_keyboard(), parse_mode='Markdown'
    )


async def admin_tokens_low(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пользователи с почти исчерпанным лимитом"""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    low = get_low_token_users(threshold_percent=80, limit=15)
    if not low:
        await query.edit_message_text(
            "✅ Нет пользователей с расходом ≥80%.",
            reply_markup=get_admin_tokens_keyboard(),
        )
        return

    text = "⚠️ *Мало токенов (≥80%)*\n\n"
    for u in low:
        name = u['first_name'] or u['username'] or str(u['user_id'])
        text += (
            f"• `{u['user_id']}` {name}\n"
            f"  Осталось: `{format_tokens(u['tokens_remaining'])}` "
            f"| {format_token_bar(u['percent_used'])}\n"
        )

    if len(text) > 4000:
        text = text[:4000] + "\n..."

    await query.edit_message_text(
        text, reply_markup=get_admin_tokens_keyboard(), parse_mode='Markdown'
    )


async def admin_tokens_find(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрос ID пользователя для просмотра токенов"""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    context.user_data['admin_action'] = 'find_user_tokens'
    await query.edit_message_text(
        "🔍 *Найти пользователя*\n\n"
        "Отправь `user_id` (число).\n"
        "Отмена: /cancel",
        parse_mode='Markdown',
    )


async def admin_show_user_tokens(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Показать токены конкретного пользователя"""
    info = get_user_token_info(user_id)
    if not info:
        await update.message.reply_text(
            f"❌ Пользователь `{user_id}` не найден.",
            parse_mode='Markdown',
            reply_markup=get_admin_tokens_keyboard(),
        )
        return

    text = (
        "🎟 *Токены пользователя*\n\n"
        f"{_format_user_tokens_block(info)}"
    )
    await update.message.reply_text(
        text, reply_markup=get_admin_tokens_keyboard(), parse_mode='Markdown'
    )


async def admin_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    await query.edit_message_text(
        "⚙️ *Настройки BrainBoost*\n\nВыбери категорию:",
        reply_markup=get_settings_keyboard(),
        parse_mode='Markdown',
    )


async def admin_settings_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    text = (
        "💰 *Цены*\n\n"
        f"EUR: `{get_setting('price_eur')}`\n"
        f"USD (USDT): `{get_setting('price_usd')}`\n"
        f"UAH: `{get_setting('price_uah')}`\n\n"
        "*Изменить:*\n"
        "`/set_price_eur 30`\n"
        "`/set_price_usd 32`\n"
        "`/set_price_uah 1200`"
    )
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад", callback_data="admin_settings")]
        ]),
        parse_mode='Markdown',
    )


async def admin_settings_limits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    text = (
        "🎯 *Лимиты*\n\n"
        f"Бесплатных запросов: `{get_setting('free_requests')}`\n"
        f"Токенов в подписке: `{format_tokens(int(get_setting('subscription_tokens', '0')))}`\n"
        f"Дней подписки: `{get_setting('subscription_days')}`\n"
        f"Бонус за реферала: `{format_tokens(int(get_setting('referral_bonus', '0')))}`\n"
        f"Макс рефералов: `{get_setting('max_referrals')}`\n\n"
        "*Изменить:*\n"
        "`/set_free_requests 20`\n"
        "`/set_subscription_tokens 50000000`\n"
        "`/set_subscription_days 30`\n"
        "`/set_referral_bonus 5000000`\n"
        "`/set_max_referrals 5`"
    )
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад", callback_data="admin_settings")]
        ]),
        parse_mode='Markdown',
    )


async def admin_settings_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    await query.edit_message_text(
        "💳 *Способы оплаты*\n\nВыбери метод для настройки:",
        reply_markup=get_payment_methods_keyboard(),
        parse_mode='Markdown',
    )


async def admin_settings_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    current = get_setting('welcome_message', '')
    context.user_data['admin_action'] = 'set_welcome'
    await query.edit_message_text(
        f"📝 *Приветствие*\n\nТекущее:\n{current}\n\n"
        "Отправь новый текст приветствия.\n"
        "Для отмены: /cancel",
        parse_mode='Markdown',
    )


async def admin_settings_maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    current = get_setting('maintenance_mode', 'false')
    new_val = 'false' if is_true(current) else 'true'
    set_setting('maintenance_mode', new_val)
    status = "🔴 ВКЛЮЧЁН" if is_true(new_val) else "🟢 ВЫКЛЮЧЕН"
    await query.edit_message_text(
        f"🛠 Режим обслуживания: *{status}*",
        reply_markup=get_settings_keyboard(),
        parse_mode='Markdown',
    )


async def admin_payment_card_uah(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    enabled = get_setting('card_uah_enabled', 'true')
    text = (
        "💳 *Карта UAH*\n\n"
        f"Статус: {'✅ Вкл' if is_true(enabled) else '❌ Выкл'}\n"
        f"Номер: `{get_setting('card_uah_number')}`\n"
        f"Банк: `{get_setting('card_uah_bank')}`\n"
        f"Получатель: `{get_setting('card_uah_recipient')}`\n\n"
        "*Изменить:*\n"
        "`/set_card_uah_number 4149...`\n"
        "`/set_card_uah_bank ПриватБанк`\n"
        "`/set_card_uah_recipient ИМЯ`\n"
        "Или нажми кнопку переключения."
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"{'❌ Выключить' if is_true(enabled) else '✅ Включить'}",
            callback_data="toggle_card_uah_enabled"
        )],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin_settings_payment")],
    ])
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')


async def admin_payment_card_eur(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    enabled = get_setting('card_eur_enabled', 'true')
    text = (
        "💳 *Карта EUR*\n\n"
        f"Статус: {'✅ Вкл' if is_true(enabled) else '❌ Выкл'}\n"
        f"IBAN: `{get_setting('card_eur_iban')}`\n"
        f"BIC: `{get_setting('card_eur_bic')}`\n"
        f"Получатель: `{get_setting('card_eur_recipient')}`\n\n"
        "*Изменить:*\n"
        "`/set_card_eur_iban DE89...`\n"
        "`/set_card_eur_bic COBADEFFXXX`\n"
        "`/set_card_eur_recipient BrainBoost OÜ`"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"{'❌ Выключить' if is_true(enabled) else '✅ Включить'}",
            callback_data="toggle_card_eur_enabled"
        )],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin_settings_payment")],
    ])
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')


async def admin_payment_usdt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    enabled = get_setting('usdt_enabled', 'true')
    text = (
        "🪙 *USDT (TRC20)*\n\n"
        f"Статус: {'✅ Вкл' if is_true(enabled) else '❌ Выкл'}\n"
        f"Сеть: `{get_setting('usdt_network')}`\n"
        f"Кошелёк: `{get_setting('usdt_wallet')}`\n\n"
        "*Изменить:*\n"
        "`/set_usdt_wallet TXxx...`\n"
        "`/set_usdt_network TRC20`"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"{'❌ Выключить' if is_true(enabled) else '✅ Включить'}",
            callback_data="toggle_usdt_enabled"
        )],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin_settings_payment")],
    ])
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')


async def toggle_setting_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    key = query.data.replace('toggle_', '')
    current = get_setting(key, 'false')
    new_val = 'false' if is_true(current) else 'true'
    set_setting(key, new_val)

    if key == 'card_uah_enabled':
        await admin_payment_card_uah(update, context)
    elif key == 'card_eur_enabled':
        await admin_payment_card_eur(update, context)
    elif key == 'usdt_enabled':
        await admin_payment_usdt(update, context)
    else:
        await query.edit_message_text(
            f"✅ `{key}` = `{new_val}`",
            parse_mode='Markdown',
            reply_markup=get_settings_keyboard(),
        )


async def admin_payments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    payments = get_pending_payments()

    if not payments:
        await query.edit_message_text(
            "✅ Нет ожидающих оплат",
            reply_markup=get_admin_main_keyboard(),
        )
        return

    await query.edit_message_text(
        f"📋 Показаны последние {min(5, len(payments))} оплат",
        reply_markup=get_admin_main_keyboard(),
    )

    for p in payments[:5]:
        text = (
            f"💳 *Оплата #{p['order_id']}*\n"
            f"👤 User: `{p['user_id']}`\n"
            f"💰 Сумма: {p['amount']} {p['currency']}\n"
            f"📅 Создан: {p['created_at']}\n"
            f"💳 Метод: {p['payment_method']}\n"
            f"📝 Статус: {p['status']}\n"
        )
        if p.get('txid'):
            text += f"🔗 TXID: `{p['txid']}`\n"
        await query.message.reply_text(
            text, reply_markup=payment_admin_keyboard(p['order_id']), parse_mode='Markdown'
        )


async def confirm_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    order_id = query.data.replace('confirm_', '')
    user_id = confirm_payment(order_id, query.from_user.id)

    if user_id:
        days = get_setting('subscription_days', '30')
        tokens = format_tokens(int(get_setting('subscription_tokens', '50000000')))
        try:
            if query.message.photo:
                await query.edit_message_caption(caption=f"✅ Оплата #{order_id} подтверждена!")
            else:
                await query.edit_message_text(f"✅ Оплата #{order_id} подтверждена!")
        except Exception:
            await query.message.reply_text(f"✅ Оплата #{order_id} подтверждена!")

        try:
            user = get_user(user_id)
            language = (user or {}).get('language') or 'en'
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    f"{t(language, 'pro_activated')}\n\n"
                    f"{t(language, 'pro_activated_body', tokens=tokens, days=days)}"
                ),
                parse_mode='Markdown',
                reply_markup=result_keyboard(language),
            )
        except Exception:
            pass
    else:
        await query.edit_message_text(f"❌ Ошибка при подтверждении #{order_id}")


async def reject_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    order_id = query.data.replace('reject_', '')
    payment = get_payment(order_id)
    reject_payment(order_id, query.from_user.id)

    try:
        if query.message.photo:
            await query.edit_message_caption(caption=f"❌ Оплата #{order_id} отклонена")
        else:
            await query.edit_message_text(f"❌ Оплата #{order_id} отклонена")
    except Exception:
        await query.message.reply_text(f"❌ Оплата #{order_id} отклонена")

    if payment:
        try:
            user = get_user(payment['user_id'])
            language = (user or {}).get('language') or 'en'
            await context.bot.send_message(
                chat_id=payment['user_id'],
                text=(
                    f"{t(language, 'payment_rejected', order_id=order_id)}\n\n"
                    f"{t(language, 'payment_rejected_body')}"
                ),
                parse_mode='Markdown',
            )
        except Exception:
            pass


async def view_screenshot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    order_id = query.data.replace('view_screenshot_', '')
    payment = get_payment(order_id)

    if payment and payment['screenshot_file_id']:
        await query.message.reply_photo(
            photo=payment['screenshot_file_id'],
            caption=f"📸 Скриншот для заказа #{order_id}",
        )
    elif payment and payment.get('txid'):
        await query.message.reply_text(f"🔗 TXID для #{order_id}:\n`{payment['txid']}`", parse_mode='Markdown')
    else:
        await query.answer("❌ Скриншот не найден", show_alert=True)


async def admin_prompts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    categories = get_prompt_categories()
    keyboard = []
    for cat in categories:
        keyboard.append([InlineKeyboardButton(f"📂 {cat}", callback_data=f"prompt_cat_{cat}")])
    keyboard.append([InlineKeyboardButton("➕ Добавить промт", callback_data="prompt_add")])
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_back")])

    await query.edit_message_text(
        "📝 *Управление промтами*\n\nВыбери категорию или добавь новый:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown',
    )


async def prompt_category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    category = query.data.replace('prompt_cat_', '')
    prompts = get_prompts_by_category(category)

    if not prompts:
        await query.edit_message_text(
            f"📂 В категории '{category}' нет промтов",
            reply_markup=get_admin_main_keyboard(),
        )
        return

    await query.edit_message_text(f"📂 Категория: {category}")

    for p in prompts:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_prompt_{p['id']}")],
            [InlineKeyboardButton("🗑️ Удалить", callback_data=f"del_prompt_{p['id']}")],
        ])
        icon = p.get('icon') or '📌'
        desc = p.get('description') or ''
        text = f"{icon} *{p['title']}*\n"
        if desc:
            text += f"{desc}\n"
        text += f"\n`{truncate(p['prompt_text'], 200)}`"
        await query.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown')


async def prompt_add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    context.user_data['admin_action'] = 'add_prompt'
    await query.edit_message_text(
        "📝 *Добавление промта (магазин)*\n\n"
        "Формат (через `|`):\n"
        "`категория | название | описание | system | шаблон | vars | иконка`\n\n"
        "Пример:\n"
        "`marketing | Instagram пост | 5 вариантов | Ты SMM... | "
        "Напиши 5 постов на тему: {topic} | topic | 📸`\n\n"
        "Категории: marketing, code, study, health, business, creativity, life\n"
        "vars: через запятую, напр. `topic,style`\n"
        "Минимум 3 поля: категория | название | шаблон\n"
        "Отмена: /cancel",
        parse_mode='Markdown',
    )


async def edit_prompt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    prompt_id = int(query.data.replace('edit_prompt_', ''))
    prompt = get_prompt(prompt_id)

    if not prompt:
        await query.edit_message_text("❌ Промт не найден")
        return

    context.user_data['admin_action'] = 'edit_prompt'
    context.user_data['edit_prompt_id'] = prompt_id

    await query.edit_message_text(
        f"✏️ *Редактирование промта #{prompt_id}*\n\n"
        f"📌 Название: {prompt['title']}\n"
        f"📂 Категория: {prompt['category']}\n\n"
        f"Отправь новый текст промта:\n\n"
        f"Текущий текст:\n`{truncate(prompt['prompt_text'], 500)}`",
        parse_mode='Markdown',
    )


async def delete_prompt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    prompt_id = int(query.data.replace('del_prompt_', ''))
    delete_prompt(prompt_id)
    await query.edit_message_text(f"🗑️ Промт #{prompt_id} удален")


def _claude_admin_keyboard():
    from claude_api import AVAILABLE_MODELS
    current = get_setting('claude_model', 'claude-opus-4-8')
    rows = [
        [InlineKeyboardButton("💳 Проверить баланс", callback_data="admin_claude_usage")],
        [InlineKeyboardButton("🧪 Тест соединения", callback_data="admin_claude_test")],
    ]
    for model_id, label in AVAILABLE_MODELS:
        mark = '✅ ' if model_id == current else ''
        rows.append([InlineKeyboardButton(
            f"{mark}{label}",
            callback_data=f"admin_claude_model_{model_id}",
        )])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_back")])
    return InlineKeyboardMarkup(rows)


async def admin_claude(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    from claude_api import (
        get_model_multiplier, DEFAULT_BASE_URL, DEFAULT_MODEL,
        find_claude_bin, get_cli_version, cli_version_ok, MIN_CLI_VERSION,
        _stable_home, _has_cli_login,
    )

    api_key = get_setting('claude_api_key', 'Не настроен')
    model = get_setting('claude_model', DEFAULT_MODEL)
    api_url = get_setting('claude_api_url', DEFAULT_BASE_URL)
    mult = get_model_multiplier(model)
    key_ok = api_key and api_key not in ('sk-ant-api-xxx', 'Не настроен')

    claude_bin = find_claude_bin()
    cli_ver = get_cli_version(claude_bin) if claude_bin else None
    if not claude_bin:
        cli_status = '❌ CLI не установлен'
    elif cli_ver and cli_version_ok(cli_ver):
        cli_status = f'✅ CLI {cli_ver}'
    else:
        cli_status = f'⚠️ CLI {cli_ver or "?"} (нужно ≥{MIN_CLI_VERSION})'

    home = _stable_home()
    login_ok = _has_cli_login(home)
    login_status = '✅ есть' if login_ok else '❌ нет (нужен шаг 2)'

    text = (
        "🔑 *Claude API (через Claude Code CLI)*\n\n"
        f"URL: `{api_url}`\n"
        f"Модель: `{model}` (×{mult})\n"
        f"CLI: {cli_status}\n"
        f"Логин CLI: {login_status}\n"
        f"Путь: `{claude_bin or '—'}`\n"
        f"API Key: {'✅ Настроен' if key_ok else '❌ Не настроен'}\n\n"
        "_Ключ работает через Claude Code CLI. "
        "setup-token (Max/Pro) не обязателен — достаточно api_key._\n\n"
        "*Команды:*\n"
        "`/set_claude_api_key KEY`\n"
        "`/set_claude_model MODEL`\n"
        "`/set_claude_api_url URL`\n\n"
        "Модели: opus 1.0x · sonnet 0.7x · haiku 0.3x · fable 2.0x"
    )
    await query.edit_message_text(
        text,
        parse_mode='Markdown',
        reply_markup=_claude_admin_keyboard(),
    )


async def admin_claude_usage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверить баланс ключа через /v1/usage"""
    query = update.callback_query
    await query.answer('Проверяю...')
    if not is_admin(query.from_user.id):
        return

    from claude_api import check_usage, format_usage_text

    ok, data = check_usage()
    if ok:
        text = format_usage_text(data)
    else:
        text = f"❌ Не удалось получить баланс:\n`{data}`"

    await query.edit_message_text(
        text,
        parse_mode='Markdown',
        reply_markup=_claude_admin_keyboard(),
    )


async def admin_claude_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Тест: usage + короткий запрос через Claude Code CLI"""
    query = update.callback_query
    await query.answer('Тестирую CLI...')
    if not is_admin(query.from_user.id):
        return

    from claude_api import test_connection

    ok, result = test_connection()
    if ok:
        reply = result.get('reply', '')[:200]
        tokens = result.get('tokens', 0)
        cli_ver = result.get('cli_version', '?')
        usage_preview = format_tokens(tokens) if isinstance(tokens, int) else tokens
        text = (
            f"✅ *Соединение OK*\n\n"
            f"CLI: `{cli_ver}`\n"
            f"Ответ: `{reply}`\n"
            f"Токены (с коэф.): `{usage_preview}`"
        )
    else:
        text = f"❌ *Тест не прошёл*\n\n`{result}`"

    await query.edit_message_text(
        text,
        parse_mode='Markdown',
        reply_markup=_claude_admin_keyboard(),
    )


async def admin_claude_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Смена модели кнопкой"""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    model = query.data.replace('admin_claude_model_', '')
    set_setting('claude_model', model)
    log_action(query.from_user.id, 'admin_setting', f'claude_model={model}')
    await admin_claude(update, context)


async def admin_price_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка команд изменения настроек"""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return

    text = update.message.text
    parts = text.split(maxsplit=1)

    if len(parts) != 2:
        await update.message.reply_text("❌ Формат: /команда значение")
        return

    command = parts[0]
    value = parts[1].strip()

    command_map = {
        '/set_price_eur': 'price_eur',
        '/set_price_usd': 'price_usd',
        '/set_price_uah': 'price_uah',
        '/set_free_requests': 'free_requests',
        '/set_claude_api_key': 'claude_api_key',
        '/set_claude_model': 'claude_model',
        '/set_claude_api_url': 'claude_api_url',
        '/set_claude_client_version': 'claude_client_version',
        '/set_claude_anthropic_version': 'claude_anthropic_version',
        '/set_claude_oauth_token': 'claude_oauth_token',
        '/set_subscription_tokens': 'subscription_tokens',
        '/set_subscription_days': 'subscription_days',
        '/set_referral_bonus': 'referral_bonus',
        '/set_max_referrals': 'max_referrals',
        '/set_card_uah_number': 'card_uah_number',
        '/set_card_uah_bank': 'card_uah_bank',
        '/set_card_uah_recipient': 'card_uah_recipient',
        '/set_card_eur_iban': 'card_eur_iban',
        '/set_card_eur_bic': 'card_eur_bic',
        '/set_card_eur_recipient': 'card_eur_recipient',
        '/set_usdt_wallet': 'usdt_wallet',
        '/set_usdt_network': 'usdt_network',
        '/set_welcome': 'welcome_message',
    }

    key = command_map.get(command)
    if not key:
        await update.message.reply_text("❌ Неизвестная команда")
        return

    try:
        set_setting(key, value)
        display = '***' if ('api_key' in key or 'oauth_token' in key or 'token' in key) else value
        await update.message.reply_text(f"✅ `{key}` обновлено: `{display}`", parse_mode='Markdown')
        log_action(user_id, 'admin_setting', f'{key}={display}')
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")


async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    await query.edit_message_text(
        "📢 *Рассылка*\n\n"
        "Отправь сообщение для рассылки всем пользователям.\n"
        "Это может быть текст, фото или видео.\n\n"
        "Для отмены отправь /cancel_broadcast",
        parse_mode='Markdown',
    )
    context.user_data['admin_action'] = 'broadcast'


async def cancel_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    context.user_data.pop('admin_action', None)
    await update.message.reply_text("❌ Рассылка отменена")


async def broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправить сообщение всем пользователям"""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return False

    if context.user_data.get('admin_action') != 'broadcast':
        return False

    message = update.message
    users = get_all_users()
    total = len(users)

    broadcast_id = create_broadcast(message.text if message.text else '📢 Рассылка')
    update_broadcast_status(broadcast_id, 'sending')

    await update.message.reply_text(f"📤 Начинаю рассылку для {total} пользователей...")

    sent = 0
    for user in users:
        try:
            if message.text:
                await context.bot.send_message(chat_id=user['user_id'], text=message.text)
            elif message.photo:
                await context.bot.send_photo(
                    chat_id=user['user_id'],
                    photo=message.photo[-1].file_id,
                    caption=message.caption or '',
                )
            elif message.video:
                await context.bot.send_video(
                    chat_id=user['user_id'],
                    video=message.video.file_id,
                    caption=message.caption or '',
                )
            sent += 1
            if sent % 10 == 0:
                await asyncio.sleep(1)
        except Exception as e:
            log_action(user['user_id'], 'broadcast_failed', str(e))

    update_broadcast_status(broadcast_id, 'completed', sent)
    context.user_data.pop('admin_action', None)

    await update.message.reply_text(f"✅ Рассылка завершена!\nОтправлено: {sent}/{total}")
    return True


async def admin_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    logs = get_logs(limit=20)
    text = "📋 *Последние логи:*\n\n"
    for log in logs:
        text += f"`{log['created_at']}` | {log['user_id']} | {log['action']}\n"
        if log['details']:
            text += f"  ↳ {truncate(log['details'], 50)}\n"

    if len(text) > 4000:
        text = text[:4000] + "...\n\n(обрезано)"

    await query.edit_message_text(
        text,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад", callback_data="admin_back")]
        ]),
    )


async def admin_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Обновлено")
    if not is_admin(query.from_user.id):
        return

    expired = check_and_expire_subscriptions()
    text = admin_panel_text()
    if expired:
        text += f"\n\n🔄 Истекло подписок: {expired}"
    await query.edit_message_text(
        text, reply_markup=get_admin_main_keyboard(), parse_mode='Markdown'
    )


async def admin_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    await query.edit_message_text(
        admin_panel_text(),
        reply_markup=get_admin_main_keyboard(),
        parse_mode='Markdown',
    )


async def admin_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений для админа (промты, welcome и т.д.)"""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return False

    action = context.user_data.get('admin_action')
    if not action:
        return False

    if action == 'broadcast':
        return await broadcast_message(update, context)

    if action == 'add_prompt':
        try:
            parts = [p.strip() for p in update.message.text.split('|')]
            if len(parts) < 3:
                await update.message.reply_text(
                    "❌ Минимум: `категория | название | шаблон`\n"
                    "Полный: `кат | имя | описание | system | шаблон | vars | иконка`",
                    parse_mode='Markdown',
                )
                return True

            category = parts[0].lower()
            title = parts[1]

            # Короткий формат: cat | title | template
            if len(parts) == 3:
                description = None
                system_prompt = None
                prompt_text = parts[2]
                variables = ['topic']
                icon = '📌'
            elif len(parts) == 4:
                description = parts[2]
                system_prompt = None
                prompt_text = parts[3]
                variables = ['topic']
                icon = '📌'
            else:
                # Полный: cat | title | desc | system | template | vars | icon
                description = parts[2] or None
                system_prompt = parts[3] or None
                prompt_text = parts[4] if len(parts) > 4 else ''
                variables = [v.strip() for v in (parts[5] if len(parts) > 5 else 'topic').split(',') if v.strip()]
                icon = parts[6] if len(parts) > 6 and parts[6] else '📌'

            if not prompt_text:
                await update.message.reply_text("❌ Пустой шаблон промта")
                return True

            prompt_id = add_prompt(
                category, title, prompt_text,
                description=description,
                system_prompt=system_prompt,
                variables=variables or ['topic'],
                icon=icon,
            )
            await update.message.reply_text(
                f"✅ Промт добавлен! ID: {prompt_id}\n"
                f"📂 {category} | {icon} {title}"
            )
            context.user_data.pop('admin_action', None)
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")
        return True

    if action == 'edit_prompt':
        try:
            prompt_id = context.user_data.get('edit_prompt_id')
            if prompt_id:
                update_prompt(prompt_id, prompt_text=update.message.text)
                await update.message.reply_text(f"✅ Промт #{prompt_id} обновлен!")
                context.user_data.pop('admin_action', None)
                context.user_data.pop('edit_prompt_id', None)
            else:
                await update.message.reply_text("❌ Ошибка: не найден ID")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")
        return True

    if action == 'set_welcome':
        set_setting('welcome_message', update.message.text)
        await update.message.reply_text("✅ Приветствие обновлено!")
        context.user_data.pop('admin_action', None)
        return True

    if action == 'find_user_tokens':
        try:
            target_id = int(update.message.text.strip())
        except ValueError:
            await update.message.reply_text("❌ Отправь числовой user_id. Отмена: /cancel")
            return True
        context.user_data.pop('admin_action', None)
        await admin_show_user_tokens(update, context, target_id)
        return True

    return False


async def cancel_admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    context.user_data.pop('admin_action', None)
    context.user_data.pop('edit_prompt_id', None)
    await update.message.reply_text("❌ Действие отменено")
