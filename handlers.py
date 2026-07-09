from telegram import Update
from telegram.ext import ContextTypes

from config import ADMIN_IDS
from database import (
    get_user, create_user, get_remaining_tokens, get_tokens_limit,
    update_tokens_used, log_action, get_setting, get_user_by_referral_code,
    get_prompts_by_category, get_prompt, check_and_expire_subscriptions,
    get_popular_prompts, parse_prompt_variables, increment_prompt_usage,
)
from claude_api import call_claude
from keyboards import (
    main_menu_keyboard, prompts_categories_keyboard, prompts_list_keyboard,
    back_to_menu_keyboard, cancel_keyboard,
)
from payment import buy, handle_screenshot, handle_txid_text
from admin_panel import admin_text_handler, is_admin
from prompts_data import CATEGORY_NAMES, CATEGORY_ALIASES, get_var_hint
from utils import format_tokens, format_token_bar, format_status, is_true, truncate


SYSTEM_PROMPT = (
    "Ты — BrainBoost, умный AI-помощник. Отвечай полезно, конкретно и по делу. "
    "Пиши на языке пользователя. Если запрос неясен — уточни."
)


async def ensure_user(update: Update):
    """Создать пользователя если нет, вернуть user dict"""
    tg_user = update.effective_user
    user = get_user(tg_user.id)
    if not user:
        create_user(
            tg_user.id,
            tg_user.username,
            tg_user.first_name,
            last_name=tg_user.last_name,
        )
        user = get_user(tg_user.id)
    return user


async def check_maintenance(update: Update):
    """Проверка режима обслуживания (админы проходят)"""
    if is_true(get_setting('maintenance_mode', 'false')):
        if update.effective_user.id not in ADMIN_IDS:
            text = "🛠 Бот на обслуживании. Попробуй позже."
            if update.message:
                await update.message.reply_text(text)
            elif update.callback_query:
                await update.callback_query.answer(text, show_alert=True)
            return True
    return False


async def check_access(user):
    """Проверка доступа: не заблокирован и есть токены"""
    if user['subscription_status'] == 'blocked':
        return False, "🚫 Ваш аккаунт заблокирован."
    remaining = get_remaining_tokens(user['user_id'])
    if remaining <= 0:
        if user['subscription_status'] == 'active':
            return False, "⚠️ Лимит токенов исчерпан. Дождись обновления подписки или купи новую: /buy"
        return False, (
            "⚠️ Бесплатные запросы закончились.\n"
            "Оформи подписку: /buy"
        )
    return True, None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_maintenance(update):
        return

    check_and_expire_subscriptions()
    tg_user = update.effective_user
    user = get_user(tg_user.id)

    referred_by = None
    if context.args:
        ref_code = context.args[0]
        referrer = get_user_by_referral_code(ref_code)
        if referrer and referrer['user_id'] != tg_user.id:
            referred_by = referrer['user_id']

    if not user:
        create_user(
            tg_user.id,
            tg_user.username,
            tg_user.first_name,
            referred_by=referred_by,
            last_name=tg_user.last_name,
        )
        user = get_user(tg_user.id)
        log_action(tg_user.id, 'start', f'ref={referred_by}')
    else:
        log_action(tg_user.id, 'start', 'returning')

    welcome = get_setting('welcome_message', 'Привет! Я BrainBoost — твой AI-помощник')
    remaining = get_remaining_tokens(tg_user.id)
    limit = get_tokens_limit(tg_user.id)

    text = (
        f"🧠 *BrainBoost*\n\n"
        f"{welcome}\n\n"
        f"📊 Статус: {format_status(user['subscription_status'])}\n"
        f"🎟 Осталось: {format_tokens(remaining)} / {format_tokens(limit)}\n\n"
        "Выбери действие или просто напиши вопрос:"
    )
    await update.message.reply_text(
        text,
        reply_markup=main_menu_keyboard(is_admin=is_admin(tg_user.id)),
        parse_mode='Markdown',
    )


async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_maintenance(update):
        return

    user = await ensure_user(update)
    remaining = get_remaining_tokens(user['user_id'])
    limit = get_tokens_limit(user['user_id'])

    used = user['tokens_used'] or 0
    percent = round((used / limit) * 100, 1) if limit > 0 else 0

    text = (
        f"👤 *Профиль*\n\n"
        f"🆔 ID: `{user['user_id']}`\n"
        f"👤 Имя: {user['first_name'] or '—'}\n"
        f"📛 @{user['username'] or '—'}\n\n"
        f"📊 Статус: {format_status(user['subscription_status'])}\n"
        f"📅 До: {user['subscription_end_date'] or '—'}\n\n"
        f"🎟 *Токены:*\n"
        f"   Использовано: `{format_tokens(used)}`\n"
        f"   Лимит: `{format_tokens(limit)}`\n"
        f"   Осталось: `{format_tokens(remaining)}`\n"
        f"   {format_token_bar(percent)}\n"
        f"🎁 Бонус: `{format_tokens(user['bonus_tokens'])}`\n"
        f"👥 Рефералов: {user['total_referrals']}\n"
        f"🔗 Код: `{user['referral_code']}`"
    )

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text, reply_markup=back_to_menu_keyboard(), parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            text, reply_markup=back_to_menu_keyboard(), parse_mode='Markdown'
        )


async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_maintenance(update):
        return

    user = await ensure_user(update)
    bot_info = await context.bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={user['referral_code']}"
    bonus = format_tokens(int(get_setting('referral_bonus', '5000000')))
    max_refs = get_setting('max_referrals', '5')

    text = (
        f"🎁 *Реферальная программа*\n\n"
        f"Пригласи друга — получи *{bonus}* бонусных токенов!\n"
        f"Максимум: {max_refs} рефералов\n"
        f"Уже приглашено: {user['total_referrals']}\n\n"
        f"🔗 Твоя ссылка:\n`{link}`\n\n"
        f"Код: `{user['referral_code']}`\n\n"
        "_Бонус начисляется, если у тебя активная подписка._"
    )

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text, reply_markup=back_to_menu_keyboard(), parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            text, reply_markup=back_to_menu_keyboard(), parse_mode='Markdown'
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "❓ *Помощь BrainBoost*\n\n"
        "*Команды:*\n"
        "/start — главное меню\n"
        "/buy — купить подписку\n"
        "/profile — профиль\n"
        "/referral — реферальная ссылка\n"
        "/help — эта справка\n\n"
        "*Как пользоваться:*\n"
        "1. Просто напиши вопрос боту\n"
        "2. Или открой *📋 Промты* — готовые шаблоны под задачи\n"
        "3. На пробном периоде — ограниченное число запросов\n"
        "4. Подписка даёт миллионы токенов на 30 дней\n\n"
        "*Оплата:*\n"
        "Карта UAH / EUR или USDT TRC20.\n"
        "После оплаты пришли скриншот — админ подтвердит вручную."
    )
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text, reply_markup=back_to_menu_keyboard(), parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            text, reply_markup=back_to_menu_keyboard(), parse_mode='Markdown'
        )


async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.pop('awaiting_ai', None)
    context.user_data.pop('awaiting_prompt_topic', None)
    context.user_data.pop('awaiting_prompt_vars', None)
    context.user_data.pop('selected_prompt_id', None)
    context.user_data.pop('prompt_var_values', None)
    context.user_data.pop('awaiting_screenshot', None)

    user = await ensure_user(update)
    remaining = get_remaining_tokens(user['user_id'])
    limit = get_tokens_limit(user['user_id'])
    welcome = get_setting('welcome_message', 'Привет! Я BrainBoost')

    text = (
        f"🧠 *BrainBoost*\n\n"
        f"{welcome}\n\n"
        f"📊 {format_status(user['subscription_status'])} | "
        f"🎟 {format_tokens(remaining)}/{format_tokens(limit)}\n\n"
        "Выбери действие или напиши вопрос:"
    )
    await query.edit_message_text(
        text,
        reply_markup=main_menu_keyboard(is_admin=is_admin(query.from_user.id)),
        parse_mode='Markdown',
    )


async def ask_ai_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if await check_maintenance(update):
        return

    user = await ensure_user(update)
    ok, msg = await check_access(user)
    if not ok:
        await query.edit_message_text(msg, reply_markup=back_to_menu_keyboard())
        return

    context.user_data['awaiting_ai'] = True
    await query.edit_message_text(
        "💬 *Напиши свой вопрос*\n\nЯ отвечу с помощью Claude AI.",
        reply_markup=cancel_keyboard(),
        parse_mode='Markdown',
    )


async def prompts_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if await check_maintenance(update):
        return

    context.user_data.pop('awaiting_prompt_vars', None)
    context.user_data.pop('awaiting_prompt_topic', None)
    context.user_data.pop('selected_prompt_id', None)
    context.user_data.pop('prompt_var_values', None)

    await query.edit_message_text(
        "📋 *Магазин промтов*\n\n"
        "Готовые шаблоны под задачи — выбери категорию:",
        reply_markup=prompts_categories_keyboard(),
        parse_mode='Markdown',
    )


async def user_category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    category = query.data.replace('user_cat_', '')
    if category == 'popular':
        prompts = get_popular_prompts(12)
        name = '🔥 Популярные'
    else:
        category = CATEGORY_ALIASES.get(category, category)
        prompts = get_prompts_by_category(category)
        name = CATEGORY_NAMES.get(category, category)

    if not prompts:
        await query.edit_message_text(
            f"В категории {name} пока нет промтов.",
            reply_markup=prompts_categories_keyboard(),
        )
        return

    await query.edit_message_text(
        f"{name}\n\nВыбери промт:",
        reply_markup=prompts_list_keyboard(prompts, category),
    )


async def prompt_use_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if await check_maintenance(update):
        return

    user = await ensure_user(update)
    ok, msg = await check_access(user)
    if not ok:
        await query.edit_message_text(msg, reply_markup=back_to_menu_keyboard())
        return

    prompt_id = int(query.data.replace('use_prompt_', ''))
    prompt = get_prompt(prompt_id)
    if not prompt or not prompt.get('is_active', 1):
        await query.edit_message_text("❌ Промт не найден", reply_markup=back_to_menu_keyboard())
        return

    variables = parse_prompt_variables(prompt)
    icon = prompt.get('icon') or '📌'
    title = prompt.get('title') or 'Промт'
    desc = prompt.get('description') or ''

    context.user_data['selected_prompt_id'] = prompt_id
    context.user_data['prompt_var_values'] = {}
    context.user_data.pop('awaiting_prompt_topic', None)

    if not variables:
        # Нет переменных — сразу выполняем
        context.user_data.pop('awaiting_prompt_vars', None)
        await query.edit_message_text(f"{icon} *{title}*\n\n⏳ Генерирую...", parse_mode='Markdown')
        await execute_store_prompt(update, context, prompt, {})
        return

    # Пошаговый ввод переменных
    context.user_data['awaiting_prompt_vars'] = variables
    first = variables[0]
    if desc:
        text = f"{icon} *{title}*\n\n{desc}\n\n"
    else:
        text = f"{icon} *{title}*\n\n"
    text += (
        f"✏️ *Шаг 1/{len(variables)}*\n"
        f"Введи: *{get_var_hint(first)}* (`{first}`)\n\n"
        f"Или одним сообщением через `|`:\n"
        f"`{' | '.join(variables)}`"
    )
    await query.edit_message_text(text, reply_markup=cancel_keyboard(), parse_mode='Markdown')


async def process_ai_request(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prompt_text: str,
    system_prompt=None,
    prompt_id=None,
):
    """Общая логика запроса к Claude с учётом лимитов"""
    user = await ensure_user(update)
    ok, msg = await check_access(user)
    if not ok:
        target = update.message or (update.callback_query.message if update.callback_query else None)
        if target:
            await target.reply_text(msg, reply_markup=back_to_menu_keyboard())
        return

    reply_target = update.message
    if not reply_target and update.callback_query:
        reply_target = update.callback_query.message

    wait_msg = await reply_target.reply_text("⏳ Думаю...")

    response_text, input_tokens, output_tokens = call_claude(
        prompt_text, system_prompt=system_prompt or SYSTEM_PROMPT
    )
    total_tokens = input_tokens + output_tokens

    if user['subscription_status'] != 'active':
        tokens_to_charge = 1
    else:
        tokens_to_charge = max(1, total_tokens)

    update_tokens_used(user['user_id'], tokens_to_charge)
    if prompt_id:
        increment_prompt_usage(prompt_id)
    log_action(
        user['user_id'],
        'request',
        f'in={input_tokens} out={output_tokens} charged={tokens_to_charge}'
        + (f' prompt={prompt_id}' if prompt_id else ''),
    )

    remaining = get_remaining_tokens(user['user_id'])

    chunks = []
    text = response_text
    while len(text) > 4000:
        chunks.append(text[:4000])
        text = text[4000:]
    chunks.append(text)

    try:
        await wait_msg.delete()
    except Exception:
        pass

    for i, chunk in enumerate(chunks):
        if i == len(chunks) - 1:
            footer = f"\n\n🎟 Осталось: {format_tokens(remaining)}"
            if len(chunk) + len(footer) < 4096:
                chunk += footer
        await reply_target.reply_text(chunk)


async def execute_store_prompt(update, context, prompt, var_dict):
    """Собрать шаблон магазина промтов и отправить в Claude"""
    template = prompt.get('prompt_text') or ''
    user_prompt = template
    for k, v in (var_dict or {}).items():
        user_prompt = user_prompt.replace('{' + str(k) + '}', str(v))

    system = prompt.get('system_prompt') or SYSTEM_PROMPT
    await process_ai_request(
        update, context, user_prompt,
        system_prompt=system,
        prompt_id=prompt.get('id'),
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    if await check_maintenance(update):
        return

    if await admin_text_handler(update, context):
        return

    if await handle_txid_text(update, context):
        return

    # Магазин промтов — ввод переменных
    if context.user_data.get('awaiting_prompt_vars'):
        await _handle_prompt_variables_input(update, context)
        return

    # Совместимость со старым флагом
    if context.user_data.get('awaiting_prompt_topic'):
        prompt_id = context.user_data.get('selected_prompt_id')
        prompt = get_prompt(prompt_id) if prompt_id else None
        context.user_data.pop('awaiting_prompt_topic', None)
        context.user_data.pop('selected_prompt_id', None)
        if not prompt:
            await update.message.reply_text("❌ Промт не найден", reply_markup=back_to_menu_keyboard())
            return
        await execute_store_prompt(update, context, prompt, {'topic': update.message.text.strip()})
        return

    text = update.message.text
    if not text or not text.strip():
        return

    context.user_data.pop('awaiting_ai', None)
    await process_ai_request(update, context, text.strip())


async def _handle_prompt_variables_input(update, context):
    variables = context.user_data.get('awaiting_prompt_vars') or []
    prompt_id = context.user_data.get('selected_prompt_id')
    prompt = get_prompt(prompt_id) if prompt_id else None
    if not prompt or not variables:
        context.user_data.pop('awaiting_prompt_vars', None)
        await update.message.reply_text("⚠️ Выбери промт заново из меню.", reply_markup=back_to_menu_keyboard())
        return

    raw = (update.message.text or '').strip()
    values = context.user_data.setdefault('prompt_var_values', {})

    # Ввод всех переменных через |
    if '|' in raw and len([v for v in raw.split('|') if v.strip()]) >= len(variables):
        parts = [v.strip() for v in raw.split('|')]
        if len(parts) < len(variables):
            await update.message.reply_text(
                f"❌ Нужно {len(variables)} значений через `|`.\n"
                f"Пример: `{' | '.join(['…'] * len(variables))}`",
                parse_mode='Markdown',
            )
            return
        for i, var in enumerate(variables):
            values[var] = parts[i]
        context.user_data.pop('awaiting_prompt_vars', None)
        context.user_data.pop('selected_prompt_id', None)
        context.user_data.pop('prompt_var_values', None)
        await update.message.reply_text("⏳ Генерирую по шаблону...")
        await execute_store_prompt(update, context, prompt, values)
        return

    # Пошаговый ввод
    next_var = None
    for var in variables:
        if var not in values:
            next_var = var
            break
    if not next_var:
        context.user_data.pop('awaiting_prompt_vars', None)
        await execute_store_prompt(update, context, prompt, values)
        return

    values[next_var] = raw
    remaining = [v for v in variables if v not in values]
    if remaining:
        step = len(variables) - len(remaining) + 1
        nxt = remaining[0]
        await update.message.reply_text(
            f"✅ Принято.\n\n"
            f"✏️ *Шаг {step}/{len(variables)}*\n"
            f"Введи: *{get_var_hint(nxt)}* (`{nxt}`)",
            parse_mode='Markdown',
            reply_markup=cancel_keyboard(),
        )
        return

    context.user_data.pop('awaiting_prompt_vars', None)
    context.user_data.pop('selected_prompt_id', None)
    context.user_data.pop('prompt_var_values', None)
    await update.message.reply_text("⏳ Генерирую по шаблону...")
    await execute_store_prompt(update, context, prompt, values)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Фото — скриншот оплаты или рассылка"""
    if context.user_data.get('admin_action') == 'broadcast':
        from admin_panel import broadcast_message
        await broadcast_message(update, context)
        return

    handled = await handle_screenshot(update, context)
    if not handled:
        await update.message.reply_text(
            "📸 Если это скриншот оплаты — сначала создай заказ через /buy и нажми «Я оплатил»."
        )


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('admin_action') == 'broadcast':
        from admin_panel import broadcast_message
        await broadcast_message(update, context)
        return
    await update.message.reply_text("📎 Файлы пока не обрабатываются. Напиши текст или выбери промт.")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎤 Голосовые пока не поддерживаются. Напиши текст."
    )


async def handle_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❓ Неизвестная команда. Используй /help или /start"
    )


async def buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await buy(update, context)


async def profile_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await profile(update, context)


async def referral_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await referral(update, context)


async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await help_command(update, context)


async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from admin_panel import admin_panel
    await admin_panel(update, context)
