.DEFAULT_GOAL := help

.PHONY: help install check api-check api-test api-migrate web-build e2e up down

help:
	@printf '%s\n' 'make install | check | api-check | api-test | api-migrate | web-build | e2e | up | down'

install:
	pnpm install --frozen-lockfile
	uv --directory backend sync --all-groups --frozen

check:
	pnpm run check
	pnpm run api:check

api-check:
	pnpm run api:check

api-test:
	pnpm run api:test

api-migrate:
	pnpm run api:migrate

web-build:
	pnpm run web:build

e2e:
	pnpm run test:e2e

up:
	docker compose --env-file deploy/docker/.env -f deploy/docker/compose.yml up --build

down:
	docker compose --env-file deploy/docker/.env -f deploy/docker/compose.yml down
