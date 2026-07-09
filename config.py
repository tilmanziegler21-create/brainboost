import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')


def _parse_admin_ids(raw):
    """Парсит ADMIN_IDS: '123,456' → [123, 456]. Игнорирует мусор."""
    if not raw:
        return []
    ids = []
    for part in raw.split(','):
        part = part.strip()
        if not part:
            continue
        # На случай если в Value случайно попало "ADMIN_IDS=123"
        if '=' in part:
            part = part.split('=', 1)[-1].strip()
        if part.isdigit() or (part.startswith('-') and part[1:].isdigit()):
            ids.append(int(part))
    return ids


ADMIN_IDS = _parse_admin_ids(os.getenv('ADMIN_IDS', ''))

# Остальные настройки берутся из БД через функцию get_setting()
