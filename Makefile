# All targets wrap Docker — no host Python/pip required.
.PHONY: build up down logs migrate test lint format config seed secret-scan private-data-scan test-persist lab-collect lab-validate lab-diag

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

migrate:
	docker compose run --rm -v "$(CURDIR):/app" migrate

test:
	docker compose run --rm --no-deps api pytest -q

lint:
	docker compose run --rm --no-deps api ruff check .

format:
	docker compose run --rm --no-deps api ruff format .

config:
	docker compose config

seed:
	docker compose run --rm api python -m scripts.seed_lab

secret-scan:
	docker compose run --rm --no-deps api python -m scripts.secret_scan

private-data-scan:
	python3 -m scripts.private_data_scan

test-persist:
	docker compose up -d db
	docker compose run --rm migrate
	docker compose run --rm --no-deps api python -m scripts.test_postgres_persist write
	docker compose restart db
	docker compose exec -T db sh -c 'until pg_isready -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"; do sleep 1; done'
	docker compose run --rm --no-deps api python -m scripts.test_postgres_persist read

# LAB_SECRETS_FILE must point to a local dotenv outside this repo. Never commit it.
lab-collect:
	@test -n "$(LAB_SECRETS_FILE)" || (echo "LAB_SECRETS_FILE is required"; exit 1)
	docker compose up -d db api mcp
	docker compose run --rm -v "$(CURDIR):/app" migrate
	docker compose run --rm --no-deps \
		-v "$(CURDIR):/app" \
		-v "$(LAB_SECRETS_FILE):/run/secrets/lab.env:ro" \
		-e LAB_SECRETS_FILE=/run/secrets/lab.env \
		-e NI_SSH_MISSING_HOST_KEY=accept-new \
		-e SECRET_PROVIDER=env \
		api python -m scripts.lab_collect

lab-diag:
	@test -n "$(LAB_SECRETS_FILE)" || (echo "LAB_SECRETS_FILE is required"; exit 1)
	docker compose run --rm --no-deps \
		-v "$(CURDIR):/app" \
		-v "$(LAB_SECRETS_FILE):/run/secrets/lab.env:ro" \
		-e LAB_SECRETS_FILE=/run/secrets/lab.env \
		-e NI_SSH_MISSING_HOST_KEY=accept-new \
		-e SECRET_PROVIDER=env \
		api python -m scripts.lab_diag

lab-validate:
	docker compose run --rm --no-deps \
		-v "$(CURDIR):/app" \
		-e API_BASE_URL=http://api:8000 \
		-e MCP_BASE_URL=http://mcp:8081 \
		api python -m scripts.lab_validate
