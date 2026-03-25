"""Macro data download entry points."""

from .loader import download_fred_series, download_fred_series_batch

__all__ = ["download_fred_series", "download_fred_series_batch"]
