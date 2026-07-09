# BrainBoost Telegram Bot

Telegram-бот с Claude AI, админ-панелью, мультивалютной оплатой (UAH / EUR / USDT) и ручной проверкой платежей.

## Быстрый старт

### 1. Клонировать

```bash
git clone https://github.com/OWNER/brainboost_bot.git
cd brainboost_bot
```

### 2. Настроить окружение

```bash
cp .env.example .env
# Отредактируй .env:
# BOT_TOKEN=токен_от_BotFather
# ADMIN_IDS=твой_telegram_id
```

### 3. Установить и запустить

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

### 4. Настроить Claude API в боте

От админа в Telegram:

```
/admin
```

или командой:

```
/set_claude_api_key sk-ant-cap01-XXXXX
```

По умолчанию используется провайдер:
`https://claude-code-cli.vibecode-claude.online`, модель `claude-opus-4-8`.

В админке: **Claude API** → Проверить баланс / Тест соединения / смена модели.

## Docker

```bash
cp .env.example .env
# заполни BOT_TOKEN и ADMIN_IDS

docker compose up -d --build
docker compose logs -f
```

## Структура

| Файл | Назначение |
|------|------------|
| `main.py` | Точка входа |
| `config.py` | BOT_TOKEN, ADMIN_IDS |
| `database.py` | SQLite |
| `claude_api.py` | Claude через провайдер |
| `admin_panel.py` | Админ-панель |
| `handlers.py` | Команды и сообщения |
| `payment.py` | Оплата UAH/EUR/USDT |
| `keyboards.py` | Inline-клавиатуры |
| `prompts_data.py` | Готовые промты |

## Команды пользователя

- `/start` — меню
- `/buy` — подписка
- `/profile` — токены и статус
- `/referral` — рефералка
- `/help` — справка
- `/admin` — админ-панель (только ADMIN_IDS)

## Важно

- `.env`, `bot.db` и `logs/` не коммитятся
- Все настройки (цены, карты, Claude) хранятся в БД и меняются через админку
