from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from database import (
    get_setting, create_payment, get_payment, update_payment_screenshot,
    update_payment_txid, log_action, get_user_pending_payment,
    get_user,
)
from config import ADMIN_IDS
from keyboards import buy_keyboard, i_paid_keyboard, back_to_menu_keyboard
from utils import is_true, format_payment_method
from utils import format_tokens
from i18n import t


def _language(user_id):
    user = get_user(user_id)
    return (user or {}).get('language') or 'en'


def get_payment_details(method, language='en'):
    """Получить реквизиты и сумму для способа оплаты"""
    if method == 'card_uah':
        return {
            'amount': float(get_setting('price_uah', '1050')),
            'currency': 'UAH',
            'method': 'card_uah',
            'enabled': is_true(get_setting('card_uah_enabled', 'true')),
            'title': f"💳 *{t(language, 'payment_title_uah')}*",
            'details': (
                f"{t(language, 'bank')}: `{get_setting('card_uah_bank', '')}`\n"
                f"{t(language, 'card')}: `{get_setting('card_uah_number', '')}`\n"
                f"{t(language, 'recipient')}: `{get_setting('card_uah_recipient', '')}`\n"
                f"{t(language, 'amount')}: *{get_setting('price_uah', '1050')} UAH*"
            ),
        }
    if method == 'card_eur':
        return {
            'amount': float(get_setting('price_eur', '25')),
            'currency': 'EUR',
            'method': 'card_eur',
            'enabled': is_true(get_setting('card_eur_enabled', 'true')),
            'title': f"💳 *{t(language, 'payment_title_eur')}*",
            'details': (
                f"IBAN: `{get_setting('card_eur_iban', '')}`\n"
                f"BIC: `{get_setting('card_eur_bic', '')}`\n"
                f"{t(language, 'recipient')}: `{get_setting('card_eur_recipient', '')}`\n"
                f"{t(language, 'amount')}: *{get_setting('price_eur', '25')} EUR*"
            ),
        }
    if method == 'usdt':
        return {
            'amount': float(get_setting('price_usd', '27')),
            'currency': 'USD',
            'method': 'usdt',
            'enabled': is_true(get_setting('usdt_enabled', 'true')),
            'title': f"🪙 *{t(language, 'payment_title_usdt')}*",
            'details': (
                f"{t(language, 'network')}: `{get_setting('usdt_network', 'TRC20')}`\n"
                f"{t(language, 'wallet')}: `{get_setting('usdt_wallet', '')}`\n"
                f"{t(language, 'amount')}: *{get_setting('price_usd', '27')} USDT*"
            ),
        }
    return None


async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /buy — выбор способа оплаты"""
    language = _language(update.effective_user.id)
    tokens = format_tokens(int(get_setting('subscription_tokens', '50000000')))
    days = get_setting('subscription_days', '30')
    text = (
        f"{t(language, 'buy_title')}\n"
        f"_{t(language, 'buy_tagline')}_\n\n"
        f"{t(language, 'buy_features', tokens=tokens, days=days)}\n\n"
        f"*{t(language, 'buy_choose')}*"
    )
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text, reply_markup=buy_keyboard(language), parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            text, reply_markup=buy_keyboard(language), parse_mode='Markdown'
        )


async def payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор способа оплаты: pay_card_uah / pay_card_eur / pay_usdt"""
    query = update.callback_query
    await query.answer()
    language = _language(query.from_user.id)

    method = query.data.replace('pay_', '')
    info = get_payment_details(method, language)

    if not info or not info['enabled']:
        await query.edit_message_text(
            t(language, 'payment_unavailable'),
            reply_markup=buy_keyboard(language),
        )
        return

    user_id = query.from_user.id
    order_id = create_payment(user_id, info['amount'], info['currency'], info['method'])
    context.user_data['pending_order_id'] = order_id
    context.user_data['awaiting_screenshot'] = False

    text = (
        f"{info['title']}\n\n"
        f"{info['details']}\n\n"
        f"{t(language, 'order')}: `{order_id}`\n\n"
        f"{t(language, 'payment_steps')}\n\n"
        f"_{t(language, 'payment_review')}_"
    )
    await query.edit_message_text(
        text, reply_markup=i_paid_keyboard(order_id, language), parse_mode='Markdown'
    )
    log_action(user_id, 'payment_created', f'{order_id} {method}')


async def i_paid_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пользователь нажал «Я оплатил»"""
    query = update.callback_query
    await query.answer()
    language = _language(query.from_user.id)

    order_id = query.data.replace('i_paid_', '')
    payment = get_payment(order_id)

    if not payment:
        await query.edit_message_text(
            t(language, 'order_not_found'),
            reply_markup=back_to_menu_keyboard(language),
        )
        return

    if payment['user_id'] != query.from_user.id:
        await query.answer(t(language, 'not_your_order'), show_alert=True)
        return

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


async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка скриншота оплаты"""
    if not context.user_data.get('awaiting_screenshot'):
        return False

    order_id = context.user_data.get('pending_order_id')
    if not order_id:
        pending = get_user_pending_payment(update.effective_user.id)
        if pending:
            order_id = pending['order_id']
        else:
            return False

    payment = get_payment(order_id)
    if not payment or payment['user_id'] != update.effective_user.id:
        return False

    photo = update.message.photo[-1]
    caption = update.message.caption or ''
    update_payment_screenshot(order_id, photo.file_id, caption)

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
        await notify_admins_payment(context, order_id, photo.file_id)

    return True


async def handle_txid_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка TXID для USDT"""
    if not context.user_data.get('awaiting_screenshot'):
        return False

    order_id = context.user_data.get('pending_order_id')
    if not order_id:
        return False

    payment = get_payment(order_id)
    if not payment or payment['payment_method'] != 'usdt':
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

    text = (
        f"💳 *Новая оплата!*\n\n"
        f"🧾 Заказ: `{order_id}`\n"
        f"👤 User: `{payment['user_id']}`\n"
        f"💰 {payment['amount']} {payment['currency']}\n"
        f"💳 {format_payment_method(payment['payment_method'])}\n"
    )
    if txid:
        text += f"🔗 TXID: `{txid}`\n"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_{order_id}")],
        [InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{order_id}")],
        [InlineKeyboardButton("📸 Скрин", callback_data=f"view_screenshot_{order_id}")],
    ])

    for admin_id in ADMIN_IDS:
        try:
            if photo_file_id:
                await context.bot.send_photo(
                    chat_id=admin_id,
                    photo=photo_file_id,
                    caption=text,
                    parse_mode='Markdown',
                    reply_markup=keyboard,
                )
            else:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=text,
                    parse_mode='Markdown',
                    reply_markup=keyboard,
                )
        except Exception:
            pass
