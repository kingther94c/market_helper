"""Signal and news data entry points."""

from .loader import download_feed_collection, download_news_feed

__all__ = ["download_news_feed", "download_feed_collection"]
