# market_helper

Small Python utilities for downloading the inputs a market regime helper needs first:

- FRED economic and market series
- RSS/Atom news headlines
- Generic JSON, text, and CSV HTTP helpers

## Environment

Create or verify the project environment:

```bash
./scripts/setup_python_env.sh
conda activate py313
```

The setup script checks whether `py313` already exists. If it does not, it recreates the environment from [`environment.yml`](/Users/kelvin/git_projects/market_helper/environment.yml).

Update the existing environment after dependency or metadata changes:

```bash
conda env update -f environment.yml --prune
conda activate py313
```

Remove and rebuild it cleanly when needed:

```bash
conda env remove -n py313
conda env create -f environment.yml
```

## Quick start

```bash
conda activate py313
python -m unittest discover -s tests
```

```python
from market_helper.download import download_feed_collection, download_fred_series

series = download_fred_series(
    series_id="INDPRO",
    api_key="your_fred_api_key",
    observation_start="2024-01-01",
)

feeds = download_feed_collection(
    {
        "Fed": "https://www.federalreserve.gov/feeds/press_all.xml",
    },
    limit=5,
)
```

The project is pinned to Python 3.13 and uses a shared `py313` conda environment definition in [`environment.yml`](/Users/kelvin/git_projects/market_helper/environment.yml) so setup stays repeatable across machines.
