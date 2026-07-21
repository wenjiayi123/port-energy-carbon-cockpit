# Backend

The FastAPI backend owns dataset validation, `PortEnergyDispatchEnv-v1`, four
Stable-Baselines3 learners, the MPC control baseline, persisted run evidence,
held-out evaluation, carbon accounting, and dashboard APIs.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --host 127.0.0.1 --port 8808
```

Run tests with `.venv/bin/python -m pytest app/tests`.
