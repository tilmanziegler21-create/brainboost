FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# Claude Code CLI ставится в ~/.local/bin пользователя bot
ENV HOME=/home/bot
ENV PATH="/home/bot/.local/bin:${PATH}"
ENV ANTHROPIC_BASE_URL=https://claude-code-cli.vibecode-claude.online
ENV DISABLE_TELEMETRY=1
ENV DISABLE_ERROR_REPORTING=1
ENV DISABLE_AUTOUPDATER=1
ENV DISABLE_COST_WARNINGS=1
ENV DISABLE_NON_ESSENTIAL_MODEL_CALLS=1
ENV CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK=1
ENV CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY=1
ENV CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1
ENV CI=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates bash \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 -s /bin/bash bot

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Claude Code CLI >= 2.1.150 от пользователя bot (не root!)
USER bot
RUN curl -fsSL https://claude.ai/install.sh | bash \
    && claude --version

USER root
COPY . .
RUN mkdir -p /app/logs /home/bot/.claude \
    && chown -R bot:bot /app /home/bot

USER bot
WORKDIR /app

CMD ["python", "main.py"]
