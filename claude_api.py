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

# Провайдер — ТОЛЬКО через Claude Code CLI (мануал: «кроме CLI ключ НИГДЕ не работает»)
DEFAULT_BASE_URL = 'https://claude-code-cli.vibecode-claude.online'
DEFAULT_MODEL = 'claude-opus-4-7'
MIN_CLI_VERSION = '2.1.150'

# settings.json СТРОГО по мануалу провайдера — без лишних полей
MANUAL_SETTINGS_ENV_KEYS = (
    'ANTHROPIC_BASE_URL',
    'ANTHROPIC_API_KEY',
    'DISABLE_TELEMETRY',
    'DISABLE_ERROR_REPORTING',
    'CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK',
    'DISABLE_AUTOUPDATER',
    'DISABLE_BUG_COMMAND',
    'DISABLE_COST_WARNINGS',
    'DISABLE_NON_ESSENTIAL_MODEL_CALLS',
    'CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY',
)

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
    """ENV имеет приоритет; БД оставлена для обратной совместимости."""
    api_key = (
        os.environ.get('CLAUDE_API_KEY')
        or get_setting('claude_api_key')
        or ''
    ).strip()
    base_url = (
        os.environ.get('CLAUDE_API_URL')
        or get_setting('claude_api_url', DEFAULT_BASE_URL)
        or DEFAULT_BASE_URL
    ).strip().rstrip('/')
    for suffix in ('/v1/messages', '/v1/usage', '/v1'):
        if base_url.endswith(suffix):
            base_url = base_url[: -len(suffix)]
            break
    model = (
        os.environ.get('CLAUDE_MODEL')
        or get_setting('claude_model', DEFAULT_MODEL)
        or DEFAULT_MODEL
    ).strip()
    return api_key, base_url, model


def get_claude_config_source():
    return 'Render ENV' if os.environ.get('CLAUDE_API_KEY', '').strip() else 'База данных'


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
    for c in (
        home / '.local' / 'bin' / 'claude',
        Path('/home/bot/.local/bin/claude'),
        Path('/usr/local/bin/claude'),
        Path('/root/.local/bin/claude'),
    ):
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
    Реальный home пользователя процесса.
    CLI резолвит home через getpwuid, а не через $HOME, поэтому settings.json
    обязан лежать именно в реальном home — иначе CLI его не прочитает.
    """
    try:
        import pwd
        path = Path(pwd.getpwuid(os.getuid()).pw_dir)
    except (ImportError, KeyError):
        path = Path(os.environ.get('HOME') or Path.home())
    if not os.access(path, os.W_OK):
        path = Path('/tmp/brainboost_claude_home')
    path.mkdir(parents=True, exist_ok=True)
    (path / '.claude').mkdir(parents=True, exist_ok=True)
    return path


def _build_settings(api_key, base_url):
    """
    settings.json В ТОЧНОСТИ как в мануале провайдера.
    Цитата: «Содержимое settings.json должно быть в точности таким же…
    Любые лишние/недостающие поля могут привести к тому, что подключение не сработает.»
    """
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
        }
    }


def _write_settings(home_dir, api_key, base_url):
    settings_path = Path(home_dir) / '.claude' / 'settings.json'
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings = _build_settings(api_key, base_url)
    settings_path.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    return settings_path


def _apply_oauth_token(home_dir):
    """
    Мануал шаг 2: нужен логин в Claude Code (даже бесплатный аккаунт).
    На сервере интерактивный логин неудобен — можно передать токен:
      /set_claude_oauth_token TOKEN
    или env CLAUDE_CODE_OAUTH_TOKEN
    """
    token = (
        os.environ.get('CLAUDE_CODE_OAUTH_TOKEN')
        or get_setting('claude_oauth_token')
        or ''
    ).strip()
    if not token:
        return False

    cred_path = Path(home_dir) / '.claude' / '.credentials.json'
    cred_path.parent.mkdir(parents=True, exist_ok=True)
    # Минимальный формат, который CLI обычно принимает
    payload = {
        'claudeAiOauth': {
            'accessToken': token,
            'refreshToken': token,
            'expiresAt': '2099-01-01T00:00:00.000Z',
        }
    }
    # Если уже похоже на JSON credentials — пишем как есть
    if token.startswith('{'):
        try:
            payload = json.loads(token)
        except json.JSONDecodeError:
            pass

    cred_path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    try:
        os.chmod(cred_path, 0o600)
    except OSError:
        pass
    return True


def _has_cli_login(home_dir):
    """Есть ли рабочий способ авторизации CLI: provider key или OAuth."""
    api_key, _, _ = get_claude_config()
    if api_key and api_key not in ('sk-ant-api-xxx', 'Не настроен'):
        return True
    if os.environ.get('CLAUDE_CODE_OAUTH_TOKEN') or get_setting('claude_oauth_token'):
        return True
    home = Path(home_dir)
    for p in (
        home / '.claude' / '.credentials.json',
        home / '.claude' / 'credentials.json',
        home / '.credentials.json',
    ):
        if p.is_file() and p.stat().st_size > 10:
            return True
    # Глобальный ~/.claude.json иногда хранит сессию
    claude_json = home / '.claude.json'
    if claude_json.is_file():
        try:
            data = json.loads(claude_json.read_text(encoding='utf-8'))
            if data.get('oauthAccount') or data.get('primaryApiKey') or data.get('hasCompletedOnboarding'):
                return True
        except Exception:
            pass
    return False


def _provider_env(api_key, base_url, home_dir):
    """
    Env для процесса.
    Мануал вариант 1: ANTHROPIC_BASE_URL + ANTHROPIC_CUSTOM_HEADERS.
    Вариант 2: те же значения через settings.json (пишем файл отдельно).
    Не добавляем лишние переменные сверх мануала.
    """
    env = os.environ.copy()
    env['HOME'] = str(home_dir)
    env['USERPROFILE'] = str(home_dir)

    # Используем только вариант 2 из гайда: API key через settings.json.
    # CUSTOM_HEADERS относится к альтернативному варианту 1 и может создать
    # конфликт двух способов авторизации.
    env['ANTHROPIC_BASE_URL'] = base_url
    env['ANTHROPIC_API_KEY'] = api_key

    for key in MANUAL_SETTINGS_ENV_KEYS:
        if key in ('ANTHROPIC_BASE_URL', 'ANTHROPIC_API_KEY'):
            continue
        env[key] = '1'

    env['CI'] = '1'
    env['TERM'] = 'dumb'
    # Provider key — единственный способ авторизации этого процесса.
    for k in (
        'ANTHROPIC_AUTH_TOKEN',
        'ANTHROPIC_CUSTOM_HEADERS',
        'CLAUDE_CODE_OAUTH_TOKEN',
    ):
        env.pop(k, None)
    return env


def check_usage():
    api_key, base_url, _ = get_claude_config()
    if not api_key or api_key in ('sk-ant-api-xxx', 'Не настроен'):
        return False, 'API ключ не настроен'

    try:
        response = requests.get(
            f'{base_url}/v1/usage',
            headers={'X-Api-Key': api_key, 'Content-Type': 'application/json'},
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
        ('balance', 'Баланс'), ('credits', 'Кредиты'), ('remaining', 'Осталось'),
        ('limit', 'Лимит'), ('used', 'Использовано'), ('total', 'Всего'),
        ('plan', 'План'), ('status', 'Статус'),
        ('tokens_remaining', 'Токенов осталось'), ('tokens_used', 'Токенов использовано'),
        ('tokens_limit', 'Лимит токенов'), ('quota', 'Квота'),
        ('expires_at', 'Истекает'), ('reset_at', 'Сброс'),
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
        lines.append(f'```\n{raw[:1500]}\n```')
    return '\n'.join(lines)


def call_claude(prompt, system_prompt=None, max_tokens=4096):
    api_key, base_url, model = get_claude_config()

    if not api_key or api_key in ('sk-ant-api-xxx', 'Не настроен'):
        return "⚠️ API ключ Claude не настроен. Обратитесь к администратору.", 0, 0

    claude_bin = find_claude_bin()
    if not claude_bin:
        return (
            "⚠️ Claude Code CLI не установлен.\n"
            "По мануалу ключ работает ТОЛЬКО через Claude Code CLI ≥ 2.1.150.",
            0, 0,
        )

    version = get_cli_version(claude_bin)
    if version and not cli_version_ok(version):
        return (
            f"⚠️ CLI {version} слишком старый. Нужно ≥ {MIN_CLI_VERSION} (`claude update`).",
            0, 0,
        )

    home_dir = _stable_home()
    _write_settings(home_dir, api_key, base_url)

    env = _provider_env(api_key, base_url, home_dir)
    work_dir = tempfile.mkdtemp(prefix='bb_claude_work_')

    try:
        # Проверенный рабочий вызов через этот же шлюз:
        # claude -p --output-format json --system-prompt <sys> --model <model>
        # Текст запроса — через stdin, без дополнительных флагов.
        cmd = [
            claude_bin,
            '-p',
            '--output-format', 'json',
            '--model', model,
        ]
        if system_prompt:
            cmd.extend(['--system-prompt', system_prompt])

        timeout = int(get_setting('claude_timeout', '180') or 180)
        logger.info('claude_cli model=%s ver=%s home=%s', model, version, home_dir)

        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=work_dir,
        )

        stdout = (result.stdout or '').strip()
        stderr = (result.stderr or '').strip()

        if result.returncode != 0 and not stdout:
            logger.warning('claude_cli rc=%s err=%s', result.returncode, (stderr or '')[:500])
            return _friendly_cli_error(stderr or f'exit {result.returncode}'), 0, 0

        text, inp, out, is_err = _parse_cli_output(stdout, prompt, stderr)
        if is_err or text.startswith('❌') or _looks_like_api_error(text + ' ' + stderr):
            raw_error = text if _looks_like_api_error(text) else (stderr or text)
            logger.warning(
                'claude_cli api_error rc=%s out=%s err=%s',
                result.returncode,
                stdout[:500].replace(api_key, '[REDACTED]'),
                stderr[:500].replace(api_key, '[REDACTED]'),
            )
            return _friendly_cli_error(raw_error), 0, 0

        mult = get_model_multiplier(model)
        return text, int(inp * mult), int(out * mult)

    except subprocess.TimeoutExpired:
        logger.warning('claude_cli timeout model=%s', model)
        return "⏰ Таймаут Claude CLI. Попробуй позже.", 0, 0
    except Exception as e:
        logger.exception('claude_cli exception model=%s', model)
        return f"❌ Ошибка CLI: {str(e)}", 0, 0
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _looks_like_api_error(text):
    lower = (text or '').lower()
    return any(x in lower for x in (
        'api error', 'unexpected error', 'please contact support',
        'please run claude update', 'rate limit', 'please log in',
        'low balance', 'add funds', 'insufficient',
    ))


def _parse_cli_output(stdout, prompt, stderr=''):
    if not stdout:
        return (stderr or '❌ Пустой ответ от Claude CLI'), 0, 0, True

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

        is_error = bool(data.get('is_error') or data.get('error'))
        err_msg = ''
        if isinstance(data.get('error'), dict):
            err_msg = data['error'].get('message') or str(data['error'])
        elif isinstance(data.get('error'), str):
            err_msg = data['error']

        text = data.get('result') or data.get('content') or data.get('text') or err_msg or ''
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

    return stdout, int(len(prompt.split()) * 1.3), int(len(stdout.split()) * 1.3), _looks_like_api_error(stdout)


def _friendly_cli_error(err):
    lower = (err or '').lower()
    if 'please run claude update' in lower or 'needs an update' in lower:
        return f"❌ CLI устарел. Нужно ≥ {MIN_CLI_VERSION}."
    if 'root/sudo' in lower or 'cannot be used with root' in lower:
        return "❌ CLI нельзя с bypassPermissions от root. Нужен user bot в Docker."
    if 'please log in' in lower or 'not logged in' in lower:
        return (
            "❌ Нет логина Claude Code (мануал шаг 2).\n"
            "`/set_claude_oauth_token TOKEN` — даже бесплатный аккаунт."
        )
    if 'low balance' in lower or 'add funds' in lower or 'insufficient' in lower:
        return (
            "❌ Ключ не подтянулся (мануал FAQ #1/#6).\n"
            "Проверь settings.json / логин CLI / `/set_claude_api_key`."
        )
    if 'device limit' in lower:
        return (
            "❌ Ключ привязан к другому устройству.\n"
            "По гайду провайдера привязка сбрасывается раз в 8 часов.\n"
            "Не гоняй тест с разных HOME/машин — каждое считается устройством.\n\n"
            f"`{err[:250]}`"
        )
    if '400' in lower or 'unexpected error' in lower or 'support service' in lower:
        return (
            "❌ Провайдер вернул 400 без описания причины.\n"
            "settings.json сформирован по мануалу; проверь модель и состояние ключа у провайдера.\n\n"
            f"`{err[:250]}`"
        )
    if 'rate limit' in lower or '429' in lower:
        return "❌ Rate limit. `/set_claude_model claude-opus-4-7` или подожди."
    if '403' in lower or 'authentication' in lower:
        return "❌ Auth/403. Проверь ключ, баланс и привязку устройства (8ч)."
    return f"❌ Claude CLI: {(err or 'unknown')[:500]}"


def test_connection():
    ok, usage = check_usage()
    if not ok:
        return False, f'Usage: {usage}'

    claude_bin = find_claude_bin()
    version = get_cli_version(claude_bin)
    if not claude_bin:
        return False, 'Claude Code CLI не найден'
    if version and not cli_version_ok(version):
        return False, f'CLI {version} < {MIN_CLI_VERSION}'

    home = _stable_home()
    logged_in = _has_cli_login(home)

    text, inp, out = call_claude('Ответь одним словом: OK')
    if text.startswith('❌') or text.startswith('⚠️') or text.startswith('⏰'):
        return False, f'{text}\n(cli={version}, login={"yes" if logged_in else "NO"})'
    return True, {
        'usage': usage,
        'reply': text,
        'tokens': inp + out,
        'cli_version': version,
        'cli_path': claude_bin,
        'home': str(home),
        'login': logged_in,
    }
