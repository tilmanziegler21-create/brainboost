import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import requests
from database import get_setting

logger = logging.getLogger('brainboost')

# Провайдер — ТОЛЬКО через Claude Code CLI
DEFAULT_BASE_URL = 'https://claude-code-cli.vibecode-claude.online'
# opus-4-8 часто даёт 400 (thinking) — по умолчанию 4-7 стабильнее
DEFAULT_MODEL = 'claude-opus-4-7'
DEFAULT_CLIENT_VERSION = '2.1.205'
MIN_CLI_VERSION = '2.1.150'

MODEL_MULTIPLIERS = {
    'claude-fable-5': 2.0,
    'claude-opus-4-8': 1.0,
    'claude-opus-4-7': 1.0,
    'claude-opus-4-6': 1.0,
    'claude-opus-4-5': 1.0,
    'claude-sonnet-5': 0.7,
    'claude-sonnet-4-6': 0.7,
    'claude-sonnet-4-5': 0.7,
    'claude-sonnet-4': 0.7,
    'claude-haiku-4-5': 0.3,
}

AVAILABLE_MODELS = [
    ('claude-opus-4-7', 'Opus 4.7 (1.0x) ★'),
    ('claude-opus-4-8', 'Opus 4.8 (1.0x)'),
    ('claude-sonnet-5', 'Sonnet 5 (0.7x)'),
    ('claude-sonnet-4-6', 'Sonnet 4.6 (0.7x)'),
    ('claude-haiku-4-5', 'Haiku 4.5 (0.3x)'),
    ('claude-fable-5', 'Fable 5 (2.0x)'),
]


def get_claude_config():
    api_key = get_setting('claude_api_key')
    base_url = get_setting('claude_api_url', DEFAULT_BASE_URL).rstrip('/')
    for suffix in ('/v1/messages', '/v1/usage', '/v1'):
        if base_url.endswith(suffix):
            base_url = base_url[: -len(suffix)]
            break
    model = get_setting('claude_model', DEFAULT_MODEL)
    return api_key, base_url, model


def get_model_multiplier(model=None):
    if model is None:
        _, _, model = get_claude_config()
    return MODEL_MULTIPLIERS.get(model, 1.0)


def find_claude_bin():
    custom = get_setting('claude_cli_path')
    if custom and os.path.isfile(custom) and os.access(custom, os.X_OK):
        return custom
    for name in ('claude', 'claude-code'):
        path = shutil.which(name)
        if path:
            return path
    home = Path.home()
    candidates = [
        home / '.local' / 'bin' / 'claude',
        Path('/home/bot/.local/bin/claude'),
        Path('/usr/local/bin/claude'),
        Path('/root/.local/bin/claude'),
    ]
    for c in candidates:
        if c.is_file() and os.access(c, os.X_OK):
            return str(c)
    return None


def get_cli_version(claude_bin=None):
    claude_bin = claude_bin or find_claude_bin()
    if not claude_bin:
        return None
    try:
        out = subprocess.check_output(
            [claude_bin, '--version'],
            text=True,
            timeout=15,
            stderr=subprocess.STDOUT,
        ).strip()
        m = re.search(r'(\d+\.\d+\.\d+)', out)
        return m.group(1) if m else out
    except Exception:
        return None


def _version_tuple(v):
    parts = []
    for p in (v or '0').split('.'):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def cli_version_ok(version=None):
    version = version or get_cli_version()
    if not version:
        return False
    return _version_tuple(version) >= _version_tuple(MIN_CLI_VERSION)


def _stable_home():
    """
    Постоянный HOME для CLI.
    Провайдер привязывает ключ к устройству — нельзя менять HOME на каждый запрос.
    """
    custom = get_setting('claude_home')
    if custom:
        path = Path(custom)
    else:
        # Предпочитаем домашний каталог пользователя контейнера
        path = Path(os.environ.get('HOME') or Path.home())
        if not os.access(path, os.W_OK):
            path = Path(tempfile.gettempdir()) / 'brainboost_claude_home'
    path.mkdir(parents=True, exist_ok=True)
    (path / '.claude').mkdir(parents=True, exist_ok=True)
    return path


def _build_settings(api_key, base_url):
    """settings.json строго по инструкции провайдера + отключение thinking"""
    return {
        'env': {
            'ANTHROPIC_BASE_URL': base_url,
            'ANTHROPIC_API_KEY': api_key,
            'DISABLE_TELEMETRY': '1',
            'DISABLE_ERROR_REPORTING': '1',
            'CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK': '1',
            'DISABLE_AUTOUPDATER': '1',
            'DISABLE_BUG_COMMAND': '1',
            'DISABLE_COST_WARNINGS': '1',
            'DISABLE_NON_ESSENTIAL_MODEL_CALLS': '1',
            'CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY': '1',
            # Снижает 400 на opus-4-8 (thinking / beta headers)
            'MAX_THINKING_TOKENS': '0',
            'CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS': '1',
            'DISABLE_INTERLEAVED_THINKING': '1',
        }
    }


def _provider_env(api_key, base_url, home_dir):
    """Env процесса claude — как в инструкции + стабильный HOME"""
    env = os.environ.copy()
    env['HOME'] = str(home_dir)
    env['USERPROFILE'] = str(home_dir)
    env['ANTHROPIC_BASE_URL'] = base_url
    env['ANTHROPIC_API_KEY'] = api_key
    # Вариант 1 из инструкции провайдера
    env['ANTHROPIC_CUSTOM_HEADERS'] = f'X-Api-Key: {api_key}'
    env['DISABLE_TELEMETRY'] = '1'
    env['DISABLE_ERROR_REPORTING'] = '1'
    env['DISABLE_AUTOUPDATER'] = '1'
    env['DISABLE_COST_WARNINGS'] = '1'
    env['DISABLE_BUG_COMMAND'] = '1'
    env['DISABLE_NON_ESSENTIAL_MODEL_CALLS'] = '1'
    env['CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK'] = '1'
    env['CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY'] = '1'
    env['CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS'] = '1'
    env['MAX_THINKING_TOKENS'] = '0'
    env['DISABLE_INTERLEAVED_THINKING'] = '1'
    env['CI'] = '1'
    env['TERM'] = 'dumb'
    # Убрать конфликтующие токены OAuth, если вдруг есть
    for k in ('ANTHROPIC_AUTH_TOKEN', 'CLAUDE_CODE_OAUTH_TOKEN'):
        env.pop(k, None)
    return env


def _write_settings(home_dir, api_key, base_url):
    settings_path = Path(home_dir) / '.claude' / 'settings.json'
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings = _build_settings(api_key, base_url)
    settings_path.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    return settings_path


def check_usage():
    api_key, base_url, _ = get_claude_config()

    if not api_key or api_key in ('sk-ant-api-xxx', 'Не настроен'):
        return False, 'API ключ не настроен'

    url = f'{base_url}/v1/usage'
    try:
        response = requests.get(
            url,
            headers={
                'X-Api-Key': api_key,
                'Content-Type': 'application/json',
            },
            timeout=20,
        )
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
    if isinstance(data, str):
        return data

    lines = ['💳 *Баланс провайдера*\n']
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

    for nest_key in ('usage', 'limits', 'account', 'data'):
        nested = data.get(nest_key)
        if isinstance(nested, dict):
            lines.append(f'\n*{nest_key}:*')
            for k, v in nested.items():
                if not isinstance(v, (dict, list)):
                    lines.append(f'• {k}: `{v}`')

    if len(lines) == 1:
        raw = json.dumps(data, ensure_ascii=False, indent=2)
        if len(raw) > 1500:
            raw = raw[:1500] + '...'
        lines.append(f'```\n{raw}\n```')

    return '\n'.join(lines)


def call_claude(prompt, system_prompt=None, max_tokens=4096):
    """
    Запрос через Claude Code CLI.
    Возвращает: (response_text, input_tokens, output_tokens)
    """
    api_key, base_url, model = get_claude_config()

    if not api_key or api_key in ('sk-ant-api-xxx', 'Не настроен'):
        return "⚠️ API ключ Claude не настроен. Обратитесь к администратору.", 0, 0

    claude_bin = find_claude_bin()
    if not claude_bin:
        return (
            "⚠️ Claude Code CLI не установлен на сервере.\n"
            "Нужна версия ≥ 2.1.150. Без CLI ключ провайдера не работает.",
            0, 0,
        )

    version = get_cli_version(claude_bin)
    if version and not cli_version_ok(version):
        return (
            f"⚠️ Claude Code CLI слишком старый: {version}\n"
            f"Нужно ≥ {MIN_CLI_VERSION}. На сервере: `claude update`",
            0, 0,
        )

    home_dir = _stable_home()
    settings_path = _write_settings(home_dir, api_key, base_url)
    env = _provider_env(api_key, base_url, home_dir)

    # Рабочая директория для сессии (не HOME — HOME стабильный)
    work_dir = tempfile.mkdtemp(prefix='bb_claude_work_')
    try:
        cmd = [
            claude_bin,
            '-p',
            '--output-format', 'json',
            '--model', model,
            '--tools', '',
            '--no-session-persistence',
            '--permission-mode', 'dontAsk',
            '--settings', str(settings_path),
        ]
        if system_prompt:
            cmd.extend(['--system-prompt', system_prompt])

        cmd.append(prompt)

        timeout = int(get_setting('claude_timeout', '180') or 180)

        logger.info(
            'claude_cli call model=%s version=%s home=%s',
            model, version, home_dir,
        )

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=work_dir,
        )

        stdout = (result.stdout or '').strip()
        stderr = (result.stderr or '').strip()

        if result.returncode != 0 and not stdout:
            err = stderr or f'exit code {result.returncode}'
            logger.warning('claude_cli fail rc=%s err=%s', result.returncode, err[:500])
            return _friendly_cli_error(err), 0, 0

        # Ошибка может прийти в stdout как JSON с is_error
        text, inp, out, err_flag = _parse_cli_output(stdout, prompt, stderr)
        if err_flag or text.startswith('❌') or _looks_like_api_error(text + ' ' + stderr):
            combined = stderr or text
            if 'API Error' in text or 'error' in text.lower():
                combined = text
            return _friendly_cli_error(combined), 0, 0

        mult = get_model_multiplier(model)
        return text, int(inp * mult), int(out * mult)

    except subprocess.TimeoutExpired:
        return "⏰ Превышено время ожидания Claude CLI. Попробуй позже.", 0, 0
    except Exception as e:
        return f"❌ Ошибка CLI: {str(e)}", 0, 0
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _looks_like_api_error(text):
    lower = (text or '').lower()
    return any(x in lower for x in (
        'api error',
        'unexpected error',
        'please contact support',
        'please run claude update',
        'rate limit',
        'authentication',
    ))


def _parse_cli_output(stdout, prompt, stderr=''):
    """
    Разобрать --output-format json.
    Возвращает: (text, input_tokens, output_tokens, is_error)
    """
    if not stdout:
        return (stderr or "❌ Пустой ответ от Claude CLI"), 0, 0, True

    candidates = [stdout]
    if '\n' in stdout:
        candidates.extend(reversed(stdout.splitlines()))

    for chunk in candidates:
        chunk = chunk.strip()
        if not chunk.startswith('{'):
            continue
        try:
            data = json.loads(chunk)
        except json.JSONDecodeError:
            continue

        # CLI иногда кладёт ошибку в JSON
        is_error = bool(data.get('is_error') or data.get('error'))
        err_msg = ''
        if isinstance(data.get('error'), dict):
            err_msg = data['error'].get('message') or str(data['error'])
        elif isinstance(data.get('error'), str):
            err_msg = data['error']

        text = (
            data.get('result')
            or data.get('content')
            or data.get('text')
            or err_msg
            or ''
        )
        if isinstance(text, list):
            parts = []
            for block in text:
                if isinstance(block, dict) and block.get('text'):
                    parts.append(block['text'])
                elif isinstance(block, str):
                    parts.append(block)
            text = '\n'.join(parts)

        if not text and isinstance(data.get('message'), dict):
            content = data['message'].get('content')
            if isinstance(content, list) and content:
                text = content[0].get('text', '') if isinstance(content[0], dict) else str(content[0])
            elif isinstance(content, str):
                text = content

        usage = data.get('usage') or {}
        inp = usage.get('input_tokens') or usage.get('prompt_tokens') or int(len(prompt.split()) * 1.3)
        out = usage.get('output_tokens') or usage.get('completion_tokens') or int(len(str(text).split()) * 1.3)

        if text or is_error:
            if is_error and not text:
                text = err_msg or 'unknown CLI error'
            return str(text), int(inp), int(out), is_error or _looks_like_api_error(str(text))

    text = stdout
    return text, int(len(prompt.split()) * 1.3), int(len(text.split()) * 1.3), _looks_like_api_error(text)


def _friendly_cli_error(err):
    lower = (err or '').lower()
    if 'please run claude update' in lower or 'needs an update' in lower:
        return (
            "❌ Claude Code CLI устарел на сервере.\n"
            f"Нужна версия ≥ {MIN_CLI_VERSION}."
        )
    if 'root/sudo' in lower or 'cannot be used with root' in lower:
        return (
            "❌ Claude CLI нельзя запускать от root с bypassPermissions.\n"
            "Нужен редеплой образа (user bot)."
        )
    if '400' in lower and ('unexpected' in lower or 'support' in lower or 'thinking' in lower):
        return (
            "❌ Провайдер вернул 400 (часто на opus-4-8 / thinking).\n"
            "Попробуй:\n"
            "`/set_claude_model claude-opus-4-7`\n"
            "или `/set_claude_model claude-sonnet-4-6`\n\n"
            f"Детали: {err[:300]}"
        )
    if 'not logged in' in lower or 'please log in' in lower:
        return (
            "❌ Claude Code CLI требует логин на сервере (вариант 2).\n"
            "После логина запросы идут через ключ провайдера."
        )
    if 'authentication' in lower or '401' in lower or '403' in lower:
        return (
            "❌ Ключ отклонён (auth/403).\n"
            "Проверь баланс и что ключ не привязан к другому устройству "
            "(привязка сбрасывается раз в 8 часов)."
        )
    if 'low balance' in lower or 'add funds' in lower or 'insufficient' in lower:
        return (
            "❌ Ключ не подтянулся или баланс пуст.\n"
            "Проверь `/set_claude_api_key` и «Проверить баланс»."
        )
    if 'rate limit' in lower or '429' in lower:
        return (
            "❌ Rate limit.\n"
            "`/set_claude_model claude-opus-4-7` или подожди."
        )
    msg = err[:500] if err else 'unknown'
    return f"❌ Claude CLI: {msg}"


def test_connection():
    ok, usage = check_usage()
    if not ok:
        return False, f'Usage: {usage}'

    claude_bin = find_claude_bin()
    version = get_cli_version(claude_bin)
    if not claude_bin:
        return False, 'Claude Code CLI не найден на сервере'
    if version and not cli_version_ok(version):
        return False, f'CLI {version} < {MIN_CLI_VERSION}'

    text, inp, out = call_claude('Ответь одним словом: OK')
    if text.startswith('❌') or text.startswith('⚠️') or text.startswith('⏰'):
        return False, f'CLI: {text} (version={version})'
    return True, {
        'usage': usage,
        'reply': text,
        'tokens': inp + out,
        'cli_version': version,
        'cli_path': claude_bin,
        'home': str(_stable_home()),
    }
