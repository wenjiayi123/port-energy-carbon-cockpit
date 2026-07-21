# Frontend

React + TypeScript cockpit for dataset provenance, measured learner progress,
persisted training evidence, control/RL comparison, and held-out trajectory
replay. Fields absent from the active dataset are shown as unavailable.

```bash
bash scripts/run_frontend.sh
```

The Vite development server proxies `/api` to the FastAPI backend.
