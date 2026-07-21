import asyncio
import os
import tempfile
import time
from datetime import datetime

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from config import ADMIN_IDS
from database import (
    get_user, create_user, get_remaining_tokens, get_tokens_limit,
    update_tokens_used, log_action, get_setting, get_user_by_referral_code,
    get_prompts_by_category, get_prompt, check_and_expire_subscriptions,
    get_popular_prompts, parse_prompt_variables, increment_prompt_usage,
    set_user_language, get_free_requests_remaining, get_category_counts,
    touch_user_activity, mark_trial_limit_hit, get_setting_int,
    get_user_pending_payment,
)
from claude_api import call_claude
from keyboards import (
    main_menu_keyboard, prompts_categories_keyboard, prompts_list_keyboard,
    back_to_menu_keyboard, back_to_more_keyboard, more_menu_keyboard,
    cancel_keyboard, language_keyboard, result_keyboard,
)
from payment import (
    buy, handle_screenshot, handle_txid_text,
    build_buy_text, buy_plans_keyboard,
)
from admin_panel import admin_text_handler, is_admin
from prompts_data import CATEGORY_ALIASES, PREMIUM_CATEGORIES
from enrichment import (
    ALLOWED_FILE_EXTS, MAX_FILE_MB, MAX_URLS_PER_MESSAGE,
    extract_urls, fetch_url_text, extract_file_text, dynamic_context,
)
from utils import format_tokens, format_token_bar, is_true, clean_ai_text
from i18n import (
    SUPPORTED_LANGUAGES, t, detect_language, category_name, prompt_title,
    variable_hint, response_language_instruction, thinking_phases,
)


SYSTEM_PROMPT = (
    "Ты — BrainBoost, умный AI-помощник. Отвечай полезно, конкретно и по делу. "
    "Пиши на языке пользователя. Если запрос неясен — уточни."
)

# Ответы отправляются в Telegram обычным текстом — Markdown-символы выглядят как мусор
FORMAT_INSTRUCTION = (
    "Format the reply as plain text for a Telegram chat: no Markdown symbols "
    "(no **, ##, backticks, no *bullets*). Use short paragraphs, emoji as "
    "section markers where helpful, and '•' for list items."
)


def _multi_step_generate(prompt_text, system_prompt):
    """Трёхшаговая генерация: структура → контент → проверка.

    Выполняется в рабочем потоке. Возвращает (text, in_tokens, out_tokens);
    при сбое любого шага — ответ этого шага как есть (ошибку распознает
    вызывающий код по нулевым токенам).
    """
    total_in = 0
    total_out = 0

    outline, i1, o1 = call_claude(
        "Create a detailed outline for the response to the task below. "
        "Output only the outline, no extra commentary.\n\n"
        f"Task:\n{prompt_text}",
        system_prompt=system_prompt,
    )
    if i1 + o1 == 0:
        return outline, 0, 0
    total_in += i1
    total_out += o1

    draft, i2, o2 = call_claude(
        f"Task:\n{prompt_text}\n\n"
        "Follow this outline and write the complete, polished result:\n"
        f"{outline}",
        system_prompt=system_prompt,
    )
    if i2 + o2 == 0:
        return draft, 0, 0
    total_in += i2
    total_out += o2

    final, i3, o3 = call_claude(
        "Review the result below for factual errors, inconsistencies and "
        "mistakes. Fix everything you find and output only the final "
        "corrected version, without commentary.\n\n"
        f"Task:\n{prompt_text}\n\nResult:\n{draft}",
        system_prompt=system_prompt,
    )
    if i3 + o3 == 0:
        # Проверка не удалась — черновик двух успешных шагов лучше, чем ошибка
        return draft, total_in, total_out
    return final, total_in + i3, total_out + o3


def user_language(user):
    return (user or {}).get('language') or 'en'


def localized_status(status, language):
    return t(language, f'status_{status}')


def _pro_days_left(user):
    """Сколько дней осталось у активной подписки (None если нет даты)"""
    end_date = user.get('subscription_end_date')
    if not end_date:
        return None
    try:
        end = datetime.strptime(str(end_date)[:10], '%Y-%m-%d')
    except ValueError:
        return None
    return max(0, (end - datetime.now()).days + 1)


def build_home_text(user):
    language = user_language(user)
    remaining = get_remaining_tokens(user['user_id'])
    limit = get_tokens_limit(user['user_id'])
    is_pro = user['subscription_status'] == 'active'
    if is_pro:
        access = t(language, 'welcome_pro')
        days_left = _pro_days_left(user)
        if days_left is not None:
            access = f"{access} · {t(language, 'pro_days_left', days=days_left)}"
        status_lines = (
            f"◇ *{access}*\n"
            f"{t(language, 'tokens_left')}: "
            f"`{format_tokens(remaining)} / {format_tokens(limit)}`"
        )
    else:
        request_limit = int(get_setting('free_requests', '3'))
        requests_left = get_free_requests_remaining(user['user_id'])
        status_lines = (
            f"*{t(language, 'home_free_left', left=requests_left, total=request_limit)}*"
        )
    return (
        f"{t(language, 'welcome_title')}\n\n"
        f"{t(language, 'home_workspace')}\n"
        f"{status_lines}\n\n"
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
    touch_user_activity(tg_user.id)
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
    """Проверка доступа. Возвращает (ok, message, reason)."""
    check_and_expire_subscriptions()
    fresh_user = get_user(user['user_id'])
    if fresh_user:
        user.clear()
        user.update(fresh_user)
    if user['subscription_status'] == 'blocked':
        return False, t(user_language(user), 'blocked'), 'blocked'
    if user['subscription_status'] == 'expired':
        return False, t(user_language(user), 'subscription_expired'), 'expired'
    remaining = get_remaining_tokens(user['user_id'])
    if user['subscription_status'] == 'trial':
        free_requests = get_free_requests_remaining(user['user_id'])
        request_cost = get_setting_int('free_request_cost', 100000)
        if free_requests <= 0 or remaining < request_cost:
            return False, t(user_language(user), 'trial_exhausted'), 'trial_exhausted'
    if remaining <= 0:
        if user['subscription_status'] == 'active':
            return False, t(user_language(user), 'pro_exhausted'), 'pro_exhausted'
        return False, t(user_language(user), 'trial_exhausted'), 'trial_exhausted'
    return True, None, None


async def send_access_paywall(update, language, user_id=None, reason='trial_exhausted'):
    """Единый paywall для trial_exhausted / expired / pro_exhausted"""
    if user_id and reason == 'trial_exhausted':
        mark_trial_limit_hit(user_id)
    text = build_buy_text(language, mode='limit', user_id=user_id)
    keyboard = buy_plans_keyboard(language)
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text, reply_markup=keyboard, parse_mode='Markdown'
            )
        except Exception:
            await update.callback_query.message.reply_text(
                text, reply_markup=keyboard, parse_mode='Markdown'
            )
    elif update.message:
        await update.message.reply_text(
            text, reply_markup=keyboard, parse_mode='Markdown'
        )


async def send_limit_locked(update, language, user_id=None):
    """Экран блокировки: лимит исчерпан → тарифы Pro (якорь 3 мес)"""
    await send_access_paywall(update, language, user_id, 'trial_exhausted')


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_maintenance(update):
        return

    check_and_expire_subscriptions()
    tg_user = update.effective_user
    user = get_user(tg_user.id)

    referred_by = None
    referer = None
    if context.args:
        arg = context.args[0].strip()[:64]
        referrer = get_user_by_referral_code(arg)
        if referrer and referrer['user_id'] != tg_user.id:
            referred_by = referrer['user_id']
        elif arg:
            # Не реферальный код — считаем UTM-меткой рекламного канала
            referer = arg

    if not user:
        create_user(
            tg_user.id,
            tg_user.username,
            tg_user.first_name,
            referred_by=referred_by,
            last_name=tg_user.last_name,
            language=detect_language(tg_user.language_code),
            referer=referer,
        )
        user = get_user(tg_user.id)
        log_action(tg_user.id, 'start', f'ref={referred_by} utm={referer}')
    else:
        log_action(tg_user.id, 'start', 'returning')
    touch_user_activity(tg_user.id)

    if not user.get('language_selected'):
        language = detect_language(tg_user.language_code)
        await update.message.reply_text(
            t(language, 'select_language'),
            reply_markup=language_keyboard(),
            parse_mode='Markdown',
        )
        return

    language = user_language(user)
    welcome = (get_setting('welcome_message', '') or '').strip()
    home = build_home_text(user)
    text = f"{welcome}\n\n{home}" if welcome else home
    await update.message.reply_text(
        text,
        reply_markup=main_menu_keyboard(is_admin=is_admin(tg_user.id), language=language),
        parse_mode='Markdown',
    )


async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_maintenance(update):
        return
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
    language = query.data.replace('lang_', '')
    if language not in SUPPORTED_LANGUAGES:
        language = 'en'
    await query.answer(t(language, 'language_changed'))
    user = await ensure_user(update)
    first_time = not user.get('language_selected')
    set_user_language(user['user_id'], language)
    user = get_user(user['user_id'])

    if first_time:
        # Двухтактный онбординг: интро → пауза с "печатает…" → главный экран
        await query.edit_message_text(
            t(language, 'onboarding_intro'), parse_mode='Markdown'
        )
        try:
            await context.bot.send_chat_action(
                chat_id=query.message.chat_id, action=ChatAction.TYPING
            )
        except Exception:
            pass
        await asyncio.sleep(1.2)
        await query.message.reply_text(
            build_home_text(user),
            reply_markup=main_menu_keyboard(
                is_admin=is_admin(user['user_id']), language=language
            ),
            parse_mode='Markdown',
        )
        return

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
        request_limit = int(get_setting('free_requests', '3'))
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
        await update.callback_query.answer(t(language, 'toast_profile'))
        await update.callback_query.edit_message_text(
            text, reply_markup=back_to_more_keyboard(language), parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            text, reply_markup=back_to_more_keyboard(language), parse_mode='Markdown'
        )


async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_maintenance(update):
        return

    user = await ensure_user(update)
    language = user_language(user)
    bot_info = await context.bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={user['referral_code']}"
    bonus = format_tokens(get_setting_int('referral_bonus', 5000000))
    max_refs = get_setting_int('max_referrals', 5)

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
        await update.callback_query.answer(t(language, 'toast_referral'))
        await update.callback_query.edit_message_text(
            text, reply_markup=back_to_more_keyboard(language), parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            text, reply_markup=back_to_more_keyboard(language), parse_mode='Markdown'
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_maintenance(update):
        return
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
            text, reply_markup=back_to_more_keyboard(language), parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            text, reply_markup=back_to_more_keyboard(language), parse_mode='Markdown'
        )


async def more_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_maintenance(update):
        return
    query = update.callback_query
    user = await ensure_user(update)
    language = user_language(user)
    await query.answer(t(language, 'toast_more'))
    text = f"{t(language, 'more_title')}\n\n{t(language, 'more_body')}"
    await query.edit_message_text(
        text, reply_markup=more_menu_keyboard(language), parse_mode='Markdown'
    )


async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = await ensure_user(update)
    await query.answer(t(user_language(user), 'toast_home'))
    context.user_data.pop('awaiting_ai', None)
    context.user_data.pop('awaiting_prompt_topic', None)
    context.user_data.pop('awaiting_prompt_vars', None)
    context.user_data.pop('selected_prompt_id', None)
    context.user_data.pop('prompt_var_values', None)
    context.user_data.pop('awaiting_screenshot', None)
    context.user_data.pop('admin_action', None)
    context.user_data.pop('broadcast_from_chat', None)
    context.user_data.pop('broadcast_message_id', None)
    context.user_data.pop('broadcast_preview', None)
    context.user_data.pop('pending_order_id', None)

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
    user = await ensure_user(update)
    language = user_language(user)
    if await check_maintenance(update):
        return
    await query.answer(t(language, 'toast_ask'))

    ok, msg, reason = await check_access(user)
    if not ok:
        if reason in ('trial_exhausted', 'expired', 'pro_exhausted'):
            await send_access_paywall(update, language, user['user_id'], reason)
        else:
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
    user = await ensure_user(update)
    language = user_language(user)
    if await check_maintenance(update):
        return
    await query.answer(t(language, 'toast_library'))

    context.user_data.pop('awaiting_prompt_vars', None)
    context.user_data.pop('awaiting_prompt_topic', None)
    context.user_data.pop('selected_prompt_id', None)
    context.user_data.pop('prompt_var_values', None)


    text = f"{t(language, 'prompt_store_title')}\n\n{t(language, 'prompt_store_body')}"
    top = get_popular_prompts(3)
    if top:
        lines = [
            f"{p.get('icon') or '📌'} {prompt_title(p.get('title') or 'Prompt', language)}"
            for p in top
        ]
        text += f"\n\n*{t(language, 'top_prompts_label')}*\n" + "\n".join(lines)

    await query.edit_message_text(
        text,
        reply_markup=prompts_categories_keyboard(
            language, get_category_counts(), is_pro=_has_pro_access(user)
        ),
        parse_mode='Markdown',
    )


def _has_pro_access(user):
    """Pro-доступ: активная подписка или админ"""
    return (
        user['subscription_status'] == 'active'
        or is_admin(user['user_id'])
    )


async def send_category_locked(query, language, category=None):
    """Экран продаж при клике на закрытую категорию: тизер инструментов + тарифы"""
    teaser = ''
    if category:
        prompts = get_prompts_by_category(category)
        if prompts:
            name = category_name(category, language)
            lines = [
                f"🔒 {p.get('icon') or '📌'} "
                f"{prompt_title(p.get('title') or 'Prompt', language)}"
                for p in prompts[:4]
            ]
            rest = len(prompts) - 4
            if rest > 0:
                lines.append(t(language, 'locked_more_tools', n=rest))
            teaser = (
                f"*{t(language, 'locked_preview', category=name)}*\n"
                + '\n'.join(lines) + '\n\n'
            )
    await query.edit_message_text(
        f"{teaser}{build_buy_text(language, mode='locked')}",
        reply_markup=buy_plans_keyboard(language),
        parse_mode='Markdown',
    )


async def user_category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = await ensure_user(update)
    language = user_language(user)

    category = query.data.replace('user_cat_', '')
    if category == 'popular':
        await query.answer()
        prompts = get_popular_prompts(12)
        name = t(language, 'popular')
    else:
        category = CATEGORY_ALIASES.get(category, category)
        if category in PREMIUM_CATEGORIES and not _has_pro_access(user):
            await query.answer('🔒 Pro')
            await send_category_locked(query, language, category)
            return
        await query.answer()
        prompts = get_prompts_by_category(category)
        name = category_name(category, language)

    if not prompts:
        await query.edit_message_text(
            t(language, 'no_prompts'),
            reply_markup=prompts_categories_keyboard(
                language, get_category_counts(), is_pro=_has_pro_access(user)
            ),
        )
        return

    await query.edit_message_text(
        f"*{name}* · {len(prompts)}\n\n{t(language, 'choose_prompt')}",
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
    ok, msg, reason = await check_access(user)
    if not ok:
        if reason in ('trial_exhausted', 'expired', 'pro_exhausted'):
            await send_access_paywall(update, language, user['user_id'], reason)
        else:
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

    # Сценарии премиальных категорий (в т.ч. из «Популярного») — только для Pro
    if prompt.get('category') in PREMIUM_CATEGORIES and not _has_pro_access(user):
        await send_category_locked(query, language, prompt.get('category'))
        return

    variables = parse_prompt_variables(prompt)
    icon = prompt.get('icon') or '📌'
    title = prompt_title(prompt.get('title') or 'Prompt', language)

    context.user_data['selected_prompt_id'] = prompt_id
    context.user_data['prompt_var_values'] = {}
    context.user_data.pop('awaiting_prompt_topic', None)

    if not variables:
        # Нет переменных — сразу выполняем (анимация ожидания появится ниже)
        context.user_data.pop('awaiting_prompt_vars', None)
        await query.edit_message_text(
            f"{icon} *{title}*", parse_mode='Markdown',
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


def _thinking_frame(phase_text, progress, width=8):
    bar = '▰' * progress + '▱' * (width - progress)
    return f"{phase_text}\n{bar}"


async def _animate_thinking(bot, wait_msg, language, category=None):
    """Живое сообщение ожидания: фазы + прогресс-бар + chat action «печатает…»"""
    phases = thinking_phases(language, category)
    width = 8
    tick = 0
    # Начальное сообщение уже показывает первый кадр — не редактируем его повторно
    last_text = _thinking_frame(phases[0], 1, width)
    while True:
        try:
            await bot.send_chat_action(
                chat_id=wait_msg.chat_id, action=ChatAction.TYPING
            )
        except Exception:
            pass
        # Фазы: 0-1 тик — анализ, 2-4 — середина, дальше — написание
        if tick < 2:
            phase = phases[0]
        elif tick < 5:
            phase = phases[1]
        else:
            phase = phases[2]
        # Прогресс растёт, но не доходит до конца, пока нет ответа
        progress = min(width - 1, 1 + tick)
        text = _thinking_frame(phase, progress, width)
        if text != last_text:
            try:
                await wait_msg.edit_text(text)
                last_text = text
            except Exception:
                pass
        tick += 1
        await asyncio.sleep(2)


async def process_ai_request(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prompt_text: str,
    system_prompt=None,
    prompt_id=None,
    multi_step=False,
):
    """Общая логика запроса к Claude с учётом лимитов"""
    user = await ensure_user(update)
    language = user_language(user)
    ok, msg, reason = await check_access(user)
    if not ok:
        # Исчерпанный лимит: система заблокирована, показываем тарифы
        if reason in ('trial_exhausted', 'expired', 'pro_exhausted'):
            mark_trial_limit_hit(user['user_id']) if reason == 'trial_exhausted' else None
            target = update.message or (update.callback_query.message if update.callback_query else None)
            if target:
                await target.reply_text(
                    build_buy_text(language, mode='limit', user_id=user['user_id']),
                    reply_markup=buy_plans_keyboard(language),
                    parse_mode='Markdown',
                )
            return
        target = update.message or (update.callback_query.message if update.callback_query else None)
        if target:
            await target.reply_text(msg, reply_markup=back_to_menu_keyboard(language))
        return

    reply_target = update.message
    if not reply_target and update.callback_query:
        reply_target = update.callback_query.message

    # Категория и название сценария нужны заранее — для тематических фаз и шапки карточки
    category = None
    scenario_title = None
    if prompt_id:
        source_prompt = get_prompt(prompt_id)
        if source_prompt:
            category = source_prompt.get('category')
            scenario_title = prompt_title(
                source_prompt.get('title') or '', language
            ) or None

    wait_msg = await reply_target.reply_text(
        _thinking_frame(thinking_phases(language, category)[0], 1)
    )
    anim_task = asyncio.create_task(
        _animate_thinking(context.bot, wait_msg, language, category)
    )

    live_context = await asyncio.to_thread(dynamic_context, prompt_text)
    localized_system = (
        f"{system_prompt or SYSTEM_PROMPT}\n\n"
        f"{live_context}\n"
        f"{response_language_instruction(language)}\n"
        f"{FORMAT_INSTRUCTION}"
    )
    # Многошаговая генерация — только для Pro (кратно дороже по токенам)
    use_multi_step = multi_step and user['subscription_status'] == 'active'
    started_at = time.monotonic()
    try:
        if use_multi_step:
            response_text, input_tokens, output_tokens = await asyncio.to_thread(
                _multi_step_generate, prompt_text, localized_system
            )
        else:
            response_text, input_tokens, output_tokens = await asyncio.to_thread(
                call_claude, prompt_text, system_prompt=localized_system
            )
    finally:
        anim_task.cancel()
        try:
            await anim_task
        except asyncio.CancelledError:
            pass
    elapsed_seconds = max(1, int(time.monotonic() - started_at))
    total_tokens = input_tokens + output_tokens

    call_failed = (
        total_tokens == 0
        and response_text.lstrip().startswith(('⚠️', '❌', '⏰'))
    )
    if call_failed:
        provider_error = response_text
        response_text = t(language, 'ai_unavailable')
    else:
        response_text = clean_ai_text(response_text)
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
    is_pro_user = user['subscription_status'] == 'active'

    show_upgrade = False
    requests_left_after = None
    used_before = None
    if not call_failed and not is_pro_user:
        requests_left_after = get_free_requests_remaining(user['user_id'])
        total_free = int(get_setting('free_requests', '3'))
        used_before = max(0, total_free - (requests_left_after or 0))
        # CTA после каждого trial-ответа
        show_upgrade = True
        if requests_left_after is not None and requests_left_after <= 0:
            mark_trial_limit_hit(user['user_id'])

    # Для триала показываем остаток операций, для Pro — баланс токенов
    if is_pro_user:
        remaining_label = f"{t(language, 'result_footer')}: {format_tokens(remaining)}"
    else:
        left = requests_left_after
        if left is None:
            left = get_free_requests_remaining(user['user_id'])
        total = int(get_setting('free_requests', '3'))
        remaining_label = f"{t(language, 'requests_left')}: {left} / {total}"

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

    divider = '━━━━━━━━━━━━━━'
    brand = t(language, 'brand_header')
    header = f"{brand} · {scenario_title}" if scenario_title else brand

    for i, chunk in enumerate(chunks):
        if not call_failed and i == 0:
            chunk = f"{header}\n{divider}\n{chunk}"
        if i == len(chunks) - 1:
            if call_failed:
                footer = f"\n\n◇ {remaining_label}"
            else:
                footer = (
                    f"\n{divider}\n"
                    f"◇ {t(language, 'done_in', seconds=elapsed_seconds)}"
                    f" · {remaining_label}"
                )
            if show_upgrade and requests_left_after is not None:
                if requests_left_after <= 0:
                    footer += f"\n⚡ {t(language, 'limit_nudge_zero')}"
                else:
                    footer += (
                        f"\n⚡ {t(language, 'low_balance_nudge', remaining=requests_left_after)}"
                    )
            if len(chunk) + len(footer) < 4096:
                chunk += footer
        reply_markup = (
            result_keyboard(language, category=category, show_upgrade=show_upgrade)
            if i == len(chunks) - 1 else None
        )
        await reply_target.reply_text(chunk, reply_markup=reply_markup)

    # Жёсткий оффер после 1-го результата и при полном исчерпании
    if not call_failed and not is_pro_user and requests_left_after is not None:
        if used_before == 1:
            await reply_target.reply_text(
                t(language, 'after_first_win'),
                reply_markup=buy_plans_keyboard(language),
                parse_mode='Markdown',
            )
        elif requests_left_after <= 0:
            await reply_target.reply_text(
                build_buy_text(language, mode='limit'),
                reply_markup=buy_plans_keyboard(language),
                parse_mode='Markdown',
            )


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
        multi_step=bool(prompt.get('multi_step')),
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

    user = await ensure_user(update)
    language = user_language(user)
    awaiting_ai = context.user_data.pop('awaiting_ai', None)
    # Pro — свободный чат; триал — только после кнопки «Спросить AI»
    if user['subscription_status'] != 'active' and not awaiting_ai:
        await update.message.reply_text(
            t(language, 'ask_ai_hint'),
            reply_markup=main_menu_keyboard(
                is_admin=is_admin(user['user_id']), language=language
            ),
            parse_mode='Markdown',
        )
        return

    prompt_text = text.strip()
    urls = extract_urls(prompt_text)
    if urls:
        if not _has_pro_access(user):
            await update.message.reply_text(
                f"🔗 {t(language, 'link_locked')}\n\n{build_buy_text(language, mode='locked', user_id=user['user_id'])}",
                reply_markup=buy_plans_keyboard(language),
                parse_mode='Markdown',
            )
            return
        fetched = []
        for url in urls[:MAX_URLS_PER_MESSAGE]:
            page_text = await asyncio.to_thread(fetch_url_text, url)
            if page_text:
                fetched.append(f"--- PAGE CONTENT ({url}) ---\n{page_text}")
        if not fetched:
            await update.message.reply_text(
                t(language, 'url_fetch_failed'),
                reply_markup=back_to_menu_keyboard(language),
            )
            return
        prompt_text = prompt_text + '\n\n' + '\n\n'.join(fetched)

    await process_ai_request(update, context, prompt_text)


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
    await execute_store_prompt(update, context, prompt, values)


def _is_broadcast_input(context):
    return context.user_data.get('admin_action') in ('broadcast', 'broadcast_confirm')


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Фото — скриншот оплаты или рассылка"""
    if _is_broadcast_input(context):
        from admin_panel import broadcast_message
        await broadcast_message(update, context)
        return

    handled = await handle_screenshot(update, context)
    if not handled:
        user = await ensure_user(update)
        await update.message.reply_text(t(user_language(user), 'photo_hint'))


DOC_ANALYSIS_INSTRUCTION = (
    "Analyze this document and provide a clear, structured summary: "
    "key points, important details, risks or issues worth attention."
)


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if _is_broadcast_input(context):
        from admin_panel import broadcast_message
        await broadcast_message(update, context)
        return

    user = await ensure_user(update)
    language = user_language(user)

    document = update.message.document
    if not document:
        await update.message.reply_text(t(language, 'file_unsupported'))
        return

    filename = document.file_name or 'file'
    ext = os.path.splitext(filename)[1].lower()
    mime = (document.mime_type or '').lower()

    # PDF/изображение как чек оплаты
    is_receipt_doc = (
        ext in ('.pdf', '.jpg', '.jpeg', '.png', '.webp')
        or mime.startswith('image/')
        or mime == 'application/pdf'
    )
    if is_receipt_doc and (
        context.user_data.get('awaiting_screenshot')
        or context.user_data.get('pending_order_id')
        or get_user_pending_payment(user['user_id'])
    ):
        handled = await handle_screenshot(
            update, context,
            file_id=document.file_id,
            caption=update.message.caption or filename,
        )
        if handled:
            return

    # Анализ документов — Pro-функция
    if not _has_pro_access(user):
        await update.message.reply_text(
            f"📎 {t(language, 'file_locked')}\n\n{build_buy_text(language, mode='locked', user_id=user['user_id'])}",
            reply_markup=buy_plans_keyboard(language),
            parse_mode='Markdown',
        )
        return

    if ext not in ALLOWED_FILE_EXTS:
        await update.message.reply_text(t(language, 'file_bad_type'))
        return
    if (document.file_size or 0) > MAX_FILE_MB * 1024 * 1024:
        await update.message.reply_text(t(language, 'file_too_big', mb=MAX_FILE_MB))
        return

    tmp_path = None
    try:
        tg_file = await document.get_file()
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp_path = tmp.name
        await tg_file.download_to_drive(tmp_path)
        doc_text = await asyncio.to_thread(extract_file_text, tmp_path, ext)
    except Exception:
        doc_text = ''
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    if not doc_text:
        await update.message.reply_text(t(language, 'file_empty'))
        return

    instruction = (update.message.caption or '').strip() or DOC_ANALYSIS_INSTRUCTION
    prompt_text = (
        f"{instruction}\n\n--- DOCUMENT ({filename}) ---\n{doc_text}"
    )
    await process_ai_request(update, context, prompt_text)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if _is_broadcast_input(context):
        from admin_panel import broadcast_message
        await broadcast_message(update, context)
        return
    user = await ensure_user(update)
    await update.message.reply_text(t(user_language(user), 'voice_unsupported'))


async def handle_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await ensure_user(update)
    await update.message.reply_text(t(user_language(user), 'unknown_command'))


async def buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_maintenance(update):
        return
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
