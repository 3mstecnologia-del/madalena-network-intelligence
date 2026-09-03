# All targets wrap Docker — no host Python/pip required.
.PHONY: build up down logs migrate test lint format config seed secret-scan

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

migrate:
	docker compose run --rm migrate

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
