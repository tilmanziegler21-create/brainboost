import requests
from database import get_setting

# Провайдер Claude Code CLI (прокси)
DEFAULT_BASE_URL = 'https://claude-code-cli.vibecode-claude.online'
DEFAULT_MODEL = 'claude-opus-4-8'

# Коэффициенты расхода токенов у провайдера
MODEL_MULTIPLIERS = {
    'claude-fable-5': 2.0,
    'claude-opus-4-8': 1.0,
    'claude-opus-4-7': 1.0,
    'claude-sonnet-4-6': 0.7,
    'claude-haiku-4-5': 0.3,
}

AVAILABLE_MODELS = [
    ('claude-opus-4-8', 'Opus 4.8 (1.0x)'),
    ('claude-sonnet-4-6', 'Sonnet 4.6 (0.7x)'),
    ('claude-haiku-4-5', 'Haiku 4.5 (0.3x)'),
    ('claude-fable-5', 'Fable 5 (2.0x)'),
]


def get_claude_config():
    """Получить настройки Claude из БД"""
    api_key = get_setting('claude_api_key')
    base_url = get_setting('claude_api_url', DEFAULT_BASE_URL).rstrip('/')
    # Если в БД лежит полный путь /v1/messages — берём только base
    for suffix in ('/v1/messages', '/v1/usage', '/v1'):
        if base_url.endswith(suffix):
            base_url = base_url[: -len(suffix)]
            break
    model = get_setting('claude_model', DEFAULT_MODEL)
    return api_key, base_url, model


def _auth_headers(api_key):
    """Заголовки для провайдера (X-Api-Key) + совместимость с Anthropic"""
    return {
        'X-Api-Key': api_key,
        'x-api-key': api_key,
        'anthropic-version': '2023-06-01',
        'Content-Type': 'application/json',
    }


def get_model_multiplier(model=None):
    if model is None:
        _, _, model = get_claude_config()
    return MODEL_MULTIPLIERS.get(model, 1.0)


def check_usage():
    """
    Проверить баланс/лимиты ключа через /v1/usage
    Возвращает: (ok: bool, data: dict | str)
    """
    api_key, base_url, _ = get_claude_config()

    if not api_key or api_key in ('sk-ant-api-xxx', 'Не настроен'):
        return False, 'API ключ не настроен'

    url = f'{base_url}/v1/usage'
    try:
        response = requests.get(url, headers=_auth_headers(api_key), timeout=20)
        if response.status_code == 200:
            return True, response.json()
        try:
            err = response.json()
            msg = err.get('error', {}).get('message') or err.get('message') or response.text[:300]
        except Exception:
            msg = response.text[:300]
        return False, f'HTTP {response.status_code}: {msg}'
    except requests.exceptions.Timeout:
        return False, 'Таймаут при проверке usage'
    except Exception as e:
        return False, str(e)


def format_usage_text(data):
    """Человекочитаемый текст баланса из ответа /v1/usage"""
    if isinstance(data, str):
        return data

    lines = ['💳 *Баланс провайдера*\n']

    # Разные возможные форматы ответа
    for key, label in [
        ('balance', 'Баланс'),
        ('credits', 'Кредиты'),
        ('remaining', 'Осталось'),
        ('limit', 'Лимит'),
        ('used', 'Использовано'),
        ('total', 'Всего'),
        ('plan', 'План'),
        ('status', 'Статус'),
        ('tokens_remaining', 'Токенов осталось'),
        ('tokens_used', 'Токенов использовано'),
        ('tokens_limit', 'Лимит токенов'),
        ('quota', 'Квота'),
        ('expires_at', 'Истекает'),
        ('reset_at', 'Сброс'),
    ]:
        if key in data and data[key] is not None:
            lines.append(f'• {label}: `{data[key]}`')

    # Вложенные объекты
    for nest_key in ('usage', 'limits', 'account', 'data'):
        nested = data.get(nest_key)
        if isinstance(nested, dict):
            lines.append(f'\n*{nest_key}:*')
            for k, v in nested.items():
                if not isinstance(v, (dict, list)):
                    lines.append(f'• {k}: `{v}`')

    if len(lines) == 1:
        # Неизвестный формат — покажем JSON кратко
        import json
        raw = json.dumps(data, ensure_ascii=False, indent=2)
        if len(raw) > 1500:
            raw = raw[:1500] + '...'
        lines.append(f'```\n{raw}\n```')

    return '\n'.join(lines)


def call_claude(prompt, system_prompt=None, max_tokens=4096):
    """
    Отправить запрос к Claude через провайдер
    Возвращает: (response_text, input_tokens, output_tokens)
    """
    api_key, base_url, model = get_claude_config()

    if not api_key or api_key in ('sk-ant-api-xxx', 'Не настроен'):
        return "⚠️ API ключ Claude не настроен. Обратитесь к администратору.", 0, 0

    url = f'{base_url}/v1/messages'
    headers = _auth_headers(api_key)

    messages = [{'role': 'user', 'content': prompt}]

    data = {
        'model': model,
        'messages': messages,
        'max_tokens': max_tokens,
        'stream': False,
    }

    if system_prompt:
        data['system'] = system_prompt

    try:
        response = requests.post(url, headers=headers, json=data, timeout=90)

        if response.status_code == 200:
            result = response.json()
            text = _extract_text(result)
            input_tokens, output_tokens = _extract_usage(result, prompt, text)

            # Учитываем коэффициент модели провайдера
            mult = get_model_multiplier(model)
            billed_in = int(input_tokens * mult)
            billed_out = int(output_tokens * mult)
            return text, billed_in, billed_out

        try:
            err = response.json()
            error_msg = (
                err.get('error', {}).get('message')
                or err.get('message')
                or str(err)[:300]
            )
        except Exception:
            error_msg = response.text[:300]
        return f"❌ Ошибка API: {response.status_code} - {error_msg}", 0, 0

    except requests.exceptions.Timeout:
        return "⏰ Превышено время ожидания. Попробуй позже.", 0, 0
    except Exception as e:
        return f"❌ Ошибка: {str(e)}", 0, 0


def _extract_text(result):
    """Достать текст ответа из разных форматов"""
    # Anthropic-совместимый: content[0].text
    content = result.get('content')
    if isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, dict) and 'text' in first:
            return first['text']
        if isinstance(first, str):
            return first

    # OpenAI-совместимый
    choices = result.get('choices')
    if isinstance(choices, list) and choices:
        msg = choices[0].get('message') or choices[0]
        if isinstance(msg, dict) and 'content' in msg:
            return msg['content']
        if 'text' in choices[0]:
            return choices[0]['text']

    if 'text' in result:
        return result['text']
    if 'response' in result:
        return result['response']
    if 'output' in result:
        return result['output'] if isinstance(result['output'], str) else str(result['output'])

    return str(result)[:2000]


def _extract_usage(result, prompt, text):
    usage = result.get('usage') or {}
    input_tokens = (
        usage.get('input_tokens')
        or usage.get('prompt_tokens')
        or int(len(prompt.split()) * 1.3)
    )
    output_tokens = (
        usage.get('output_tokens')
        or usage.get('completion_tokens')
        or int(len(text.split()) * 1.3)
    )
    return int(input_tokens), int(output_tokens)


def test_connection():
    """Быстрый тест ключа: usage + короткий messages"""
    ok, usage = check_usage()
    if not ok:
        return False, f'Usage: {usage}'

    text, inp, out = call_claude('Ответь одним словом: OK', max_tokens=16)
    if text.startswith('❌') or text.startswith('⚠️') or text.startswith('⏰'):
        return False, f'Messages: {text}'
    return True, {'usage': usage, 'reply': text, 'tokens': inp + out}
