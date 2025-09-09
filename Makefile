export COMPOSE_FILE := docker-compose.local.yml

## Make does not yet manage signals for subprocesses reliably, which can lead to unexpected behavior.
## Exercise caution before expanding its usage in production environments. 
## For more information, see https://github.com/casey/just/issues/2473 .

.PHONY: help build up down prune logs manage

# Default command to list all available commands
help:
	@echo "Available commands:"
	@echo "  help  - Show this help"
	@echo "  build - Build python image"
	@echo "  up    - Start up containers"
	@echo "  down  - Stop containers"
	@echo "  prune - Remove containers and their volumes"
	@echo "  logs  - View container logs"
	@echo "  manage- Executes manage.py command"

# Build python image
build:
	@echo "Building python image..."
	@docker compose build

# Start up containers
up:
	@echo "Starting up containers..."
	@docker compose up --remove-orphans -d=false

# Stop containers
down:
	@echo "Stopping containers..."
	@docker compose down

# Remove containers and their volumes
prune:
	@echo "Killing containers and removing volumes..."
	@docker compose down -v $(ARGS)

# View container logs
logs:
	@docker compose logs -f $(ARGS)

# Executes `manage.py` command
manage:
	@docker compose run --rm django python ./manage.py $(ARGS) 

# Make migrations
makemigrations:
	@docker compose run --rm django python ./manage.py makemigrations $(ARGS)

# Migrate
migrate:
	@docker compose run --rm django python ./manage.py migrate $(ARGS)

# Create superuser
createsuperuser:
	@docker compose run --rm django python ./manage.py createsuperuser 

# Seed the database with initial data
seed:
	@docker compose run --rm django python ./manage.py seed_interviews

# Run tests
testinterviews:
	@docker compose run --rm django python ./manage.py test interviews.tests -v 2


