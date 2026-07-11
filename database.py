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
        ('price_eur', '25', 'Цена в EUR'),
        ('price_usd', '27', 'Цена в USD'),
        ('price_uah', '1050', 'Цена в UAH'),
        ('free_requests', '10', 'Бесплатных запросов'),
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

    old_model = cursor.execute(
        "SELECT setting_value FROM admin_settings WHERE setting_key = 'claude_model'"
    ).fetchone()
    if old_model and old_model[0] in (
        'claude-3-5-sonnet-20241022',
        'claude-3-5-sonnet-20240620',
        'claude-3-opus-20240229',
        'claude-opus-4-8',  # часто 400 у провайдера — переключаем на стабильный 4-7
    ):
        cursor.execute(
            "UPDATE admin_settings SET setting_value = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE setting_key = 'claude_model'",
            ('claude-opus-4-7',),
        )

    cursor.execute(
        "UPDATE admin_settings SET setting_value = '2.1.198', "
        "updated_at = CURRENT_TIMESTAMP "
        "WHERE setting_key = 'claude_client_version' "
        "AND setting_value = '2.1.205'"
    )

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


def set_setting(key, value):
    """Обновить настройку"""
    conn = get_db_connection()
    conn.execute('''
        UPDATE admin_settings
        SET setting_value = ?, updated_at = CURRENT_TIMESTAMP
        WHERE setting_key = ?
    ''', (str(value), key))
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
    user_id, username, first_name, referred_by=None, last_name=None, language='en'
):
    conn = get_db_connection()
    cursor = conn.cursor()

    ref_code = hashlib.md5(f"{user_id}{random.randint(1000, 9999)}".encode()).hexdigest()[:8]
    free_limit = int(get_setting('free_tokens_limit', '1000000'))

    cursor.execute('''
        INSERT INTO users (
            user_id, username, first_name, last_name, referral_code,
            tokens_limit, referred_by, language
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        user_id, username, first_name, last_name, ref_code,
        free_limit, referred_by, language,
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
    conn = get_db_connection()
    referrer = get_user(referrer_id)
    if referrer and referrer['subscription_status'] == 'active':
        max_refs = int(get_setting('max_referrals', '5'))
        if referrer['total_referrals'] < max_refs:
            bonus = int(get_setting('referral_bonus', '5000000'))
            conn.execute('''
                UPDATE users
                SET bonus_tokens = bonus_tokens + ?,
                    total_referrals = total_referrals + 1
                WHERE user_id = ?
            ''', (bonus, referrer_id))

            conn.execute('''
                INSERT INTO logs (user_id, action, details)
                VALUES (?, ?, ?)
            ''', (referrer_id, 'referral_bonus', f'User {new_user_id}, bonus: {bonus}'))
            conn.commit()
    conn.close()


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

    if user['subscription_status'] == 'active':
        limit = int(get_setting('subscription_tokens', '50000000')) + user['bonus_tokens']
    else:
        limit = user['tokens_limit']

    remaining = limit - user['tokens_used']
    return max(0, remaining)


def get_tokens_limit(user_id):
    user = get_user(user_id)
    if not user:
        return 0
    if user['subscription_status'] == 'active':
        return int(get_setting('subscription_tokens', '50000000')) + user['bonus_tokens']
    return user['tokens_limit']


def get_free_requests_remaining(user_id):
    user = get_user(user_id)
    if not user or user['subscription_status'] != 'trial':
        return 0
    limit = int(get_setting('free_requests', '10'))
    return max(0, limit - (user.get('free_requests_used') or 0))


def activate_subscription(user_id):
    conn = get_db_connection()
    days = int(get_setting('subscription_days', '30'))
    end_date = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')
    tokens_limit = int(get_setting('subscription_tokens', '50000000'))

    conn.execute('''
        UPDATE users
        SET subscription_status = 'active',
            tokens_limit = ?,
            tokens_used = 0,
            subscription_end_date = ?
        WHERE user_id = ?
    ''', (tokens_limit, end_date, user_id))
    conn.commit()
    conn.close()


def check_and_expire_subscriptions():
    conn = get_db_connection()
    today = datetime.now().strftime('%Y-%m-%d')
    expired = conn.execute('''
        SELECT user_id FROM users
        WHERE subscription_status = 'active'
        AND subscription_end_date < ?
    ''', (today,)).fetchall()

    for user in expired:
        conn.execute('''
            UPDATE users SET subscription_status = 'expired' WHERE user_id = ?
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


# --- Работа с платежами ---

def create_payment(user_id, amount, currency, method):
    conn = get_db_connection()
    order_id = (
        f"BB-{datetime.now().strftime('%Y%m%d')}-"
        f"{hashlib.md5(f'{user_id}{datetime.now()}'.encode()).hexdigest()[:6].upper()}"
    )

    conn.execute('''
        INSERT INTO payments (user_id, amount, currency, payment_method, order_id, status)
        VALUES (?, ?, ?, ?, ?, 'pending')
    ''', (user_id, amount, currency, method, order_id))

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
    conn = get_db_connection()
    cursor = conn.cursor()

    payment = cursor.execute(
        'SELECT user_id FROM payments WHERE order_id = ?',
        (order_id,),
    ).fetchone()
    if not payment:
        conn.close()
        return None

    cursor.execute('''
        UPDATE payments
        SET status = 'confirmed',
            confirmed_at = CURRENT_TIMESTAMP,
            admin_comment = ?
        WHERE order_id = ?
    ''', (comment or 'Confirmed', order_id))

    days_row = cursor.execute(
        "SELECT setting_value FROM admin_settings WHERE setting_key = 'subscription_days'"
    ).fetchone()
    tokens_row = cursor.execute(
        "SELECT setting_value FROM admin_settings WHERE setting_key = 'subscription_tokens'"
    ).fetchone()
    days = int(days_row[0] if days_row else '30')
    end_date = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')
    tokens_limit = int(tokens_row[0] if tokens_row else '50000000')
    cursor.execute('''
        UPDATE users
        SET subscription_status = 'active',
            tokens_limit = ?,
            tokens_used = 0,
            subscription_end_date = ?
        WHERE user_id = ?
    ''', (tokens_limit, end_date, payment['user_id']))
    cursor.execute('''
        INSERT INTO logs (user_id, action, details)
        VALUES (?, ?, ?)
    ''', (
        payment['user_id'],
        'payment_confirmed',
        f'Order: {order_id} by admin {admin_id}',
    ))

    conn.commit()
    conn.close()
    return payment['user_id']


def reject_payment(order_id, admin_id, reason=None):
    conn = get_db_connection()
    conn.execute('''
        UPDATE payments
        SET status = 'rejected',
            admin_comment = ?
        WHERE order_id = ?
    ''', (reason or 'Rejected', order_id))
    conn.execute('''
        INSERT INTO logs (user_id, action, details)
        VALUES (
            (SELECT user_id FROM payments WHERE order_id = ?),
            'payment_rejected',
            ?
        )
    ''', (order_id, f'Order: {order_id} by admin {admin_id}: {reason or "Rejected"}'))
    conn.commit()
    conn.close()


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
