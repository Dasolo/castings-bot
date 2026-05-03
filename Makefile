HOST      = root@193.233.232.91
REMOTE    = /opt/castings-bot
SSH_KEY   = ~/.ssh/id_rsa
SSH       = ssh -i $(SSH_KEY) $(HOST)
SCP       = scp -i $(SSH_KEY)

.PHONY: up down logs build \
        deploy logs-remote ps-remote restart-remote \
        db-tunnel db-remote \
        auth backup-session \
        help

# ─── Local ────────────────────────────────────────────────────────────────────

up:
	docker compose up --build

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f

# ─── Deploy ───────────────────────────────────────────────────────────────────

deploy:
	$(SSH) "cd $(REMOTE) && git pull && docker compose up -d --build"

logs-remote:
	$(SSH) "cd $(REMOTE) && docker compose logs -f"

ps-remote:
	$(SSH) "cd $(REMOTE) && docker compose ps"

# Restart a single service without touching the rest
# Usage: make restart-remote svc=listener-tg
restart-remote:
	$(SSH) "cd $(REMOTE) && docker compose restart $(svc)"

# ─── Database ─────────────────────────────────────────────────────────────────

# Open SSH tunnel: Postgres on VPS becomes available at localhost:5433
# Use in DataGrip / DBeaver / psql: host=localhost port=5433
db-tunnel:
	ssh -i $(SSH_KEY) -L 5433:localhost:5432 $(HOST) -N

# Open psql directly on the server
db-remote:
	$(SSH) "cd $(REMOTE) && docker compose exec db psql -U $${POSTGRES_USER} $${POSTGRES_DB}"

# ─── Userbot session ──────────────────────────────────────────────────────────

# First-time authorisation: runs listener-tg interactively so you can
# enter your phone number and the Telegram confirmation code.
# The session file will be written to ./sessions/userbot.session on the host.
auth:
	docker compose run --rm -it listener-tg python -m src.auth

# Back up the session file before risky operations
backup-session:
	cp sessions/userbot.session sessions/userbot.session.bak
	@echo "Session backed up to sessions/userbot.session.bak"

# Авторизоваться локально, потом залить сессию на VPS
push-session:
	scp -i $(SSH_KEY) sessions/userbot.session $(HOST):$(REMOTE)/sessions/userbot.session
	@echo "Session uploaded to VPS"
# ─── Help ─────────────────────────────────────────────────────────────────────

help:
	@echo ""
	@echo "  Local"
	@echo "    make up                   build & start all services locally"
	@echo "    make down                 stop all services"
	@echo "    make logs                 tail logs locally"
	@echo ""
	@echo "  Deploy"
	@echo "    make deploy               git pull + docker compose up on VPS"
	@echo "    make logs-remote          tail logs on VPS"
	@echo "    make ps-remote            service status on VPS"
	@echo "    make restart-remote svc=X restart one service on VPS"
	@echo ""
	@echo "  Database"
	@echo "    make db-tunnel            SSH tunnel → Postgres on localhost:5433"
	@echo "    make db-remote            psql shell on VPS"
	@echo ""
	@echo "  Userbot"
	@echo "    make auth                 first-time Pyrogram authorisation"
	@echo "    make backup-session       back up sessions/userbot.session"
	@echo ""
