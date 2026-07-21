import sqlite3
from datetime import datetime, timedelta
import hashlib
import random
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot.db')


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Инициализация базы данных с дефолтными настройками"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            language TEXT DEFAULT 'uk',
            language_selected INTEGER DEFAULT 0,
            subscription_status TEXT DEFAULT 'trial',
            tokens_limit INTEGER DEFAULT 1000000,
            tokens_used INTEGER DEFAULT 0,
            free_requests_used INTEGER DEFAULT 0,
            subscription_end_date TEXT,
            referral_code TEXT UNIQUE,
            referred_by INTEGER,
            total_referrals INTEGER DEFAULT 0,
            bonus_tokens INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            currency TEXT,
            payment_method TEXT,
            order_id TEXT UNIQUE,
            status TEXT DEFAULT 'pending',
            screenshot_file_id TEXT,
            screenshot_caption TEXT,
            admin_comment TEXT,
            txid TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            confirmed_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS prompts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT,
            title TEXT,
            description TEXT,
            system_prompt TEXT,
            prompt_text TEXT,
            variables TEXT DEFAULT '["topic"]',
            icon TEXT DEFAULT '📌',
            is_active INTEGER DEFAULT 1,
            sort_order INTEGER DEFAULT 0,
            usage_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS admin_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            setting_key TEXT UNIQUE,
            setting_value TEXT,
            description TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT,
            details TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS broadcasts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message TEXT,
            sent_count INTEGER DEFAULT 0,
            total_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT
        );
    ''')

    default_settings = [
        ('claude_api_key', 'sk-ant-api-xxx', 'API ключ Claude'),
        ('claude_model', 'claude-opus-4-7', 'Модель Claude'),
        ('claude_api_url', 'https://claude-code-cli.vibecode-claude.online', 'URL API провайдера'),
        ('claude_client_version', '2.1.198', 'Версия Claude Code CLI'),
        ('claude_anthropic_version', '2023-06-01', 'Заголовок anthropic-version'),
        ('claude_oauth_token', '', 'OAuth/setup-token Claude Code (логин шага 2)'),
        ('price_eur', '15', 'Цена в EUR (1 месяц)'),
        ('price_usd', '16', 'Цена в USD (1 месяц)'),
        ('price_uah', '630', 'Цена в UAH (1 месяц)'),
        ('price_eur_3m', '33', 'Цена в EUR (3 месяца)'),
        ('price_usd_3m', '36', 'Цена в USD (3 месяца)'),
        ('price_uah_3m', '1390', 'Цена в UAH (3 месяца)'),
        ('price_eur_6m', '60', 'Цена в EUR (6 месяцев)'),
        ('price_usd_6m', '65', 'Цена в USD (6 месяцев)'),
        ('price_uah_6m', '2520', 'Цена в UAH (6 месяцев)'),
        ('free_requests', '3', 'Бесплатных запросов'),
        ('free_request_cost', '100000', 'Списание за бесплатный запрос'),
        ('free_tokens_limit', '1000000', 'Бесплатных токенов на пользователя'),
        ('subscription_tokens', '50000000', 'Токенов в подписке'),
        ('subscription_days', '30', 'Дней подписки'),
        ('referral_bonus', '5000000', 'Бонус за реферала'),
        ('max_referrals', '5', 'Макс рефералов'),
        ('card_uah_enabled', 'true', 'Включена карта UAH'),
        ('card_uah_number', '4149 4999 9999 9999', 'Номер карты UAH'),
        ('card_uah_bank', 'ПриватБанк', 'Банк UAH'),
        ('card_uah_recipient', 'БОГДАНОВИЧ АНДРІЙ', 'Получатель UAH'),
        ('card_eur_enabled', 'true', 'Включена карта EUR'),
        ('card_eur_iban', 'DE89 3704 0044 0532 0130 00', 'IBAN EUR'),
        ('card_eur_bic', 'COBADEFFXXX', 'BIC EUR'),
        ('card_eur_recipient', 'BrainBoost OÜ', 'Получатель EUR'),
        ('usdt_enabled', 'true', 'Включен USDT'),
        ('usdt_wallet', 'TXxxXxxxXxxxXxxxXxxxXxxxXxxxXxxxXxxx', 'Кошелек TRC20'),
        ('usdt_network', 'TRC20', 'Сеть USDT'),
        ('admin_notifications', 'true', 'Уведомления админам'),
        ('payment_notification_chat_id', '', 'Группа уведомлений об оплатах'),
        ('welcome_message', 'Привет! Я BrainBoost — твой AI-помощник', 'Приветствие'),
        ('support_url', '', 'Ссылка поддержки (https://t.me/...)'),
        ('maintenance_mode', 'false', 'Режим обслуживания'),
    ]

    for key, value, desc in default_settings:
        cursor.execute('''
            INSERT OR IGNORE INTO admin_settings (setting_key, setting_value, description)
            VALUES (?, ?, ?)
        ''', (key, value, desc))

    # Миграция на провайдер Claude Code CLI (если ещё старые дефолты)
    old_url = cursor.execute(
        "SELECT setting_value FROM admin_settings WHERE setting_key = 'claude_api_url'"
    ).fetchone()
    if old_url and old_url[0] in (
        'https://api.anthropic.com/v1/messages',
        'https://api.anthropic.com',
    ):
        cursor.execute(
            "UPDATE admin_settings SET setting_value = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE setting_key = 'claude_api_url'",
            ('https://claude-code-cli.vibecode-claude.online',),
        )

    # Одноразовые миграции (не затирают выбор админа на каждом рестарте)
    def _flag_done(flag):
        row = cursor.execute(
            'SELECT setting_value FROM admin_settings WHERE setting_key = ?',
            (flag,),
        ).fetchone()
        return bool(row and row[0] == '1')

    def _mark_flag(flag):
        cursor.execute('''
            INSERT INTO admin_settings (setting_key, setting_value, description)
            VALUES (?, '1', ?)
            ON CONFLICT(setting_key) DO UPDATE SET
                setting_value = '1',
                updated_at = CURRENT_TIMESTAMP
        ''', (flag, f'one-shot migration {flag}'))

    if not _flag_done('migration_model_legacy_v1'):
        old_model = cursor.execute(
            "SELECT setting_value FROM admin_settings WHERE setting_key = 'claude_model'"
        ).fetchone()
        if old_model and old_model[0] in (
            'claude-3-5-sonnet-20241022',
            'claude-3-5-sonnet-20240620',
            'claude-3-opus-20240229',
        ):
            cursor.execute(
                "UPDATE admin_settings SET setting_value = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE setting_key = 'claude_model'",
                ('claude-opus-4-7',),
            )
        _mark_flag('migration_model_legacy_v1')

    if not _flag_done('migration_cli_2_1_198'):
        cursor.execute(
            "UPDATE admin_settings SET setting_value = '2.1.198', "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE setting_key = 'claude_client_version' "
            "AND setting_value = '2.1.205'"
        )
        _mark_flag('migration_cli_2_1_198')

    # Миграция таблицы prompts → магазин промтов
    prompt_cols = {
        r[1] for r in cursor.execute('PRAGMA table_info(prompts)').fetchall()
    }
    alter_map = {
        'description': "ALTER TABLE prompts ADD COLUMN description TEXT",
        'system_prompt': "ALTER TABLE prompts ADD COLUMN system_prompt TEXT",
        'variables': "ALTER TABLE prompts ADD COLUMN variables TEXT DEFAULT '[\"topic\"]'",
        'icon': "ALTER TABLE prompts ADD COLUMN icon TEXT DEFAULT '📌'",
        'usage_count': "ALTER TABLE prompts ADD COLUMN usage_count INTEGER DEFAULT 0",
        'multi_step': "ALTER TABLE prompts ADD COLUMN multi_step INTEGER DEFAULT 0",
    }
    for col, sql in alter_map.items():
        if col not in prompt_cols:
            cursor.execute(sql)

    user_cols = {
        r[1] for r in cursor.execute('PRAGMA table_info(users)').fetchall()
    }
    if 'language_selected' not in user_cols:
        cursor.execute(
            'ALTER TABLE users ADD COLUMN language_selected INTEGER DEFAULT 0'
        )
    payment_cols = {
        r[1] for r in cursor.execute('PRAGMA table_info(payments)').fetchall()
    }
    if 'months' not in payment_cols:
        cursor.execute(
            'ALTER TABLE payments ADD COLUMN months INTEGER DEFAULT 1'
        )
    if 'abandoned_notified' not in payment_cols:
        cursor.execute(
            'ALTER TABLE payments ADD COLUMN abandoned_notified INTEGER DEFAULT 0'
        )

    if 'renewal_notified' not in user_cols:
        cursor.execute(
            'ALTER TABLE users ADD COLUMN renewal_notified INTEGER DEFAULT 0'
        )

    if 'referer' not in user_cols:
        cursor.execute('ALTER TABLE users ADD COLUMN referer TEXT')
    if 'last_activity' not in user_cols:
        cursor.execute('ALTER TABLE users ADD COLUMN last_activity TEXT')
    if 'limit_hit_at' not in user_cols:
        cursor.execute('ALTER TABLE users ADD COLUMN limit_hit_at TEXT')
    if 'sales_followup_step' not in user_cols:
        cursor.execute(
            'ALTER TABLE users ADD COLUMN sales_followup_step INTEGER DEFAULT 0'
        )

    # Миграция цен на линейку 15/33/60 € (только если стояли старые дефолты)
    price_migrations = {
        'price_eur': ('25', '15'),
        'price_usd': ('27', '16'),
        'price_uah': ('1050', '630'),
        'price_eur_3m': ('65', '33'),
        'price_usd_3m': ('70', '36'),
        'price_uah_3m': ('2740', '1390'),
    }
    for key, (old, new) in price_migrations.items():
        cursor.execute('''
            UPDATE admin_settings
            SET setting_value = ?, updated_at = CURRENT_TIMESTAMP
            WHERE setting_key = ? AND setting_value = ?
        ''', (new, key, old))

    if 'free_requests_used' not in user_cols:
        cursor.execute(
            'ALTER TABLE users ADD COLUMN free_requests_used INTEGER DEFAULT 0'
        )
        # Раньше tokens_used у trial означал число запросов. Переводим старые
        # данные в новую схему: 100K за запрос, максимум 10 запросов / 1M.
        cursor.execute('''
            UPDATE users
            SET free_requests_used = MIN(COALESCE(tokens_used, 0), 10),
                tokens_used = MIN(COALESCE(tokens_used, 0), 10) * 100000,
                tokens_limit = 1000000
            WHERE subscription_status = 'trial'
        ''')

    cursor.execute('''
        UPDATE admin_settings
        SET setting_value = '10', updated_at = CURRENT_TIMESTAMP
        WHERE setting_key = 'free_requests' AND setting_value = '20'
    ''')
    # Продажная воронка: 10 → 3 один раз (админский /set_free_requests 10 больше не затирается)
    if not _flag_done('migration_free_requests_to_3'):
        cursor.execute('''
            UPDATE admin_settings
            SET setting_value = '3', updated_at = CURRENT_TIMESTAMP
            WHERE setting_key = 'free_requests' AND setting_value = '10'
        ''')
        _mark_flag('migration_free_requests_to_3')

    # Старые промты без variables → topic
    cursor.execute('''
        UPDATE prompts
        SET variables = '["topic"]'
        WHERE variables IS NULL OR variables = ''
    ''')
    cursor.execute('''
        UPDATE prompts
        SET icon = '📌'
        WHERE icon IS NULL OR icon = ''
    ''')

    conn.commit()
    conn.close()


# --- Работа с настройками ---

def get_setting(key, default=None):
    """Получить настройку из БД"""
    conn = get_db_connection()
    result = conn.execute(
        'SELECT setting_value FROM admin_settings WHERE setting_key = ?', (key,)
    ).fetchone()
    conn.close()
    return result[0] if result else default


def get_setting_int(key, default=0):
    """Безопасное чтение числовой настройки (битый /set_* не роняет бота)."""
    raw = get_setting(key, str(default))
    try:
        return int(float(str(raw).replace(',', '.').strip()))
    except (TypeError, ValueError):
        return int(default)


def _utc_now():
    return datetime.utcnow()


def _parse_ts(value):
    if not value:
        return None
    raw = str(value).replace('T', ' ')[:19]
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def set_setting(key, value, description=None):
    """Обновить настройку (создаёт запись, если ключа ещё нет)"""
    conn = get_db_connection()
    cursor = conn.execute('''
        UPDATE admin_settings
        SET setting_value = ?, updated_at = CURRENT_TIMESTAMP
        WHERE setting_key = ?
    ''', (str(value), key))
    if cursor.rowcount == 0:
        conn.execute('''
            INSERT INTO admin_settings (setting_key, setting_value, description)
            VALUES (?, ?, ?)
        ''', (key, str(value), description or ''))
    conn.commit()
    conn.close()


def get_all_settings():
    """Получить все настройки"""
    conn = get_db_connection()
    settings = conn.execute(
        'SELECT setting_key, setting_value, description FROM admin_settings'
    ).fetchall()
    conn.close()
    return [dict(s) for s in settings]


def get_setting_group(prefix):
    """Получить группу настроек по префиксу (например, 'card_uah_')"""
    conn = get_db_connection()
    settings = conn.execute(
        'SELECT setting_key, setting_value FROM admin_settings WHERE setting_key LIKE ?',
        (f'{prefix}%',)
    ).fetchall()
    conn.close()
    return {s['setting_key']: s['setting_value'] for s in settings}


# --- Работа с пользователями ---

def get_user(user_id):
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE user_id = ?', (user_id,)).fetchone()
    conn.close()
    return dict(user) if user else None


def create_user(
    user_id, username, first_name, referred_by=None, last_name=None,
    language='en', referer=None,
):
    conn = get_db_connection()
    cursor = conn.cursor()

    ref_code = hashlib.md5(f"{user_id}{random.randint(1000, 9999)}".encode()).hexdigest()[:8]
    free_limit = int(get_setting('free_tokens_limit', '1000000'))

    cursor.execute('''
        INSERT INTO users (
            user_id, username, first_name, last_name, referral_code,
            tokens_limit, referred_by, language, referer
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        user_id, username, first_name, last_name, ref_code,
        free_limit, referred_by, language, referer,
    ))

    cursor.execute('''
        INSERT INTO logs (user_id, action, details)
        VALUES (?, ?, ?)
    ''', (user_id, 'register', f'Referred by: {referred_by}'))

    conn.commit()
    conn.close()

    if referred_by:
        add_referral_bonus(referred_by, user_id)

    return True


def set_user_language(user_id, language):
    """Сохранить выбранный язык клиентского интерфейса."""
    conn = get_db_connection()
    conn.execute(
        '''
        UPDATE users
        SET language = ?, language_selected = 1
        WHERE user_id = ?
        ''',
        (language, user_id),
    )
    conn.commit()
    conn.close()


def add_referral_bonus(referrer_id, new_user_id):
    """Начислить бонус рефереру. Если ещё не Pro — отложить до активации."""
    conn = get_db_connection()
    referrer = conn.execute(
        'SELECT * FROM users WHERE user_id = ?', (referrer_id,)
    ).fetchone()
    if not referrer:
        conn.close()
        return

    max_refs = get_setting_int('max_referrals', 5)
    if (referrer['total_referrals'] or 0) >= max_refs:
        conn.close()
        return

    conn.execute('''
        UPDATE users SET total_referrals = total_referrals + 1 WHERE user_id = ?
    ''', (referrer_id,))

    if referrer['subscription_status'] == 'active':
        bonus = get_setting_int('referral_bonus', 5000000)
        conn.execute('''
            UPDATE users SET bonus_tokens = bonus_tokens + ? WHERE user_id = ?
        ''', (bonus, referrer_id))
        conn.execute('''
            INSERT INTO logs (user_id, action, details) VALUES (?, ?, ?)
        ''', (referrer_id, 'referral_bonus', f'User {new_user_id}, bonus: {bonus}'))
    else:
        conn.execute('''
            INSERT INTO logs (user_id, action, details) VALUES (?, ?, ?)
        ''', (
            referrer_id, 'referral_pending',
            f'User {new_user_id}',
        ))
    conn.commit()
    conn.close()


def flush_pending_referral_bonuses(referrer_id):
    """Выдать отложенные реферальные бонусы при активации Pro."""
    conn = get_db_connection()
    pending = conn.execute('''
        SELECT id, details FROM logs
        WHERE user_id = ? AND action = 'referral_pending'
    ''', (referrer_id,)).fetchall()
    if not pending:
        conn.close()
        return 0

    bonus = get_setting_int('referral_bonus', 5000000)
    granted = 0
    for row in pending:
        conn.execute('''
            UPDATE users SET bonus_tokens = bonus_tokens + ? WHERE user_id = ?
        ''', (bonus, referrer_id))
        conn.execute('''
            UPDATE logs SET action = 'referral_bonus',
                details = ? WHERE id = ?
        ''', (f"{row['details']}, bonus: {bonus} (deferred)", row['id']))
        granted += 1
    conn.commit()
    conn.close()
    return granted


def update_tokens_used(user_id, tokens, count_free_request=False):
    conn = get_db_connection()
    if count_free_request:
        conn.execute('''
            UPDATE users
            SET tokens_used = tokens_used + ?,
                free_requests_used = free_requests_used + 1
            WHERE user_id = ?
        ''', (tokens, user_id))
    else:
        conn.execute('''
            UPDATE users
            SET tokens_used = tokens_used + ?
            WHERE user_id = ?
        ''', (tokens, user_id))
    conn.commit()
    conn.close()


def get_remaining_tokens(user_id):
    user = get_user(user_id)
    if not user:
        return 0
    # Для Pro берём сохранённый лимит тарифа (1/3/6 мес), не дефолт 1 месяца
    if user['subscription_status'] == 'active':
        base = user.get('tokens_limit') or get_setting_int('subscription_tokens', 50000000)
        limit = int(base) + (user.get('bonus_tokens') or 0)
    else:
        limit = user['tokens_limit']
    return max(0, limit - user['tokens_used'])


def get_tokens_limit(user_id):
    user = get_user(user_id)
    if not user:
        return 0
    if user['subscription_status'] == 'active':
        base = user.get('tokens_limit') or get_setting_int('subscription_tokens', 50000000)
        return int(base) + (user.get('bonus_tokens') or 0)
    return user['tokens_limit']


def get_free_requests_remaining(user_id):
    user = get_user(user_id)
    if not user or user['subscription_status'] != 'trial':
        return 0
    limit = get_setting_int('free_requests', 3)
    return max(0, limit - (user.get('free_requests_used') or 0))


def mark_trial_limit_hit(user_id):
    """Зафиксировать момент исчерпания триала (для серии дожимов)."""
    conn = get_db_connection()
    conn.execute('''
        UPDATE users
        SET limit_hit_at = COALESCE(limit_hit_at, CURRENT_TIMESTAMP),
            sales_followup_step = COALESCE(sales_followup_step, 0)
        WHERE user_id = ?
          AND subscription_status IN ('trial', 'expired')
    ''', (user_id,))
    conn.commit()
    conn.close()


def clear_sales_funnel_state(user_id):
    """Сбросить дожимы после покупки Pro."""
    conn = get_db_connection()
    conn.execute('''
        UPDATE users
        SET limit_hit_at = NULL,
            sales_followup_step = 0
        WHERE user_id = ?
    ''', (user_id,))
    conn.commit()
    conn.close()


def get_sales_followup_candidates():
    """Кандидаты на дожим после исчерпания триала: 1ч / 24ч / 72ч."""
    conn = get_db_connection()
    rows = conn.execute('''
        SELECT user_id, language, limit_hit_at,
               COALESCE(sales_followup_step, 0) AS sales_followup_step
        FROM users
        WHERE subscription_status IN ('trial', 'expired')
          AND limit_hit_at IS NOT NULL
          AND COALESCE(sales_followup_step, 0) < 3
    ''').fetchall()
    conn.close()
    return [dict(r) for r in rows]


def advance_sales_followup(user_id, step):
    conn = get_db_connection()
    conn.execute(
        'UPDATE users SET sales_followup_step = ? WHERE user_id = ?',
        (step, user_id),
    )
    conn.commit()
    conn.close()


def get_abandoned_payments(hours=1):
    """Заказы без чека/TXID старше N часов, ещё без напоминания."""
    conn = get_db_connection()
    rows = conn.execute('''
        SELECT p.order_id, p.user_id, p.amount, p.currency, p.months,
               u.language
        FROM payments p
        JOIN users u ON u.user_id = p.user_id
        WHERE p.status = 'pending'
          AND COALESCE(p.abandoned_notified, 0) = 0
          AND (p.screenshot_file_id IS NULL OR p.screenshot_file_id = '')
          AND (p.txid IS NULL OR p.txid = '')
          AND datetime(p.created_at) <= datetime('now', ?)
          AND u.subscription_status != 'active'
    ''', (f'-{int(hours)} hours',)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_payment_abandoned_notified(order_id):
    conn = get_db_connection()
    conn.execute(
        'UPDATE payments SET abandoned_notified = 1 WHERE order_id = ?',
        (order_id,),
    )
    conn.commit()
    conn.close()


def activate_subscription(user_id, months=1):
    conn = get_db_connection()
    days = get_setting_int('subscription_days', 30) * int(months)
    tokens_limit = get_setting_int('subscription_tokens', 50000000) * int(months)

    row = conn.execute(
        'SELECT subscription_end_date, subscription_status FROM users WHERE user_id = ?',
        (user_id,),
    ).fetchone()
    start = _utc_now()
    if row and row['subscription_status'] == 'active' and row['subscription_end_date']:
        current_end = _parse_ts(row['subscription_end_date'])
        if current_end and current_end > start:
            start = current_end
    end_date = (start + timedelta(days=days)).strftime('%Y-%m-%d')

    conn.execute('''
        UPDATE users
        SET subscription_status = 'active',
            tokens_limit = ?,
            tokens_used = 0,
            subscription_end_date = ?,
            renewal_notified = 0,
            limit_hit_at = NULL,
            sales_followup_step = 0
        WHERE user_id = ?
    ''', (tokens_limit, end_date, user_id))
    conn.commit()
    conn.close()
    flush_pending_referral_bonuses(user_id)


def check_and_expire_subscriptions():
    conn = get_db_connection()
    today = _utc_now().strftime('%Y-%m-%d')
    expired = conn.execute('''
        SELECT user_id FROM users
        WHERE subscription_status = 'active'
        AND subscription_end_date < ?
    ''', (today,)).fetchall()

    for user in expired:
        conn.execute('''
            UPDATE users
            SET subscription_status = 'expired',
                limit_hit_at = COALESCE(limit_hit_at, CURRENT_TIMESTAMP),
                sales_followup_step = CASE
                    WHEN limit_hit_at IS NULL THEN 0
                    ELSE COALESCE(sales_followup_step, 0)
                END,
                renewal_notified = 0
            WHERE user_id = ?
        ''', (user['user_id'],))

    conn.commit()
    conn.close()
    return len(expired)


def get_user_by_referral_code(code):
    conn = get_db_connection()
    user = conn.execute(
        'SELECT * FROM users WHERE referral_code = ?', (code,)
    ).fetchone()
    conn.close()
    return dict(user) if user else None


def block_user(user_id):
    conn = get_db_connection()
    conn.execute(
        "UPDATE users SET subscription_status = 'blocked' WHERE user_id = ?",
        (user_id,)
    )
    conn.commit()
    conn.close()


def unblock_user(user_id):
    conn = get_db_connection()
    row = conn.execute(
        'SELECT subscription_end_date FROM users WHERE user_id = ?', (user_id,)
    ).fetchone()
    today = _utc_now().strftime('%Y-%m-%d')
    status = 'trial'
    if row and row['subscription_end_date'] and str(row['subscription_end_date'])[:10] >= today:
        status = 'active'
    conn.execute(
        'UPDATE users SET subscription_status = ? WHERE user_id = ?',
        (status, user_id),
    )
    conn.commit()
    conn.close()
    return status


# --- Работа с платежами ---

def create_payment(user_id, amount, currency, method, months=1):
    """Создать заказ. Старые pending без чека того же юзера отменяются."""
    conn = get_db_connection()
    conn.execute('''
        UPDATE payments
        SET status = 'cancelled',
            admin_comment = COALESCE(admin_comment, 'superseded')
        WHERE user_id = ? AND status IN ('pending', 'paid')
          AND (screenshot_file_id IS NULL OR screenshot_file_id = '')
          AND (txid IS NULL OR txid = '')
    ''', (user_id,))

    order_id = (
        f"BB-{_utc_now().strftime('%Y%m%d')}-"
        f"{hashlib.md5(f'{user_id}{_utc_now()}'.encode()).hexdigest()[:6].upper()}"
    )

    conn.execute('''
        INSERT INTO payments (user_id, amount, currency, payment_method, order_id, status, months)
        VALUES (?, ?, ?, ?, ?, 'pending', ?)
    ''', (user_id, amount, currency, method, order_id, int(months)))

    conn.commit()
    conn.close()
    return order_id


def get_payment(order_id):
    conn = get_db_connection()
    payment = conn.execute(
        'SELECT * FROM payments WHERE order_id = ?', (order_id,)
    ).fetchone()
    conn.close()
    return dict(payment) if payment else None


def get_pending_payments():
    conn = get_db_connection()
    payments = conn.execute('''
        SELECT * FROM payments
        WHERE status IN ('pending', 'paid')
        ORDER BY created_at DESC
    ''').fetchall()
    conn.close()
    return [dict(p) for p in payments]


def get_user_pending_payment(user_id):
    conn = get_db_connection()
    payment = conn.execute('''
        SELECT * FROM payments
        WHERE user_id = ? AND status IN ('pending', 'paid')
        ORDER BY created_at DESC LIMIT 1
    ''', (user_id,)).fetchone()
    conn.close()
    return dict(payment) if payment else None


def confirm_payment(order_id, admin_id, comment=None):
    """Подтвердить оплату. Идемпотентно. Возвращает dict или None."""
    conn = get_db_connection()
    cursor = conn.cursor()

    payment = cursor.execute(
        'SELECT * FROM payments WHERE order_id = ?', (order_id,),
    ).fetchone()
    if not payment:
        conn.close()
        return None

    if payment['status'] == 'confirmed':
        user = cursor.execute(
            'SELECT subscription_end_date, tokens_limit FROM users WHERE user_id = ?',
            (payment['user_id'],),
        ).fetchone()
        conn.close()
        return {
            'user_id': payment['user_id'],
            'already_processed': True,
            'days': 0,
            'bonus_days': 0,
            'end_date': (user['subscription_end_date'] if user else None),
            'tokens_limit': (user['tokens_limit'] if user else 0),
            'months': int(payment['months'] or 1),
        }

    if payment['status'] not in ('pending', 'paid'):
        conn.close()
        return None

    cursor.execute('''
        UPDATE payments
        SET status = 'confirmed',
            confirmed_at = CURRENT_TIMESTAMP,
            admin_comment = ?
        WHERE order_id = ? AND status IN ('pending', 'paid')
    ''', (comment or 'Confirmed', order_id))
    if cursor.rowcount == 0:
        conn.close()
        return None

    months = int(payment['months'] or 1)
    days = get_setting_int('subscription_days', 30) * months
    tokens_limit = get_setting_int('subscription_tokens', 50000000) * months

    bonus_days = 0
    user_row = cursor.execute(
        'SELECT limit_hit_at, subscription_end_date, subscription_status '
        'FROM users WHERE user_id = ?',
        (payment['user_id'],),
    ).fetchone()
    now = _utc_now()
    hit_at = _parse_ts(user_row['limit_hit_at']) if user_row else None
    pay_created = _parse_ts(payment['created_at'])
    if hit_at and (now - hit_at) <= timedelta(hours=24):
        bonus_days = 14
    elif pay_created and hit_at and abs((pay_created - hit_at).total_seconds()) <= 24 * 3600:
        bonus_days = 14
    days += bonus_days

    start = now
    if (
        user_row
        and user_row['subscription_status'] == 'active'
        and user_row['subscription_end_date']
    ):
        current_end = _parse_ts(user_row['subscription_end_date'])
        if current_end and current_end > start:
            start = current_end
    end_date = (start + timedelta(days=days)).strftime('%Y-%m-%d')

    cursor.execute('''
        UPDATE users
        SET subscription_status = 'active',
            tokens_limit = ?,
            tokens_used = 0,
            subscription_end_date = ?,
            renewal_notified = 0,
            limit_hit_at = NULL,
            sales_followup_step = 0
        WHERE user_id = ?
    ''', (tokens_limit, end_date, payment['user_id']))
    cursor.execute('''
        INSERT INTO logs (user_id, action, details)
        VALUES (?, ?, ?)
    ''', (
        payment['user_id'],
        'payment_confirmed',
        f'Order: {order_id} by admin {admin_id} days={days} bonus={bonus_days}',
    ))

    conn.commit()
    conn.close()
    flush_pending_referral_bonuses(payment['user_id'])
    return {
        'user_id': payment['user_id'],
        'already_processed': False,
        'days': days,
        'bonus_days': bonus_days,
        'end_date': end_date,
        'tokens_limit': tokens_limit,
        'months': months,
    }


def get_confirmed_buyers_count():
    """Число уникальных пользователей с подтверждённой оплатой (для соцдоказательства)"""
    conn = get_db_connection()
    count = conn.execute(
        "SELECT COUNT(DISTINCT user_id) FROM payments WHERE status = 'confirmed'"
    ).fetchone()[0]
    conn.close()
    return count


def touch_user_activity(user_id):
    """Отметить дневную активность (для retention). Пишет не чаще раза в день."""
    today = _utc_now().strftime('%Y-%m-%d')
    conn = get_db_connection()
    row = conn.execute(
        'SELECT last_activity FROM users WHERE user_id = ?', (user_id,)
    ).fetchone()
    if row is None:
        conn.close()
        return
    if (row['last_activity'] or '')[:10] != today:
        conn.execute(
            'UPDATE users SET last_activity = ? WHERE user_id = ?',
            (today, user_id),
        )
        conn.execute(
            'INSERT INTO logs (user_id, action, details) VALUES (?, ?, ?)',
            (user_id, 'active_day', today),
        )
        conn.commit()
    conn.close()


def eur_amount(amount, currency):
    """Пересчёт суммы в EUR по соотношению текущих цен месячного тарифа."""
    if currency == 'EUR' or not currency:
        return float(amount)
    key = {'UAH': 'price_uah', 'USD': 'price_usd'}.get(currency)
    if not key:
        return float(amount)
    eur = float(get_setting('price_eur', '15') or 0)
    cur = float(get_setting(key, '0') or 0)
    if eur <= 0 or cur <= 0:
        return float(amount)
    return float(amount) * eur / cur


def get_analytics_summary():
    """Сводка ключевых метрик: LTV, CR, retention, токены."""
    conn = get_db_connection()

    total_users = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    paying_users = conn.execute(
        "SELECT COUNT(DISTINCT user_id) FROM payments WHERE status = 'confirmed'"
    ).fetchone()[0]

    revenue_rows = conn.execute(
        "SELECT amount, currency FROM payments WHERE status = 'confirmed'"
    ).fetchall()
    revenue_by_currency = {}
    revenue_eur = 0.0
    for r in revenue_rows:
        cur = r['currency'] or '?'
        revenue_by_currency[cur] = revenue_by_currency.get(cur, 0) + (r['amount'] or 0)
        revenue_eur += eur_amount(r['amount'] or 0, cur)

    free_limit = int(get_setting('free_requests', '3'))
    exhausted = conn.execute(
        'SELECT COUNT(*) FROM users WHERE free_requests_used >= ?', (free_limit,)
    ).fetchone()[0]
    exhausted_paid = conn.execute('''
        SELECT COUNT(DISTINCT u.user_id) FROM users u
        JOIN payments p ON p.user_id = u.user_id AND p.status = 'confirmed'
        WHERE u.free_requests_used >= ?
    ''', (free_limit,)).fetchone()[0]

    retention = {}
    for day in (1, 7, 30):
        cohort = conn.execute(
            "SELECT COUNT(*) FROM users WHERE date(created_at) <= date('now', ?)",
            (f'-{day} day',),
        ).fetchone()[0]
        returned = conn.execute('''
            SELECT COUNT(DISTINCT u.user_id) FROM users u
            JOIN logs l ON l.user_id = u.user_id
            WHERE date(u.created_at) <= date('now', ?)
              AND date(l.created_at) = date(u.created_at, ?)
        ''', (f'-{day} day', f'+{day} day')).fetchone()[0]
        retention[day] = {
            'cohort': cohort,
            'returned': returned,
            'pct': round(returned / cohort * 100, 1) if cohort else 0,
        }

    # Токены за последние 30 дней — из логов запросов (charged=N)
    request_logs = conn.execute('''
        SELECT details FROM logs
        WHERE action = 'request' AND date(created_at) >= date('now', '-30 day')
    ''').fetchall()
    generations = len(request_logs)
    tokens_charged = 0
    for r in request_logs:
        for part in (r['details'] or '').split():
            if part.startswith('charged='):
                try:
                    tokens_charged += int(part[8:])
                except ValueError:
                    pass
                break
    active_users_30d = conn.execute('''
        SELECT COUNT(DISTINCT user_id) FROM logs
        WHERE action = 'request' AND date(created_at) >= date('now', '-30 day')
    ''').fetchone()[0]

    conn.close()
    return {
        'total_users': total_users,
        'paying_users': paying_users,
        'revenue_by_currency': revenue_by_currency,
        'revenue_eur': round(revenue_eur, 2),
        'ltv_eur': round(revenue_eur / paying_users, 2) if paying_users else 0,
        'cr_total_pct': round(paying_users / total_users * 100, 1) if total_users else 0,
        'exhausted': exhausted,
        'exhausted_paid': exhausted_paid,
        'cr_exhausted_pct': (
            round(exhausted_paid / exhausted * 100, 1) if exhausted else 0
        ),
        'retention': retention,
        'generations_30d': generations,
        'tokens_charged_30d': tokens_charged,
        'avg_tokens_per_generation': (
            round(tokens_charged / generations) if generations else 0
        ),
        'avg_tokens_per_user_30d': (
            round(tokens_charged / active_users_30d) if active_users_30d else 0
        ),
    }


def get_channels_report():
    """Отчёт по источникам (UTM): переходы, активации, покупки, касса, CAC."""
    conn = get_db_connection()
    rows = conn.execute('''
        SELECT COALESCE(NULLIF(u.referer, ''), 'organic') AS source,
               COUNT(DISTINCT u.user_id) AS users,
               SUM(CASE WHEN u.free_requests_used > 0
                         OR u.subscription_status IN ('active', 'expired')
                   THEN 1 ELSE 0 END) AS activated,
               COUNT(DISTINCT p.user_id) AS paid
        FROM users u
        LEFT JOIN payments p ON p.user_id = u.user_id AND p.status = 'confirmed'
        GROUP BY source
        ORDER BY users DESC
    ''').fetchall()
    revenue_rows = conn.execute('''
        SELECT COALESCE(NULLIF(u.referer, ''), 'organic') AS source,
               p.amount, p.currency
        FROM payments p
        JOIN users u ON u.user_id = p.user_id
        WHERE p.status = 'confirmed'
    ''').fetchall()
    spend_rows = conn.execute('''
        SELECT setting_key, setting_value FROM admin_settings
        WHERE setting_key LIKE 'ad_spend_%'
    ''').fetchall()
    conn.close()

    revenue = {}
    for r in revenue_rows:
        revenue[r['source']] = (
            revenue.get(r['source'], 0) + eur_amount(r['amount'] or 0, r['currency'])
        )
    spend = {}
    for r in spend_rows:
        try:
            spend[r['setting_key'][len('ad_spend_'):]] = float(r['setting_value'])
        except (ValueError, TypeError):
            pass

    report = []
    for r in rows:
        d = dict(r)
        source = d['source']
        d['activated'] = d['activated'] or 0
        d['revenue_eur'] = round(revenue.get(source, 0), 2)
        d['cr_pct'] = round(d['paid'] / d['users'] * 100, 1) if d['users'] else 0
        d['spend_eur'] = spend.get(source)
        d['cac_eur'] = (
            round(spend[source] / d['paid'], 2)
            if source in spend and d['paid'] else None
        )
        report.append(d)
    return report


def get_expiring_subscriptions(days=3):
    """Активные подписки, истекающие в ближайшие N дней, без отправленного напоминания"""
    conn = get_db_connection()
    deadline = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')
    today = datetime.now().strftime('%Y-%m-%d')
    rows = conn.execute('''
        SELECT user_id, language, subscription_end_date FROM users
        WHERE subscription_status = 'active'
          AND COALESCE(renewal_notified, 0) = 0
          AND subscription_end_date IS NOT NULL
          AND subscription_end_date >= ?
          AND subscription_end_date <= ?
    ''', (today, deadline)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_renewal_notified(user_id):
    conn = get_db_connection()
    conn.execute(
        'UPDATE users SET renewal_notified = 1 WHERE user_id = ?', (user_id,)
    )
    conn.commit()
    conn.close()


def reject_payment(order_id, admin_id, reason=None):
    """Отклонить только pending/paid. Возвращает user_id или None."""
    conn = get_db_connection()
    payment = conn.execute(
        'SELECT user_id, status FROM payments WHERE order_id = ?', (order_id,)
    ).fetchone()
    if not payment or payment['status'] not in ('pending', 'paid'):
        conn.close()
        return None

    conn.execute('''
        UPDATE payments
        SET status = 'rejected',
            admin_comment = ?
        WHERE order_id = ? AND status IN ('pending', 'paid')
    ''', (reason or 'Rejected', order_id))
    conn.execute('''
        INSERT INTO logs (user_id, action, details)
        VALUES (?, 'payment_rejected', ?)
    ''', (payment['user_id'], f'Order: {order_id} by admin {admin_id}: {reason or "Rejected"}'))
    conn.commit()
    conn.close()
    return payment['user_id']


def user_eligible_for_bonus_24h(user_id):
    """Показывать оффер +14 дней только если он реально применим."""
    user = get_user(user_id)
    if not user or not user.get('limit_hit_at'):
        return False
    hit_at = _parse_ts(user['limit_hit_at'])
    if not hit_at:
        return False
    return (_utc_now() - hit_at) <= timedelta(hours=24)


def update_payment_screenshot(order_id, file_id, caption=None):
    conn = get_db_connection()
    conn.execute('''
        UPDATE payments
        SET screenshot_file_id = ?,
            screenshot_caption = ?,
            status = 'paid'
        WHERE order_id = ?
    ''', (file_id, caption, order_id))
    conn.commit()
    conn.close()


def update_payment_txid(order_id, txid):
    conn = get_db_connection()
    conn.execute('''
        UPDATE payments SET txid = ?, status = 'paid' WHERE order_id = ?
    ''', (txid, order_id))
    conn.commit()
    conn.close()


# --- Статистика для админа ---

def get_admin_stats():
    conn = get_db_connection()

    total_users = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    active_subs = conn.execute(
        'SELECT COUNT(*) FROM users WHERE subscription_status = "active"'
    ).fetchone()[0]
    trial_users = conn.execute(
        'SELECT COUNT(*) FROM users WHERE subscription_status = "trial"'
    ).fetchone()[0]
    expired = conn.execute(
        'SELECT COUNT(*) FROM users WHERE subscription_status = "expired"'
    ).fetchone()[0]

    today = datetime.now().strftime('%Y-%m-%d')
    today_requests = conn.execute('''
        SELECT COUNT(*) FROM logs
        WHERE action = "request" AND DATE(created_at) = ?
    ''', (today,)).fetchone()[0]

    pending = conn.execute(
        'SELECT COUNT(*) FROM payments WHERE status IN ("pending", "paid")'
    ).fetchone()[0]

    total_revenue = conn.execute('''
        SELECT COALESCE(SUM(amount), 0) FROM payments WHERE status = "confirmed"
    ''').fetchone()[0]

    total_requests = conn.execute(
        'SELECT COUNT(*) FROM logs WHERE action = "request"'
    ).fetchone()[0]

    total_tokens_used = conn.execute(
        'SELECT COALESCE(SUM(tokens_used), 0) FROM users'
    ).fetchone()[0]

    conn.close()

    return {
        'total_users': total_users,
        'active_subs': active_subs,
        'trial_users': trial_users,
        'expired': expired,
        'today_requests': today_requests,
        'pending_payments': pending,
        'total_revenue': total_revenue,
        'total_requests': total_requests,
        'total_tokens_used': total_tokens_used,
    }


def get_user_token_info(user_id):
    """Детальная информация о токенах пользователя (как в профиле клиента)"""
    user = get_user(user_id)
    if not user:
        return None

    limit = get_tokens_limit(user_id)
    used = user['tokens_used'] or 0
    remaining = max(0, limit - used)
    percent = round((used / limit) * 100, 1) if limit > 0 else 0

    return {
        'user_id': user['user_id'],
        'username': user['username'],
        'first_name': user['first_name'],
        'subscription_status': user['subscription_status'],
        'subscription_end_date': user['subscription_end_date'],
        'tokens_limit': limit,
        'tokens_used': used,
        'tokens_remaining': remaining,
        'bonus_tokens': user['bonus_tokens'] or 0,
        'percent_used': percent,
        'total_referrals': user['total_referrals'] or 0,
        'referral_code': user['referral_code'],
    }


def get_tokens_usage_summary():
    """Сводка по токенам для админа"""
    conn = get_db_connection()
    today = datetime.now().strftime('%Y-%m-%d')

    total_used = conn.execute(
        'SELECT COALESCE(SUM(tokens_used), 0) FROM users'
    ).fetchone()[0]

    active_used = conn.execute('''
        SELECT COALESCE(SUM(tokens_used), 0) FROM users
        WHERE subscription_status = "active"
    ''').fetchone()[0]

    trial_used = conn.execute('''
        SELECT COALESCE(SUM(tokens_used), 0) FROM users
        WHERE subscription_status = "trial"
    ''').fetchone()[0]

    users_with_usage = conn.execute(
        'SELECT COUNT(*) FROM users WHERE tokens_used > 0'
    ).fetchone()[0]

    today_tokens = 0
    today_logs = conn.execute('''
        SELECT details FROM logs
        WHERE action = "request" AND DATE(created_at) = ?
    ''', (today,)).fetchall()
    for row in today_logs:
        details = row['details'] or ''
        # details: in=X out=Y charged=Z
        if 'charged=' in details:
            try:
                today_tokens += int(details.split('charged=')[1].split()[0])
            except (ValueError, IndexError):
                pass

    today_requests = len(today_logs)
    conn.close()

    return {
        'total_used': total_used,
        'active_used': active_used,
        'trial_used': trial_used,
        'users_with_usage': users_with_usage,
        'today_tokens': today_tokens,
        'today_requests': today_requests,
    }


def get_top_token_users(limit=10):
    """Топ пользователей по расходу токенов"""
    conn = get_db_connection()
    rows = conn.execute('''
        SELECT user_id, username, first_name, subscription_status,
               tokens_used, tokens_limit, bonus_tokens, subscription_end_date
        FROM users
        WHERE tokens_used > 0
        ORDER BY tokens_used DESC
        LIMIT ?
    ''', (limit,)).fetchall()
    conn.close()

    result = []
    for r in rows:
        user = dict(r)
        user_limit = get_tokens_limit(user['user_id'])
        used = user['tokens_used'] or 0
        remaining = max(0, user_limit - used)
        result.append({
            'user_id': user['user_id'],
            'username': user['username'],
            'first_name': user['first_name'],
            'subscription_status': user['subscription_status'],
            'tokens_used': used,
            'tokens_limit': user_limit,
            'tokens_remaining': remaining,
            'percent_used': round((used / user_limit) * 100, 1) if user_limit > 0 else 0,
        })
    return result


def get_low_token_users(threshold_percent=80, limit=10):
    """Пользователи с почти исчерпанным лимитом (>= threshold_percent%)"""
    conn = get_db_connection()
    rows = conn.execute('''
        SELECT user_id, username, first_name, subscription_status,
               tokens_used, tokens_limit, bonus_tokens
        FROM users
        WHERE tokens_used > 0
        ORDER BY tokens_used DESC
    ''').fetchall()
    conn.close()

    result = []
    for r in rows:
        user = dict(r)
        user_limit = get_tokens_limit(user['user_id'])
        used = user['tokens_used'] or 0
        if user_limit <= 0:
            continue
        percent = (used / user_limit) * 100
        if percent >= threshold_percent:
            result.append({
                'user_id': user['user_id'],
                'username': user['username'],
                'first_name': user['first_name'],
                'subscription_status': user['subscription_status'],
                'tokens_used': used,
                'tokens_limit': user_limit,
                'tokens_remaining': max(0, user_limit - used),
                'percent_used': round(percent, 1),
            })
        if len(result) >= limit:
            break
    return result


# --- Работа с промтами ---

def add_prompt(
    category,
    title,
    prompt_text,
    sort_order=0,
    description=None,
    system_prompt=None,
    variables=None,
    icon='📌',
):
    import json as _json
    conn = get_db_connection()
    cursor = conn.cursor()
    if isinstance(variables, (list, tuple)):
        variables = _json.dumps(list(variables), ensure_ascii=False)
    elif not variables:
        variables = '["topic"]'
    cursor.execute('''
        INSERT INTO prompts (
            category, title, description, system_prompt, prompt_text,
            variables, icon, sort_order
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        category, title, description, system_prompt, prompt_text,
        variables, icon or '📌', sort_order,
    ))
    conn.commit()
    prompt_id = cursor.lastrowid
    conn.close()
    return prompt_id


def get_prompts_by_category(category):
    conn = get_db_connection()
    prompts = conn.execute('''
        SELECT * FROM prompts
        WHERE category = ? AND is_active = 1
        ORDER BY sort_order, id
    ''', (category,)).fetchall()
    conn.close()
    return [dict(p) for p in prompts]


def get_category_counts():
    """Количество активных сценариев по каждой категории (для бейджей в библиотеке)"""
    conn = get_db_connection()
    rows = conn.execute('''
        SELECT category, COUNT(*) as cnt FROM prompts
        WHERE is_active = 1
        GROUP BY category
    ''').fetchall()
    conn.close()
    return {r['category']: r['cnt'] for r in rows}


def get_popular_prompts(limit=10):
    conn = get_db_connection()
    prompts = conn.execute('''
        SELECT * FROM prompts
        WHERE is_active = 1
        ORDER BY usage_count DESC, sort_order, id
        LIMIT ?
    ''', (limit,)).fetchall()
    conn.close()
    return [dict(p) for p in prompts]


def get_all_prompts():
    conn = get_db_connection()
    prompts = conn.execute('''
        SELECT * FROM prompts WHERE is_active = 1 ORDER BY category, sort_order
    ''').fetchall()
    conn.close()
    return [dict(p) for p in prompts]


def get_prompt(prompt_id):
    conn = get_db_connection()
    prompt = conn.execute('SELECT * FROM prompts WHERE id = ?', (prompt_id,)).fetchone()
    conn.close()
    return dict(prompt) if prompt else None


def parse_prompt_variables(prompt):
    """Список переменных промта из JSON / строки"""
    import json as _json
    raw = (prompt or {}).get('variables') if isinstance(prompt, dict) else prompt
    if not raw:
        return ['topic']
    if isinstance(raw, list):
        return raw
    try:
        data = _json.loads(raw)
        if isinstance(data, list) and data:
            return [str(x) for x in data]
    except Exception:
        pass
    return ['topic']


def update_prompt(
    prompt_id,
    title=None,
    prompt_text=None,
    is_active=None,
    sort_order=None,
    description=None,
    system_prompt=None,
    variables=None,
    icon=None,
):
    import json as _json
    conn = get_db_connection()
    updates = []
    params = []

    if title is not None:
        updates.append('title = ?')
        params.append(title)
    if prompt_text is not None:
        updates.append('prompt_text = ?')
        params.append(prompt_text)
    if is_active is not None:
        updates.append('is_active = ?')
        params.append(is_active)
    if sort_order is not None:
        updates.append('sort_order = ?')
        params.append(sort_order)
    if description is not None:
        updates.append('description = ?')
        params.append(description)
    if system_prompt is not None:
        updates.append('system_prompt = ?')
        params.append(system_prompt)
    if variables is not None:
        if isinstance(variables, (list, tuple)):
            variables = _json.dumps(list(variables), ensure_ascii=False)
        updates.append('variables = ?')
        params.append(variables)
    if icon is not None:
        updates.append('icon = ?')
        params.append(icon)

    if updates:
        params.append(prompt_id)
        conn.execute(f'UPDATE prompts SET {", ".join(updates)} WHERE id = ?', params)
        conn.commit()

    conn.close()


def set_prompt_multi_step(prompt_id, enabled):
    """Включить/выключить многошаговую генерацию для сценария"""
    conn = get_db_connection()
    cursor = conn.execute(
        'UPDATE prompts SET multi_step = ? WHERE id = ?',
        (1 if enabled else 0, prompt_id),
    )
    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return updated


def increment_prompt_usage(prompt_id):
    conn = get_db_connection()
    conn.execute(
        'UPDATE prompts SET usage_count = COALESCE(usage_count, 0) + 1 WHERE id = ?',
        (prompt_id,),
    )
    conn.commit()
    conn.close()


def delete_prompt(prompt_id):
    conn = get_db_connection()
    conn.execute('DELETE FROM prompts WHERE id = ?', (prompt_id,))
    conn.commit()
    conn.close()


def get_prompt_categories():
    conn = get_db_connection()
    categories = conn.execute('''
        SELECT DISTINCT category FROM prompts WHERE is_active = 1
    ''').fetchall()
    conn.close()
    return [c['category'] for c in categories]


def count_prompts():
    conn = get_db_connection()
    count = conn.execute('SELECT COUNT(*) FROM prompts').fetchone()[0]
    conn.close()
    return count


def reseed_prompts_if_outdated():
    """
    Если в БД старые промты без system_prompt/description —
    помечаем флаг, чтобы seed мог обновить (вызывается из prompts_data).
    """
    conn = get_db_connection()
    total = conn.execute('SELECT COUNT(*) FROM prompts').fetchone()[0]
    with_system = conn.execute(
        "SELECT COUNT(*) FROM prompts WHERE system_prompt IS NOT NULL AND system_prompt != ''"
    ).fetchone()[0]
    conn.close()
    return total, with_system


# --- Логирование ---

def log_action(user_id, action, details=None):
    conn = get_db_connection()
    conn.execute('''
        INSERT INTO logs (user_id, action, details)
        VALUES (?, ?, ?)
    ''', (user_id, action, details))
    conn.commit()
    conn.close()


def get_logs(limit=100, user_id=None):
    conn = get_db_connection()
    query = 'SELECT * FROM logs'
    params = []
    if user_id:
        query += ' WHERE user_id = ?'
        params.append(user_id)
    query += ' ORDER BY created_at DESC LIMIT ?'
    params.append(limit)
    logs = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(l) for l in logs]


# --- Broadcast ---

def create_broadcast(message):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO broadcasts (message, total_count, status)
        VALUES (?, (SELECT COUNT(*) FROM users), 'pending')
    ''', (message,))
    broadcast_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return broadcast_id


def update_broadcast_status(broadcast_id, status, sent_count=None):
    conn = get_db_connection()
    if sent_count is not None:
        conn.execute('''
            UPDATE broadcasts
            SET status = ?, sent_count = ?, completed_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (status, sent_count, broadcast_id))
    else:
        conn.execute('''
            UPDATE broadcasts SET status = ? WHERE id = ?
        ''', (status, broadcast_id))
    conn.commit()
    conn.close()


def get_all_users():
    conn = get_db_connection()
    users = conn.execute(
        'SELECT user_id, username, first_name FROM users'
    ).fetchall()
    conn.close()
    return [dict(u) for u in users]
