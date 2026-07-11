from telegram import Update
from telegram.helpers import escape_markdown
from telegram.ext import ContextTypes

from config import ADMIN_IDS
from database import (
    get_user, create_user, get_remaining_tokens, get_tokens_limit,
    update_tokens_used, log_action, get_setting, get_user_by_referral_code,
    get_prompts_by_category, get_prompt, check_and_expire_subscriptions,
    get_popular_prompts, parse_prompt_variables, increment_prompt_usage,
    set_user_language, get_free_requests_remaining,
)
from claude_api import call_claude
from keyboards import (
    main_menu_keyboard, prompts_categories_keyboard, prompts_list_keyboard,
    back_to_menu_keyboard, cancel_keyboard, language_keyboard,
    result_keyboard,
)
from payment import buy, handle_screenshot, handle_txid_text
from admin_panel import admin_text_handler, is_admin
from prompts_data import CATEGORY_ALIASES
from utils import format_tokens, format_token_bar, is_true
from i18n import (
    SUPPORTED_LANGUAGES, t, detect_language, category_name, prompt_title,
    variable_hint, response_language_instruction,
)


SYSTEM_PROMPT = (
    "Ты — BrainBoost, умный AI-помощник. Отвечай полезно, конкретно и по делу. "
    "Пиши на языке пользователя. Если запрос неясен — уточни."
)


def user_language(user):
    return (user or {}).get('language') or 'en'


def localized_status(status, language):
    return t(language, f'status_{status}')


def build_home_text(user):
    language = user_language(user)
    remaining = get_remaining_tokens(user['user_id'])
    limit = get_tokens_limit(user['user_id'])
    is_pro = user['subscription_status'] == 'active'
    access = t(language, 'welcome_pro' if is_pro else 'welcome_trial')
    welcome_body = t(language, 'welcome_body')
    configured_welcome = get_setting('welcome_message', '')
    old_defaults = {
        'Привет! Я BrainBoost — твой AI-помощник',
        'Привет! Я BrainBoost',
    }
    if language == 'ru' and configured_welcome and configured_welcome not in old_defaults:
        welcome_body = escape_markdown(configured_welcome, version=1)
    usage_lines = (
        f"{t(language, 'tokens_left')}: "
        f"`{format_tokens(remaining)} / {format_tokens(limit)}`"
    )
    if not is_pro:
        request_limit = int(get_setting('free_requests', '10'))
        requests_left = get_free_requests_remaining(user['user_id'])
        usage_lines = (
            f"{t(language, 'requests_left')}: `{requests_left} / {request_limit}`\n"
            f"{t(language, 'tokens_left')}: "
            f"`{format_tokens(remaining)} / {format_tokens(limit)}`"
        )
    return (
        f"{t(language, 'welcome_title')}\n"
        f"_{t(language, 'welcome_subtitle')}_\n\n"
        f"{welcome_body}\n\n"
        f"◇ *{access}*\n"
        f"{usage_lines}\n\n"
        f"*{t(language, 'choose_action')}*"
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
            language=detect_language(tg_user.language_code),
        )
        user = get_user(tg_user.id)
    return user


async def check_maintenance(update: Update):
    """Проверка режима обслуживания (админы проходят)"""
    if is_true(get_setting('maintenance_mode', 'false')):
        if update.effective_user.id not in ADMIN_IDS:
            user = get_user(update.effective_user.id)
            text = t(user_language(user), 'maintenance')
            if update.message:
                await update.message.reply_text(text)
            elif update.callback_query:
                await update.callback_query.answer(text, show_alert=True)
            return True
    return False


async def check_access(user):
    """Проверка доступа: не заблокирован и есть токены"""
    check_and_expire_subscriptions()
    fresh_user = get_user(user['user_id'])
    if fresh_user:
        user.clear()
        user.update(fresh_user)
    if user['subscription_status'] == 'blocked':
        return False, t(user_language(user), 'blocked')
    if user['subscription_status'] == 'expired':
        return False, t(user_language(user), 'subscription_expired')
    remaining = get_remaining_tokens(user['user_id'])
    if user['subscription_status'] == 'trial':
        free_requests = get_free_requests_remaining(user['user_id'])
        request_cost = int(get_setting('free_request_cost', '100000'))
        if free_requests <= 0 or remaining < request_cost:
            return False, t(user_language(user), 'trial_exhausted')
    if remaining <= 0:
        if user['subscription_status'] == 'active':
            return False, t(user_language(user), 'pro_exhausted')
        return False, t(user_language(user), 'trial_exhausted')
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
            language=detect_language(tg_user.language_code),
        )
        user = get_user(tg_user.id)
        log_action(tg_user.id, 'start', f'ref={referred_by}')
    else:
        log_action(tg_user.id, 'start', 'returning')

    if not user.get('language_selected'):
        language = detect_language(tg_user.language_code)
        await update.message.reply_text(
            t(language, 'select_language'),
            reply_markup=language_keyboard(),
            parse_mode='Markdown',
        )
        return

    language = user_language(user)
    await update.message.reply_text(
        build_home_text(user),
        reply_markup=main_menu_keyboard(is_admin=is_admin(tg_user.id), language=language),
        parse_mode='Markdown',
    )


async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await ensure_user(update)
    language = user_language(user)
    text = t(language, 'select_language')
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text, reply_markup=language_keyboard(back=True), parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            text, reply_markup=language_keyboard(back=True), parse_mode='Markdown'
        )


async def language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    language = query.data.replace('lang_', '')
    if language not in SUPPORTED_LANGUAGES:
        language = 'en'
    user = await ensure_user(update)
    set_user_language(user['user_id'], language)
    user = get_user(user['user_id'])
    await query.edit_message_text(
        f"{t(language, 'language_changed')}\n\n{build_home_text(user)}",
        reply_markup=main_menu_keyboard(
            is_admin=is_admin(user['user_id']), language=language
        ),
        parse_mode='Markdown',
    )


async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_maintenance(update):
        return

    user = await ensure_user(update)
    language = user_language(user)
    remaining = get_remaining_tokens(user['user_id'])
    limit = get_tokens_limit(user['user_id'])

    used = user['tokens_used'] or 0
    percent = round((used / limit) * 100, 1) if limit > 0 else 0

    if user['subscription_status'] == 'active':
        text = (
            f"{t(language, 'profile_title')}\n\n"
            f"◇ *{localized_status('active', language)}*\n"
            f"{t(language, 'profile_valid_until')}: "
            f"`{user['subscription_end_date'] or t(language, 'not_set')}`\n"
            f"{t(language, 'profile_available')}: `{format_tokens(remaining)}`"
        )
    else:
        request_limit = int(get_setting('free_requests', '10'))
        requests_left = get_free_requests_remaining(user['user_id'])
        text = (
            f"{t(language, 'profile_title')}\n\n"
            f"◇ *{t(language, 'profile_plan')}*\n"
            f"{localized_status(user['subscription_status'], language)}\n\n"
            f"◇ *{t(language, 'profile_usage')}*\n"
            f"{format_token_bar(percent)}\n"
            f"{t(language, 'requests_left')}: `{requests_left} / {request_limit}`\n"
            f"{t(language, 'profile_used')}: `{format_tokens(used)}`\n"
            f"{t(language, 'profile_available')}: "
            f"`{format_tokens(remaining)} / {format_tokens(limit)}`\n\n"
            f"{t(language, 'profile_id')}: `{user['user_id']}`"
        )

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text, reply_markup=back_to_menu_keyboard(language), parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            text, reply_markup=back_to_menu_keyboard(language), parse_mode='Markdown'
        )


async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_maintenance(update):
        return

    user = await ensure_user(update)
    language = user_language(user)
    bot_info = await context.bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={user['referral_code']}"
    bonus = format_tokens(int(get_setting('referral_bonus', '5000000')))
    max_refs = get_setting('max_referrals', '5')

    text = (
        f"{t(language, 'ref_title')}\n\n"
        f"{t(language, 'ref_body', bonus=bonus)}\n\n"
        f"◇ *{t(language, 'ref_progress')}*\n"
        f"`{user['total_referrals']} / {max_refs}`\n\n"
        f"◇ *{t(language, 'ref_link')}*\n"
        f"`{link}`\n\n"
        f"_{t(language, 'ref_note', max_refs=max_refs)}_"
    )

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text, reply_markup=back_to_menu_keyboard(language), parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            text, reply_markup=back_to_menu_keyboard(language), parse_mode='Markdown'
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await ensure_user(update)
    language = user_language(user)
    text = (
        f"{t(language, 'help_title')}\n\n"
        f"{t(language, 'help_body')}\n\n"
        f"◇ *BrainBoost Pro*\n"
        f"{t(language, 'help_payment')}"
    )
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text, reply_markup=back_to_menu_keyboard(language), parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            text, reply_markup=back_to_menu_keyboard(language), parse_mode='Markdown'
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
    language = user_language(user)
    await query.edit_message_text(
        build_home_text(user),
        reply_markup=main_menu_keyboard(
            is_admin=is_admin(query.from_user.id), language=language
        ),
        parse_mode='Markdown',
    )


async def ask_ai_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if await check_maintenance(update):
        return

    user = await ensure_user(update)
    language = user_language(user)
    ok, msg = await check_access(user)
    if not ok:
        await query.edit_message_text(msg, reply_markup=back_to_menu_keyboard(language))
        return

    context.user_data['awaiting_ai'] = True
    await query.edit_message_text(
        f"{t(language, 'ask_title')}\n\n"
        f"{t(language, 'ask_body')}\n\n"
        f"{t(language, 'ask_examples')}",
        reply_markup=cancel_keyboard(language),
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

    user = await ensure_user(update)
    language = user_language(user)
    await query.edit_message_text(
        f"{t(language, 'prompt_store_title')}\n\n"
        f"{t(language, 'prompt_store_body')}",
        reply_markup=prompts_categories_keyboard(language),
        parse_mode='Markdown',
    )


async def user_category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = await ensure_user(update)
    language = user_language(user)

    category = query.data.replace('user_cat_', '')
    if category == 'popular':
        prompts = get_popular_prompts(12)
        name = t(language, 'popular')
    else:
        category = CATEGORY_ALIASES.get(category, category)
        prompts = get_prompts_by_category(category)
        name = category_name(category, language)

    if not prompts:
        await query.edit_message_text(
            t(language, 'no_prompts'),
            reply_markup=prompts_categories_keyboard(language),
        )
        return

    await query.edit_message_text(
        f"*{name}*\n\n{t(language, 'choose_prompt')}",
        reply_markup=prompts_list_keyboard(prompts, category, language),
        parse_mode='Markdown',
    )


async def prompt_use_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if await check_maintenance(update):
        return

    user = await ensure_user(update)
    language = user_language(user)
    ok, msg = await check_access(user)
    if not ok:
        await query.edit_message_text(msg, reply_markup=back_to_menu_keyboard(language))
        return

    prompt_id = int(query.data.replace('use_prompt_', ''))
    prompt = get_prompt(prompt_id)
    if not prompt or not prompt.get('is_active', 1):
        await query.edit_message_text(
            t(language, 'prompt_not_found'),
            reply_markup=back_to_menu_keyboard(language),
        )
        return

    variables = parse_prompt_variables(prompt)
    icon = prompt.get('icon') or '📌'
    title = prompt_title(prompt.get('title') or 'Prompt', language)

    context.user_data['selected_prompt_id'] = prompt_id
    context.user_data['prompt_var_values'] = {}
    context.user_data.pop('awaiting_prompt_topic', None)

    if not variables:
        # Нет переменных — сразу выполняем
        context.user_data.pop('awaiting_prompt_vars', None)
        await query.edit_message_text(
            f"{icon} *{title}*\n\n{t(language, 'generating')}",
            parse_mode='Markdown',
        )
        await execute_store_prompt(update, context, prompt, {})
        return

    # Пошаговый ввод переменных
    context.user_data['awaiting_prompt_vars'] = variables
    first = variables[0]
    text = f"{icon} *{title}*\n\n"
    text += (
        f"◇ *{t(language, 'prompt_step', step=1, total=len(variables))}*\n"
        f"{t(language, 'prompt_enter', hint=variable_hint(first, language))}\n\n"
        f"{t(language, 'prompt_fast', variables=' | '.join(variables))}"
    )
    await query.edit_message_text(
        text, reply_markup=cancel_keyboard(language), parse_mode='Markdown'
    )


async def process_ai_request(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prompt_text: str,
    system_prompt=None,
    prompt_id=None,
):
    """Общая логика запроса к Claude с учётом лимитов"""
    user = await ensure_user(update)
    language = user_language(user)
    ok, msg = await check_access(user)
    if not ok:
        target = update.message or (update.callback_query.message if update.callback_query else None)
        if target:
            await target.reply_text(msg, reply_markup=back_to_menu_keyboard(language))
        return

    reply_target = update.message
    if not reply_target and update.callback_query:
        reply_target = update.callback_query.message

    wait_msg = await reply_target.reply_text(t(language, 'thinking'))

    localized_system = (
        f"{system_prompt or SYSTEM_PROMPT}\n\n"
        f"{response_language_instruction(language)}"
    )
    response_text, input_tokens, output_tokens = call_claude(
        prompt_text, system_prompt=localized_system
    )
    total_tokens = input_tokens + output_tokens

    call_failed = (
        total_tokens == 0
        and response_text.lstrip().startswith(('⚠️', '❌', '⏰'))
    )
    if call_failed:
        provider_error = response_text
        response_text = t(language, 'ai_unavailable')
    else:
        if user['subscription_status'] == 'active':
            tokens_to_charge = max(1, total_tokens)
            update_tokens_used(user['user_id'], tokens_to_charge)
        else:
            tokens_to_charge = int(get_setting('free_request_cost', '100000'))
            update_tokens_used(
                user['user_id'], tokens_to_charge, count_free_request=True
            )
        if prompt_id:
            increment_prompt_usage(prompt_id)
        log_action(
            user['user_id'],
            'request',
            f'in={input_tokens} out={output_tokens} charged={tokens_to_charge}'
            + (f' prompt={prompt_id}' if prompt_id else ''),
        )
    if call_failed:
        log_action(user['user_id'], 'request_error', provider_error[:500])

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
            footer = (
                f"\n\n◇ {t(language, 'result_footer')}: "
                f"{format_tokens(remaining)}"
            )
            if len(chunk) + len(footer) < 4096:
                chunk += footer
        reply_markup = result_keyboard(language) if i == len(chunks) - 1 else None
        await reply_target.reply_text(chunk, reply_markup=reply_markup)


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

    if context.user_data.get('awaiting_screenshot'):
        user = await ensure_user(update)
        await update.message.reply_text(
            t(user_language(user), 'waiting_receipt'),
            reply_markup=cancel_keyboard(user_language(user)),
        )
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
            user = await ensure_user(update)
            language = user_language(user)
            await update.message.reply_text(
                t(language, 'prompt_not_found'),
                reply_markup=back_to_menu_keyboard(language),
            )
            return
        await execute_store_prompt(update, context, prompt, {'topic': update.message.text.strip()})
        return

    text = update.message.text
    if not text or not text.strip():
        return

    context.user_data.pop('awaiting_ai', None)
    await process_ai_request(update, context, text.strip())


async def _handle_prompt_variables_input(update, context):
    user = await ensure_user(update)
    language = user_language(user)
    variables = context.user_data.get('awaiting_prompt_vars') or []
    prompt_id = context.user_data.get('selected_prompt_id')
    prompt = get_prompt(prompt_id) if prompt_id else None
    if not prompt or not variables:
        context.user_data.pop('awaiting_prompt_vars', None)
        await update.message.reply_text(
            t(language, 'restart_prompt'),
            reply_markup=back_to_menu_keyboard(language),
        )
        return

    raw = (update.message.text or '').strip()
    values = context.user_data.setdefault('prompt_var_values', {})

    # Ввод всех переменных через |
    if '|' in raw and len([v for v in raw.split('|') if v.strip()]) >= len(variables):
        parts = [v.strip() for v in raw.split('|')]
        if len(parts) < len(variables):
            await update.message.reply_text(
                t(
                    language,
                    'prompt_fast',
                    variables=' | '.join(['…'] * len(variables)),
                ),
                parse_mode='Markdown',
            )
            return
        for i, var in enumerate(variables):
            values[var] = parts[i]
        context.user_data.pop('awaiting_prompt_vars', None)
        context.user_data.pop('selected_prompt_id', None)
        context.user_data.pop('prompt_var_values', None)
        await update.message.reply_text(t(language, 'generating'))
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
            f"{t(language, 'accepted')}\n\n"
            f"◇ *{t(language, 'prompt_step', step=step, total=len(variables))}*\n"
            f"{t(language, 'prompt_enter', hint=variable_hint(nxt, language))}",
            parse_mode='Markdown',
            reply_markup=cancel_keyboard(language),
        )
        return

    context.user_data.pop('awaiting_prompt_vars', None)
    context.user_data.pop('selected_prompt_id', None)
    context.user_data.pop('prompt_var_values', None)
    await update.message.reply_text(t(language, 'generating'))
    await execute_store_prompt(update, context, prompt, values)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Фото — скриншот оплаты или рассылка"""
    if context.user_data.get('admin_action') == 'broadcast':
        from admin_panel import broadcast_message
        await broadcast_message(update, context)
        return

    handled = await handle_screenshot(update, context)
    if not handled:
        user = await ensure_user(update)
        await update.message.reply_text(t(user_language(user), 'photo_hint'))


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('admin_action') == 'broadcast':
        from admin_panel import broadcast_message
        await broadcast_message(update, context)
        return
    user = await ensure_user(update)
    await update.message.reply_text(t(user_language(user), 'file_unsupported'))


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await ensure_user(update)
    await update.message.reply_text(t(user_language(user), 'voice_unsupported'))


async def handle_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await ensure_user(update)
    await update.message.reply_text(t(user_language(user), 'unknown_command'))


async def buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await buy(update, context)


async def profile_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await profile(update, context)


async def referral_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await referral(update, context)


async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await help_command(update, context)


async def language_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await language_command(update, context)


async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from admin_panel import admin_panel
    await admin_panel(update, context)
