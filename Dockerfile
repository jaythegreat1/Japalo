# Railway (or any Docker host) image for the Japalo Highrise bot.
#
# Runs the bot as ONE process, without main.py's keep-alive web server and
# restart supervisor: Railway restarts the container itself (railway.json),
# and a single small process (~45-60 MB) is what fits Railway's free plan.
# main.py is unchanged and still what Replit runs.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    LOG_LEVEL=INFO

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY highrise_bot ./highrise_bot
COPY config ./config
RUN mkdir -p data

CMD ["sh", "-c", "if [ -z \"$HIGHRISE_ROOM_ID\" ] || [ -z \"$HIGHRISE_BOT_TOKEN\" ]; then echo 'Set HIGHRISE_ROOM_ID and HIGHRISE_BOT_TOKEN in the Railway service variables.' >&2; exit 1; fi; exec python -m highrise highrise_bot.bot:HighriseRoomBot \"$HIGHRISE_ROOM_ID\" \"$HIGHRISE_BOT_TOKEN\""]
