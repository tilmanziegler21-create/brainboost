import logging
import os
from datetime import datetime

LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
os.makedirs(LOGS_DIR, exist_ok=True)

logger = logging.getLogger('brainboost')


def setup_logging():
    """Настройка логирования в файл и консоль"""
    log_file = os.path.join(LOGS_DIR, 'bot.log')

    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO,
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(),
        ],
    )
    return logger


def format_tokens(n):
    """Форматирование числа токенов: 50000000 -> 50M"""
    if n is None:
        return '0'
    n = int(n)
    if n >= 1_000_000:
        return f'{n / 1_000_000:.0f}M' if n % 1_000_000 == 0 else f'{n / 1_000_000:.1f}M'
    if n >= 1_000:
        return f'{n / 1_000:.0f}K' if n % 1_000 == 0 else f'{n / 1_000:.1f}K'
    return str(n)


def format_token_bar(percent, width=10):
    """Прогресс-бар использования токенов (цветные квадраты вместо блочных символов)"""
    percent = max(0, min(100, float(percent)))
    filled = int(round(percent / 100 * width))
    empty = width - filled
    if percent >= 90:
        mark, fill_icon = '🔴', '🟥'
    elif percent >= 70:
        mark, fill_icon = '🟡', '🟨'
    else:
        mark, fill_icon = '🟢', '🟩'
    bar = fill_icon * filled + '⬜️' * empty
    return f'{mark} {bar} {percent:.0f}%'


def format_status(status):
    """Человекочитаемый статус подписки"""
    mapping = {
        'trial': '🎁 Пробный период',
        'active': '✅ Активна',
        'expired': '⏰ Истекла',
        'blocked': '🚫 Заблокирован',
    }
    return mapping.get(status, status)


def format_payment_method(method):
    mapping = {
        'card_uah': '💳 Карта UAH',
        'card_eur': '💳 Карта EUR',
        'usdt': '🪙 USDT (TRC20)',
    }
    return mapping.get(method, method)


def is_true(value):
    """Проверка строкового булева значения из БД"""
    if value is None:
        return False
    return str(value).lower() in ('true', '1', 'yes', 'on')


def escape_markdown(text):
    """Экранирование спецсимволов Markdown"""
    if not text:
        return ''
    for ch in ('_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!'):
        text = text.replace(ch, f'\\{ch}')
    return text


def truncate(text, length=200):
    if not text:
        return ''
    if len(text) <= length:
        return text
    return text[:length] + '...'


def now_str():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')
