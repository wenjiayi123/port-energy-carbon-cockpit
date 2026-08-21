.PHONY: bootstrap validate backend frontend demo test build runtime-evidence verify-runtime-evidence security-audit release-check data-deps data-enhanced data-regulatory benchmark benchmark-enhanced landing-benchmark regulatory-benchmark tune-enhanced-short verify-benchmark verify-benchmark-enhanced verify-landing-benchmark verify-regulatory-benchmark docker-up docker-down

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

runtime-evidence:
	backend/.venv/bin/python scripts/export_runtime_evidence.py export

verify-runtime-evidence:
	backend/.venv/bin/python scripts/export_runtime_evidence.py verify

security-audit:
	backend/.venv/bin/python scripts/audit_python_dependencies.py
	cd frontend && bash ../scripts/run_frontend_command.sh audit --audit-level high

release-check:
	bash scripts/release_check.sh

benchmark:
	PYTHONPATH=backend backend/.venv/bin/python -m app.rl.benchmark run

data-deps:
	cd backend && .venv/bin/python -m pip install -e '.[data]'

data-enhanced: data-deps
	backend/.venv/bin/python scripts/fetch_port_la_vessel_activity_dataset.py

data-regulatory:
	backend/.venv/bin/python scripts/build_regulatory_resilience_dataset.py
	backend/.venv/bin/python scripts/build_regulatory_forward_challenge_dataset.py
	backend/.venv/bin/python scripts/build_regulatory_final_challenge_dataset.py

benchmark-enhanced:
	PYTHONPATH=backend backend/.venv/bin/python -m app.rl.benchmark run --dataset port_la_2020_2024_vessel_activity_hourly --output reports/offline_benchmark_vessel_activity_v1

landing-benchmark:
	PYTHONPATH=backend backend/.venv/bin/python -m app.rl.landing_benchmark run

regulatory-benchmark:
	PYTHONPATH=backend backend/.venv/bin/python -m app.rl.regulatory_benchmark run --steps 5000 --seeds 11,29,47 --workers 3
	PYTHONPATH=backend backend/.venv/bin/python -m app.rl.regulatory_shielded_benchmark run --steps 5000 --seeds 13,31,53 --workers 3
	PYTHONPATH=backend backend/.venv/bin/python -m app.rl.regulatory_projected_benchmark run --steps 5000 --seeds 17,37,59 --workers 3

tune-enhanced-short:
	PYTHONPATH=backend backend/.venv/bin/python -m app.rl.tuning --algorithm all --dataset port_la_2020_2024_vessel_activity_hourly --steps 10000 --final-seeds 11,29,47 --output reports/rl_tuning_vessel_activity_10k.json

verify-benchmark:
	PYTHONPATH=backend backend/.venv/bin/python -m app.rl.legacy_extension_verify verify reports/offline_benchmark_v3.json

verify-benchmark-enhanced:
	PYTHONPATH=backend backend/.venv/bin/python -m app.rl.legacy_extension_verify verify reports/offline_benchmark_vessel_activity_v1.json

verify-landing-benchmark:
	PYTHONPATH=backend backend/.venv/bin/python -m app.rl.legacy_extension_verify verify reports/port_landing_benchmark_v4.json

verify-regulatory-benchmark:
	PYTHONPATH=backend backend/.venv/bin/python -m app.rl.regulatory_benchmark verify reports/regulatory_resilience_v1.json
	PYTHONPATH=backend backend/.venv/bin/python -m app.rl.regulatory_shielded_benchmark verify reports/regulatory_resilience_v2.json
	PYTHONPATH=backend backend/.venv/bin/python -m app.rl.regulatory_projected_benchmark verify reports/regulatory_resilience_v3.json

docker-up:
	docker compose up --build

docker-down:
	docker compose down
