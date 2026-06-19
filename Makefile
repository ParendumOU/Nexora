.PHONY: dev up down build logs ps clean env

# Copy .env.example if no .env exists
env:
	@if not exist .env (copy .env.example .env && echo "Created .env from .env.example") else (echo ".env already exists")

# Development mode (hot-reload)
dev: env
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build

# Production mode
up: env
	docker compose up --build -d

# Stop all services
down:
	docker compose down

# Stop and remove volumes (DESTRUCTIVE)
clean:
	docker compose down -v --remove-orphans

# Build images without starting
build:
	docker compose build

# View logs
logs:
	docker compose logs -f

# Show running containers
ps:
	docker compose ps
