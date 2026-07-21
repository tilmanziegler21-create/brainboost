"""Обогащение запросов: текст из файлов и ссылок, динамические данные."""
import html
import logging
import re
import time

import requests

logger = logging.getLogger('brainboost')

ALLOWED_FILE_EXTS = {'.pdf', '.txt', '.csv'}
MAX_FILE_MB = 10
FILE_TEXT_LIMIT = 24000     # символов текста документа в промт
URL_TEXT_LIMIT = 8000       # символов текста одной страницы
MAX_URLS_PER_MESSAGE = 2

URL_RE = re.compile(r'https?://[^\s<>"\']+')

_UA = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'
)


def extract_urls(text):
    """Найти URL в тексте сообщения"""
    found = URL_RE.findall(text or '')
    cleaned = []
    for url in found:
        cleaned.append(url.rstrip('.,);]>\"\''))
    return cleaned


def _strip_html(raw):
    """Грубая, но безопасная очистка HTML до читаемого текста"""
    raw = re.sub(
        r'<(script|style|noscript|svg|head)\b.*?</\1>', ' ',
        raw, flags=re.DOTALL | re.IGNORECASE,
    )
    raw = re.sub(r'<br\s*/?>|</p>|</div>|</li>|</h[1-6]>', '\n', raw, flags=re.IGNORECASE)
    raw = re.sub(r'<[^>]+>', ' ', raw)
    raw = html.unescape(raw)
    raw = re.sub(r'[ \t]+', ' ', raw)
    raw = re.sub(r'\n\s*\n+', '\n\n', raw)
    return raw.strip()


def fetch_url_text(url, limit=URL_TEXT_LIMIT):
    """Скачать страницу и вернуть её текст. None, если прочитать не удалось."""
    try:
        resp = requests.get(
            url, timeout=15, headers={'User-Agent': _UA}, allow_redirects=True
        )
        if resp.status_code != 200:
            logger.info('URL fetch %s -> HTTP %s', url, resp.status_code)
            return None
        content_type = resp.headers.get('Content-Type', '')
        if content_type and 'html' not in content_type and 'text' not in content_type:
            return None
        text = _strip_html(resp.text)
        if len(text) < 200:
            # Заглушка для ботов / пустая страница
            return None
        return text[:limit]
    except Exception as exc:
        logger.info('URL fetch failed %s: %s', url, exc)
        return None


def extract_file_text(path, ext, limit=FILE_TEXT_LIMIT):
    """Извлечь текст из PDF/TXT/CSV. Пустая строка, если текста нет."""
    ext = ext.lower()
    if ext in ('.txt', '.csv'):
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read(limit).strip()
    if ext == '.pdf':
        from pypdf import PdfReader
        reader = PdfReader(path)
        parts = []
        total = 0
        for page in reader.pages:
            page_text = page.extract_text() or ''
            parts.append(page_text)
            total += len(page_text)
            if total >= limit:
                break
        return '\n'.join(parts)[:limit].strip()
    return ''


# --- Динамические данные ---

_CURRENCY_KEYWORDS = (
    'курс', 'валют', 'гривн', 'доллар', 'евро',
    'currency', 'exchange rate', 'dollar', 'euro', 'hryvnia',
    'wechselkurs', 'währung', 'divisa', 'tipo de cambio',
    'usd', 'eur', 'uah', 'usdt',
)

_rates_cache = {'ts': 0.0, 'text': None}
_RATES_TTL = 3600  # час


def _fetch_rates_line():
    """Актуальные курсы EUR→USD/UAH (open.er-api.com, без ключа)"""
    try:
        resp = requests.get('https://open.er-api.com/v6/latest/EUR', timeout=10)
        data = resp.json()
        rates = data.get('rates') or {}
        usd, uah = rates.get('USD'), rates.get('UAH')
        if not usd or not uah:
            return None
        return (
            f"Live exchange rates: 1 EUR = {usd:.2f} USD, "
            f"1 EUR = {uah:.2f} UAH, 1 USD = {uah / usd:.2f} UAH."
        )
    except Exception as exc:
        logger.info('Rates fetch failed: %s', exc)
        return None


def dynamic_context(prompt_text):
    """Строка с актуальными данными для системного промта.

    Дата и время добавляются всегда; курсы валют — только если запрос
    похож на валютную тему (экономия токенов).
    """
    now = time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())
    lines = [f"Current date and time: {now}."]

    lowered = (prompt_text or '').lower()
    if any(k in lowered for k in _CURRENCY_KEYWORDS):
        cached = _rates_cache
        if cached['text'] is None or time.time() - cached['ts'] > _RATES_TTL:
            cached['text'] = _fetch_rates_line()
            cached['ts'] = time.time()
        if cached['text']:
            lines.append(cached['text'])

    return ' '.join(lines)
