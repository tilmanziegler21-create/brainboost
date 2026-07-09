import logging
import os

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

from config import BOT_TOKEN
from database import init_db
from prompts_data import seed_prompts
from utils import setup_logging

from handlers import (
    start, buy, profile, referral, help_command,
    handle_message, handle_photo, handle_file, handle_voice, handle_unknown,
    main_menu_callback, ask_ai_callback, prompts_menu_callback,
    user_category_callback, prompt_use_callback,
    buy_callback, profile_callback, referral_callback, help_callback,
    admin_panel_callback,
)
from admin_panel import (
    admin_panel, admin_stats, admin_payments, admin_settings, admin_claude,
    admin_prompts, admin_broadcast, admin_logs, admin_back, admin_refresh,
    admin_price_command, cancel_broadcast, cancel_admin_action,
    confirm_payment_callback, reject_payment_callback, view_screenshot_callback,
    prompt_category_callback, prompt_add_callback, edit_prompt_callback,
    delete_prompt_callback, admin_settings_prices, admin_settings_limits,
    admin_settings_payment, admin_settings_welcome, admin_settings_maintenance,
    admin_payment_card_uah, admin_payment_card_eur, admin_payment_usdt,
    toggle_setting_callback, admin_tokens, admin_tokens_me, admin_tokens_top,
    admin_tokens_low, admin_tokens_find,
    admin_claude_usage, admin_claude_test, admin_claude_model,
)
from payment import payment_callback, i_paid_callback

logger = setup_logging()


def main():
    if not BOT_TOKEN or BOT_TOKEN == 'YOUR_BOT_TOKEN_HERE':
        logger.error("Укажи BOT_TOKEN в файле .env")
        print("❌ Укажи BOT_TOKEN в файле .env")
        return

    # Инициализация БД
    init_db()
    seeded = seed_prompts()
    if seeded:
        logger.info(f"Загружено промтов: {seeded}")

    app = Application.builder().token(BOT_TOKEN).build()

    # Пользовательские команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("referral", referral))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("cancel", cancel_admin_action))
    app.add_handler(CommandHandler("cancel_broadcast", cancel_broadcast))

    # Админ-команды настроек
    admin_set_commands = [
        "set_price_eur", "set_price_usd", "set_price_uah",
        "set_free_requests", "set_claude_api_key", "set_claude_model",
        "set_claude_api_url", "set_claude_client_version", "set_claude_anthropic_version",
        "set_claude_oauth_token",
        "set_subscription_tokens", "set_subscription_days",
        "set_referral_bonus", "set_max_referrals",
        "set_card_uah_number", "set_card_uah_bank", "set_card_uah_recipient",
        "set_card_eur_iban", "set_card_eur_bic", "set_card_eur_recipient",
        "set_usdt_wallet", "set_usdt_network", "set_welcome",
    ]
    for cmd in admin_set_commands:
        app.add_handler(CommandHandler(cmd, admin_price_command))

    # Главное меню / пользовательские callback
    app.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(ask_ai_callback, pattern="^ask_ai$"))
    app.add_handler(CallbackQueryHandler(prompts_menu_callback, pattern="^prompts_menu$"))
    app.add_handler(CallbackQueryHandler(user_category_callback, pattern="^user_cat_"))
    app.add_handler(CallbackQueryHandler(prompt_use_callback, pattern="^use_prompt_"))
    app.add_handler(CallbackQueryHandler(buy_callback, pattern="^buy$"))
    app.add_handler(CallbackQueryHandler(profile_callback, pattern="^profile$"))
    app.add_handler(CallbackQueryHandler(referral_callback, pattern="^referral$"))
    app.add_handler(CallbackQueryHandler(help_callback, pattern="^help$"))
    app.add_handler(CallbackQueryHandler(admin_panel_callback, pattern="^admin_panel$"))

    # Админ callback
    app.add_handler(CallbackQueryHandler(admin_stats, pattern="^admin_stats$"))
    app.add_handler(CallbackQueryHandler(admin_tokens, pattern="^admin_tokens$"))
    app.add_handler(CallbackQueryHandler(admin_tokens_me, pattern="^admin_tokens_me$"))
    app.add_handler(CallbackQueryHandler(admin_tokens_top, pattern="^admin_tokens_top$"))
    app.add_handler(CallbackQueryHandler(admin_tokens_low, pattern="^admin_tokens_low$"))
    app.add_handler(CallbackQueryHandler(admin_tokens_find, pattern="^admin_tokens_find$"))
    app.add_handler(CallbackQueryHandler(admin_payments, pattern="^admin_payments$"))
    app.add_handler(CallbackQueryHandler(admin_settings, pattern="^admin_settings$"))
    app.add_handler(CallbackQueryHandler(admin_claude, pattern="^admin_claude$"))
    app.add_handler(CallbackQueryHandler(admin_claude_usage, pattern="^admin_claude_usage$"))
    app.add_handler(CallbackQueryHandler(admin_claude_test, pattern="^admin_claude_test$"))
    app.add_handler(CallbackQueryHandler(admin_claude_model, pattern="^admin_claude_model_"))
    app.add_handler(CallbackQueryHandler(admin_prompts, pattern="^admin_prompts$"))
    app.add_handler(CallbackQueryHandler(admin_broadcast, pattern="^admin_broadcast$"))
    app.add_handler(CallbackQueryHandler(admin_logs, pattern="^admin_logs$"))
    app.add_handler(CallbackQueryHandler(admin_back, pattern="^admin_back$"))
    app.add_handler(CallbackQueryHandler(admin_refresh, pattern="^admin_refresh$"))
    app.add_handler(CallbackQueryHandler(admin_settings_prices, pattern="^admin_settings_prices$"))
    app.add_handler(CallbackQueryHandler(admin_settings_limits, pattern="^admin_settings_limits$"))
    app.add_handler(CallbackQueryHandler(admin_settings_payment, pattern="^admin_settings_payment$"))
    app.add_handler(CallbackQueryHandler(admin_settings_welcome, pattern="^admin_settings_welcome$"))
    app.add_handler(CallbackQueryHandler(admin_settings_maintenance, pattern="^admin_settings_maintenance$"))
    app.add_handler(CallbackQueryHandler(admin_payment_card_uah, pattern="^admin_payment_card_uah$"))
    app.add_handler(CallbackQueryHandler(admin_payment_card_eur, pattern="^admin_payment_card_eur$"))
    app.add_handler(CallbackQueryHandler(admin_payment_usdt, pattern="^admin_payment_usdt$"))
    app.add_handler(CallbackQueryHandler(toggle_setting_callback, pattern="^toggle_"))

    # Оплаты
    app.add_handler(CallbackQueryHandler(payment_callback, pattern="^pay_"))
    app.add_handler(CallbackQueryHandler(i_paid_callback, pattern="^i_paid_"))
    app.add_handler(CallbackQueryHandler(confirm_payment_callback, pattern="^confirm_"))
    app.add_handler(CallbackQueryHandler(reject_payment_callback, pattern="^reject_"))
    app.add_handler(CallbackQueryHandler(view_screenshot_callback, pattern="^view_screenshot_"))

    # Промты (админ)
    app.add_handler(CallbackQueryHandler(prompt_category_callback, pattern="^prompt_cat_"))
    app.add_handler(CallbackQueryHandler(prompt_add_callback, pattern="^prompt_add$"))
    app.add_handler(CallbackQueryHandler(edit_prompt_callback, pattern="^edit_prompt_"))
    app.add_handler(CallbackQueryHandler(delete_prompt_callback, pattern="^del_prompt_"))

    # Сообщения
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.VIDEO, handle_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.COMMAND, handle_unknown))

    logger.info("BrainBoost bot starting...")
    print("🧠 BrainBoost bot запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
