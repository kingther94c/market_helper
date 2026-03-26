# market_helper

A scaffolded market research and workflow project organized for data, regime detection, signal generation, backtesting, reporting, and UI workflows.

## Environment

Create or verify the project environment:

```bash
./scripts/setup_python_env.sh
conda activate py313
```

## Project structure

This repository follows a domain-first layout:

- `configs/` for environment and runtime config
- `data/` for raw/interim/processed/external datasets
- `outputs/` for generated artifacts
- `notebooks/` for exploratory and research work
- `market_helper/` for package code by domain (`data_library`, `regimes`, `suggest`, `backtest`, `reporting`, `ui`, `workflows`, `cli`)
- `scripts/` for executable workflow entrypoints
- `tests/` for unit and e2e tests
- `docs/` for architecture and strategy notes

## Quick test

```bash
conda run -n py313 python -m unittest discover -s tests
```

## IBKR Web API Setup

Use [`configs/settings.example.json`](configs/settings.example.json) as the local config template for the read-only Web API path.

- Put your IBKR username in `provider.username`.
- Keep the password in an env var such as `IBKR_CP_PASSWORD`, referenced by `provider.password_env_var`.
- For most individual-account setups, start with username/password plus the local gateway session rather than looking for an API key first.

More detail is in [`docs/ibkr_web_api_auth.md`](docs/ibkr_web_api_auth.md).
