.PHONY: bootstrap validate backend frontend demo test build data-deps data-enhanced benchmark benchmark-enhanced landing-benchmark tune-enhanced-short verify-benchmark verify-benchmark-enhanced verify-landing-benchmark docker-up docker-down

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

data-deps:
	cd backend && .venv/bin/python -m pip install -e '.[data]'

data-enhanced: data-deps
	backend/.venv/bin/python scripts/fetch_port_la_vessel_activity_dataset.py

benchmark-enhanced:
	PYTHONPATH=backend backend/.venv/bin/python -m app.rl.benchmark run --dataset port_la_2020_2024_vessel_activity_hourly --output reports/offline_benchmark_vessel_activity_v1

landing-benchmark:
	PYTHONPATH=backend backend/.venv/bin/python -m app.rl.landing_benchmark run

tune-enhanced-short:
	PYTHONPATH=backend backend/.venv/bin/python -m app.rl.tuning --algorithm all --dataset port_la_2020_2024_vessel_activity_hourly --steps 10000 --final-seeds 11,29,47 --output reports/rl_tuning_vessel_activity_10k.json

verify-benchmark:
	PYTHONPATH=backend backend/.venv/bin/python -m app.rl.benchmark verify reports/offline_benchmark_v3.json

verify-benchmark-enhanced:
	PYTHONPATH=backend backend/.venv/bin/python -m app.rl.benchmark verify reports/offline_benchmark_vessel_activity_v1.json

verify-landing-benchmark:
	PYTHONPATH=backend backend/.venv/bin/python -m app.rl.landing_benchmark verify reports/port_landing_benchmark_v4.json

docker-up:
	docker compose up --build

docker-down:
	docker compose down
