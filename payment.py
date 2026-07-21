import logging

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from database import (
    get_setting, create_payment, get_payment, update_payment_screenshot,
    update_payment_txid, log_action, get_user_pending_payment,
    get_user,
)
from config import ADMIN_IDS
from keyboards import i_paid_keyboard, back_to_menu_keyboard
from utils import is_true, format_payment_method
from i18n import t

logger = logging.getLogger('brainboost')

_PRICE_DEFAULTS = {
    'price_uah': '630', 'price_eur': '15', 'price_usd': '16',
    'price_uah_3m': '1390', 'price_eur_3m': '33', 'price_usd_3m': '36',
    'price_uah_6m': '2520', 'price_eur_6m': '60', 'price_usd_6m': '65',
}

_PLAN_SUFFIX = {1: '', 3: '_3m', 6: '_6m'}


def _language(user_id):
    user = get_user(user_id)
    return (user or {}).get('language') or 'en'


def _fmt_price(value):
    return int(value) if value == int(value) else round(value, 2)


def get_plan_price(currency_key, months=1):
    """Цена тарифа: price_eur / price_eur_3m / price_eur_6m. Целое, если без копеек."""
    key = f'{currency_key}{_PLAN_SUFFIX.get(int(months), "")}'
    value = float(get_setting(key, _PRICE_DEFAULTS.get(key, '0')))
    return _fmt_price(value)


def plan_discount_percent(months):
    """Скидка тарифа относительно месячной цены × срок (по EUR)"""
    monthly = float(get_plan_price('price_eur', 1))
    plan = float(get_plan_price('price_eur', months))
    if monthly <= 0 or months <= 1:
        return 0
    return max(0, round((1 - plan / (monthly * months)) * 100))


def plan_per_month(months):
    """Цена в пересчёте на месяц (EUR)"""
    return _fmt_price(float(get_plan_price('price_eur', months)) / months)


def build_buy_text(language, mode='buy', user_id=None):
    """Продающий текст. mode: buy | limit | locked."""
    from database import get_confirmed_buyers_count, user_eligible_for_bonus_24h

    price_3m = get_plan_price('price_eur', 3)
    pct_3m = plan_discount_percent(3)
    per_month = plan_per_month(3)

    if mode == 'limit':
        parts = [
            f"🔒 *{t(language, 'limit_locked_title')}*\n"
            f"{t(language, 'limit_locked_body')}",
            t(language, 'paywall_hero',
              price=price_3m, pct=pct_3m, per_month=per_month),
        ]
    elif mode == 'locked':
        parts = [
            f"🔒 {t(language, 'category_locked')}",
            t(language, 'paywall_hero',
              price=price_3m, pct=pct_3m, per_month=per_month),
        ]
    else:
        parts = [
            f"{t(language, 'buy_title')}\n"
            f"_{t(language, 'buy_tagline')}_",
            t(language, 'buy_features'),
            t(language, 'paywall_hero',
              price=price_3m, pct=pct_3m, per_month=per_month),
        ]

    buyers = get_confirmed_buyers_count()
    if buyers >= 10:
        shown = (buyers // 10) * 10
        parts.append(t(language, 'buy_social', n=shown))

    # +14 дней только когда реально даём (лимит / eligible)
    if mode == 'limit' or (user_id and user_eligible_for_bonus_24h(user_id)):
        parts.append(t(language, 'buy_bonus_24h'))

    parts.append(
        f"{t(language, 'buy_instant')}\n"
        f"{t(language, 'buy_trust')}"
    )
    parts.append(f"*{t(language, 'choose_plan')}*")
    return '\n\n'.join(parts)


def buy_plans_keyboard(language='en', hero=True):
    """Витрина тарифов: 3 месяца (якорь) → 1 месяц → 6 месяцев."""
    rows = []
    if hero:
        rows.append([InlineKeyboardButton(
            t(language, 'plan_3m_hero',
              price=get_plan_price('price_eur', 3),
              pct=plan_discount_percent(3)),
            callback_data='plan_3',
        )])
        rows.append([InlineKeyboardButton(
            t(language, 'plan_1m', price=get_plan_price('price_eur', 1)),
            callback_data='plan_1',
        )])
        rows.append([InlineKeyboardButton(
            t(language, 'plan_6m',
              price=get_plan_price('price_eur', 6),
              pct=plan_discount_percent(6)),
            callback_data='plan_6',
        )])
    else:
        rows.append([InlineKeyboardButton(
            t(language, 'plan_1m', price=get_plan_price('price_eur', 1)),
            callback_data='plan_1',
        )])
        rows.append([InlineKeyboardButton(
            t(language, 'plan_3m',
              price=get_plan_price('price_eur', 3),
              pct=plan_discount_percent(3)),
            callback_data='plan_3',
        )])
        rows.append([InlineKeyboardButton(
            t(language, 'plan_6m',
              price=get_plan_price('price_eur', 6),
              pct=plan_discount_percent(6)),
            callback_data='plan_6',
        )])
    rows.append([InlineKeyboardButton(t(language, 'back_menu'), callback_data='main_menu')])
    return InlineKeyboardMarkup(rows)


_PLACEHOLDER_MARKERS = (
    '9999 9999', '4149 4999', 'TXxx', 'DE89 3704', 'XXXX', 'xxxXxxx',
)


def _looks_placeholder(*values):
    blob = ' '.join(str(v or '') for v in values)
    return any(m in blob for m in _PLACEHOLDER_MARKERS)


def buy_methods_keyboard(language='en', months=1):
    """Способы оплаты для выбранного тарифа (без плейсхолдер-реквизитов)"""
    buttons = []
    if is_true(get_setting('card_uah_enabled', 'true')) and not _looks_placeholder(
        get_setting('card_uah_number', ''), get_setting('card_uah_recipient', '')
    ):
        price = get_plan_price('price_uah', months)
        buttons.append([InlineKeyboardButton(
            t(language, 'buy_card_uah', price=price),
            callback_data=f'pay_card_uah_{months}',
        )])
    if is_true(get_setting('card_eur_enabled', 'true')) and not _looks_placeholder(
        get_setting('card_eur_iban', ''), get_setting('card_eur_recipient', '')
    ):
        price = get_plan_price('price_eur', months)
        buttons.append([InlineKeyboardButton(
            t(language, 'buy_card_eur', price=price),
            callback_data=f'pay_card_eur_{months}',
        )])
    if is_true(get_setting('usdt_enabled', 'true')) and not _looks_placeholder(
        get_setting('usdt_wallet', '')
    ):
        price = get_plan_price('price_usd', months)
        buttons.append([InlineKeyboardButton(
            t(language, 'buy_usdt', price=price),
            callback_data=f'pay_usdt_{months}',
        )])
    buttons.append([InlineKeyboardButton(t(language, 'back_plans'), callback_data='buy')])
    return InlineKeyboardMarkup(buttons)


def get_payment_details(method, language='en', months=1):
    """Получить реквизиты и сумму для способа оплаты с учётом тарифа"""
    if method == 'card_uah':
        amount = get_plan_price('price_uah', months)
        number = get_setting('card_uah_number', '')
        enabled = (
            is_true(get_setting('card_uah_enabled', 'true'))
            and not _looks_placeholder(number)
        )
        return {
            'amount': float(amount),
            'currency': 'UAH',
            'method': 'card_uah',
            'enabled': enabled,
            'title': f"💳 *{t(language, 'payment_title_uah')}*",
            'details': (
                f"{t(language, 'bank')}: `{get_setting('card_uah_bank', '')}`\n"
                f"{t(language, 'card')}: `{number}`\n"
                f"{t(language, 'recipient')}: `{get_setting('card_uah_recipient', '')}`\n"
                f"{t(language, 'amount')}: *{amount} UAH*"
            ),
        }
    if method == 'card_eur':
        amount = get_plan_price('price_eur', months)
        iban = get_setting('card_eur_iban', '')
        enabled = (
            is_true(get_setting('card_eur_enabled', 'true'))
            and not _looks_placeholder(iban)
        )
        return {
            'amount': float(amount),
            'currency': 'EUR',
            'method': 'card_eur',
            'enabled': enabled,
            'title': f"💳 *{t(language, 'payment_title_eur')}*",
            'details': (
                f"IBAN: `{iban}`\n"
                f"BIC: `{get_setting('card_eur_bic', '')}`\n"
                f"{t(language, 'recipient')}: `{get_setting('card_eur_recipient', '')}`\n"
                f"{t(language, 'amount')}: *{amount} EUR*"
            ),
        }
    if method == 'usdt':
        amount = get_plan_price('price_usd', months)
        wallet = get_setting('usdt_wallet', '')
        enabled = (
            is_true(get_setting('usdt_enabled', 'true'))
            and not _looks_placeholder(wallet)
        )
        return {
            'amount': float(amount),
            'currency': 'USD',
            'method': 'usdt',
            'enabled': enabled,
            'title': f"🪙 *{t(language, 'payment_title_usdt')}*",
            'details': (
                f"{t(language, 'network')}: `{get_setting('usdt_network', 'TRC20')}`\n"
                f"{t(language, 'wallet')}: `{wallet}`\n"
                f"{t(language, 'amount')}: *{amount} USDT*"
            ),
        }
    return None


async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /buy — выбор тарифа Pro"""
    from config import ADMIN_IDS as _ADMINS
    if is_true(get_setting('maintenance_mode', 'false')):
        if update.effective_user.id not in _ADMINS:
            language = _language(update.effective_user.id)
            text = t(language, 'maintenance')
            if update.callback_query:
                await update.callback_query.answer(text, show_alert=True)
            else:
                await update.message.reply_text(text)
            return

    context.user_data['awaiting_screenshot'] = False
    context.user_data.pop('pending_order_id', None)
    context.user_data.pop('admin_action', None)
    uid = update.effective_user.id
    language = _language(uid)
    text = build_buy_text(language, user_id=uid)
    if update.callback_query:
        await update.callback_query.answer(t(language, 'toast_buy'))
        await update.callback_query.edit_message_text(
            text, reply_markup=buy_plans_keyboard(language), parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            text, reply_markup=buy_plans_keyboard(language), parse_mode='Markdown'
        )


async def plan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор тарифа: plan_1 / plan_3 / plan_6 → способы оплаты"""
    query = update.callback_query
    await query.answer()
    language = _language(query.from_user.id)
    months = {'plan_1': 1, 'plan_3': 3, 'plan_6': 6}.get(query.data, 1)
    plan_name = t(language, f'plan_name_{months}')
    await query.edit_message_text(
        f"{t(language, 'buy_title')} · *{plan_name}*\n\n"
        f"*{t(language, 'buy_choose')}*",
        reply_markup=buy_methods_keyboard(language, months),
        parse_mode='Markdown',
    )


async def payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор способа оплаты: pay_card_uah_1 / pay_card_eur_3 / pay_usdt_1 …"""
    query = update.callback_query
    await query.answer()
    language = _language(query.from_user.id)

    data = query.data.replace('pay_', '')
    months = 1
    for suffix, value in (('_6', 6), ('_3', 3), ('_1', 1)):
        if data.endswith(suffix):
            months, data = value, data[:-2]
            break
    method = data
    info = get_payment_details(method, language, months)

    if not info or not info['enabled']:
        await query.edit_message_text(
            t(language, 'payment_unavailable'),
            reply_markup=buy_plans_keyboard(language),
        )
        return

    user_id = query.from_user.id
    order_id = create_payment(
        user_id, info['amount'], info['currency'], info['method'], months=months
    )
    context.user_data['pending_order_id'] = order_id
    # Можно слать чек сразу, без обязательного «Я оплатил»
    context.user_data['awaiting_screenshot'] = True

    plan_name = t(language, f'plan_name_{months}')
    text = (
        f"{info['title']} · {plan_name}\n\n"
        f"{info['details']}\n\n"
        f"{t(language, 'order')}: `{order_id}`\n\n"
        f"{t(language, 'payment_steps')}\n\n"
        f"_{t(language, 'payment_review')}_"
    )
    await query.edit_message_text(
        text, reply_markup=i_paid_keyboard(order_id, language), parse_mode='Markdown'
    )
    log_action(user_id, 'payment_created', f'{order_id} {method} {months}m')


async def i_paid_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пользователь нажал «Я оплатил»"""
    query = update.callback_query
    language = _language(query.from_user.id)

    order_id = query.data.replace('i_paid_', '')
    payment = get_payment(order_id)

    if not payment:
        await query.answer()
        await query.edit_message_text(
            t(language, 'order_not_found'),
            reply_markup=back_to_menu_keyboard(language),
        )
        return

    if payment['user_id'] != query.from_user.id:
        await query.answer(t(language, 'not_your_order'), show_alert=True)
        return

    await query.answer()
    context.user_data['pending_order_id'] = order_id
    context.user_data['awaiting_screenshot'] = True

    hint = t(language, 'send_receipt')
    if payment['payment_method'] == 'usdt':
        hint += f"\n\n{t(language, 'send_receipt_usdt')}"

    await query.edit_message_text(
        f"✓ *{t(language, 'order')} `{order_id}`*\n\n{hint}",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t(language, 'cancel'), callback_data="buy")]
        ]),
    )


async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE, file_id=None, caption=None):
    """Обработка скриншота/PDF оплаты"""
    order_id = context.user_data.get('pending_order_id')
    if not order_id:
        pending = get_user_pending_payment(update.effective_user.id)
        if pending:
            order_id = pending['order_id']
        elif not context.user_data.get('awaiting_screenshot'):
            return False
        else:
            return False

    payment = get_payment(order_id)
    if not payment or payment['user_id'] != update.effective_user.id:
        return False
    if payment['status'] not in ('pending', 'paid'):
        return False

    if file_id is None:
        if not update.message.photo:
            return False
        file_id = update.message.photo[-1].file_id
        caption = update.message.caption or ''

    update_payment_screenshot(order_id, file_id, caption or '')

    context.user_data['awaiting_screenshot'] = False
    context.user_data.pop('pending_order_id', None)
    language = _language(update.effective_user.id)

    await update.message.reply_text(
        f"*{t(language, 'receipt_received')}*\n\n"
        f"{t(language, 'order')}: `{order_id}`\n\n"
        f"{t(language, 'receipt_wait')}",
        parse_mode='Markdown',
        reply_markup=back_to_menu_keyboard(language),
    )

    log_action(update.effective_user.id, 'payment_screenshot', order_id)

    if is_true(get_setting('admin_notifications', 'true')):
        await notify_admins_payment(context, order_id, file_id)

    return True


async def handle_txid_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка TXID для USDT"""
    order_id = context.user_data.get('pending_order_id')
    if not order_id and not context.user_data.get('awaiting_screenshot'):
        pending = get_user_pending_payment(update.effective_user.id)
        if not pending or pending.get('payment_method') != 'usdt':
            return False
        order_id = pending['order_id']
    if not order_id:
        return False

    payment = get_payment(order_id)
    if not payment or payment['payment_method'] != 'usdt':
        return False
    if payment['user_id'] != update.effective_user.id:
        return False

    txid = update.message.text.strip()
    language = _language(update.effective_user.id)
    if len(txid) < 10:
        await update.message.reply_text(t(language, 'txid_short'))
        return True

    update_payment_txid(order_id, txid)
    context.user_data['awaiting_screenshot'] = False
    context.user_data.pop('pending_order_id', None)

    await update.message.reply_text(
        f"*{t(language, 'txid_received')}*\n\n"
        f"{t(language, 'order')}: `{order_id}`\n"
        f"TXID: `{txid}`\n\n"
        f"{t(language, 'receipt_wait')}",
        parse_mode='Markdown',
        reply_markup=back_to_menu_keyboard(language),
    )

    log_action(update.effective_user.id, 'payment_txid', f'{order_id}: {txid}')

    if is_true(get_setting('admin_notifications', 'true')):
        await notify_admins_payment(context, order_id, txid=txid)

    return True


async def notify_admins_payment(context, order_id, photo_file_id=None, txid=None):
    """Уведомить админов о новой оплате"""
    payment = get_payment(order_id)
    if not payment:
        return

    months = int(payment.get('months') or 1)
    text = (
        f"💳 *Новая оплата!*\n\n"
        f"🧾 Заказ: `{order_id}`\n"
        f"👤 User: `{payment['user_id']}`\n"
        f"💰 {payment['amount']} {payment['currency']}\n"
        f"💳 {format_payment_method(payment['payment_method'])}\n"
        f"📦 Тариф: {months} мес.\n"
    )
    if txid:
        text += f"🔗 TXID: `{txid}`\n"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_{order_id}")],
        [InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{order_id}")],
        [InlineKeyboardButton("📸 Скрин", callback_data=f"view_screenshot_{order_id}")],
    ])

    configured_chat = (get_setting('payment_notification_chat_id', '') or '').strip()
    targets = []
    group_target = None
    if configured_chat:
        try:
            group_target = int(configured_chat)
            targets.append(group_target)
        except ValueError:
            logger.warning(
                'Invalid payment_notification_chat_id=%s', configured_chat
            )
    targets.extend(admin_id for admin_id in ADMIN_IDS if admin_id not in targets)

    group_delivered = False
    for target_id in targets:
        if group_delivered and target_id in ADMIN_IDS:
            continue
        try:
            if photo_file_id:
                await context.bot.send_photo(
                    chat_id=target_id,
                    photo=photo_file_id,
                    caption=text,
                    parse_mode='Markdown',
                    reply_markup=keyboard,
                )
            else:
                await context.bot.send_message(
                    chat_id=target_id,
                    text=text,
                    parse_mode='Markdown',
                    reply_markup=keyboard,
                )
            if group_target is not None and target_id == group_target:
                group_delivered = True
        except Exception as exc:
            logger.warning(
                'Payment notification failed chat=%s order=%s: %s',
                target_id, order_id, exc,
            )
