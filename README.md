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

## Claude / провайдер

Ключ от `claude-code-cli.vibecode-claude.online` работает **только через Claude Code CLI**
(не через обычный HTTP). По мануалу нужны:

1. Claude Code CLI ≥ **2.1.150** (ставится в Docker)
2. **Логин** в Claude Code (даже бесплатный аккаунт) — шаг 2 мануала
3. `settings.json` **строго** как в инструкции (без лишних полей)
4. Ключ провайдера

После деплоя:

```
/set_claude_api_key sk-ant-cap01-XXXXX
/set_claude_oauth_token ТОКЕН_ИЗ_claude_setup-token
/set_claude_model claude-opus-4-7
```

Затем `/admin` → Claude API → Тест соединения.

Баланс: `GET /v1/usage` с заголовком `X-Api-Key`.


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
