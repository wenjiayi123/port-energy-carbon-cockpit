.PHONY: bootstrap validate backend frontend demo test build benchmark verify-benchmark docker-up docker-down

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

benchmark:
	PYTHONPATH=backend backend/.venv/bin/python -m app.rl.benchmark run

verify-benchmark:
	PYTHONPATH=backend backend/.venv/bin/python -m app.rl.benchmark verify reports/offline_benchmark_v3.json

docker-up:
	docker compose up --build

docker-down:
	docker compose down
