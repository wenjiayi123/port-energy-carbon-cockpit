.PHONY: bootstrap validate backend frontend demo test build docker-up docker-down

bootstrap:
	bash scripts/bootstrap.sh

validate:
	bash scripts/validate_structure.sh

backend:
	bash scripts/run_backend.sh

frontend:
	bash scripts/run_frontend.sh

demo:
	bash scripts/start_demo.sh

test:
	cd backend && .venv/bin/python -m pytest app/tests

build:
	cd frontend && bash ../scripts/run_frontend_command.sh build

docker-up:
	docker compose up --build

docker-down:
	docker compose down
