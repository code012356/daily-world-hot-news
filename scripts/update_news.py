from __future__ import annotations

import email.utils
import html
import json
import os
import re
import sys
import textwrap
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
LATEST_JSON = DATA_DIR / "latest.json"
README = ROOT / "README.md"

DEFAULT_FEEDS = [
    "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en",
]


@dataclass(frozen=True)
class NewsItem:
    title: str
    link: str
    source: str
    published_at: str | None
    rank_score: int


def text_of(parent: ET.Element, name: str) -> str:
    node = parent.find(name)
    if node is None or node.text is None:
        return ""
    return clean_text(node.text)


def clean_text(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def normalize_title(title: str) -> str:
    title = title.lower()
    title = re.sub(r"\s+-\s+[^-]+$", "", title)
    title = re.sub(r"[^a-z0-9]+", " ", title)
    return title.strip()


def parse_date(value: str) -> str | None:
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def fetch_feed(url: str) -> list[NewsItem]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "daily-world-hot-news/1.0 (+https://github.com/)",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read()

    root = ET.fromstring(body)
    channel = root.find("channel")
    if channel is None:
        return []

    items: list[NewsItem] = []
    for position, item in enumerate(channel.findall("item")):
        title = text_of(item, "title")
        link = text_of(item, "link")
        if not title or not link:
            continue
        source = text_of(item, "source") or "Unknown source"
        published_at = parse_date(text_of(item, "pubDate"))
        items.append(
            NewsItem(
                title=title,
                link=link,
                source=source,
                published_at=published_at,
                rank_score=max(0, 100 - position),
            )
        )
    return items


def configured_feeds() -> list[str]:
    raw = os.environ.get("NEWS_RSS_FEEDS", "")
    feeds = [feed.strip() for feed in raw.split("|") if feed.strip()]
    return feeds or DEFAULT_FEEDS


def collect_news(feeds: Iterable[str], limit: int) -> list[NewsItem]:
    by_key: dict[str, NewsItem] = {}
    failures: list[str] = []

    for feed in feeds:
        try:
            items = fetch_feed(feed)
        except Exception as exc:  # noqa: BLE001 - continue with the next public feed.
            failures.append(f"{feed}: {exc}")
            continue

        for item in items:
            key = normalize_title(item.title)
            if not key:
                continue
            existing = by_key.get(key)
            if existing is None or item.rank_score > existing.rank_score:
                by_key[key] = item

    ranked = sorted(
        by_key.values(),
        key=lambda item: (item.rank_score, item.published_at or ""),
        reverse=True,
    )

    if not ranked:
        for failure in failures:
            print(f"Feed failed: {failure}", file=sys.stderr)
        raise RuntimeError("No news items were fetched from the configured feeds.")

    return ranked[:limit]


def write_latest(items: list[NewsItem], generated_at: str) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    payload = {
        "generated_at": generated_at,
        "timezone": "UTC",
        "count": len(items),
        "items": [
            {
                "rank": index,
                "title": item.title,
                "source": item.source,
                "url": item.link,
                "published_at": item.published_at,
            }
            for index, item in enumerate(items, start=1)
        ],
    }
    LATEST_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def update_readme(items: list[NewsItem], generated_at: str) -> None:
    header = textwrap.dedent(
        """\
        # Daily World Hot News

        This repository automatically updates every morning with the top 10 global hot news stories.

        The workflow uses public RSS feeds, writes the latest result to `data/latest.json`, refreshes this README, and commits the change back to the repository when the news list changes.

        ## Latest Top 10
        """
    )
    lines = [header, f"\nGenerated at `{generated_at}` UTC.\n\n"]
    for index, item in enumerate(items, start=1):
        published = f" Published: `{item.published_at}`." if item.published_at else ""
        lines.append(f"{index}. [{item.title}]({item.link}) - {item.source}.{published}\n")

    footer = textwrap.dedent(
        """

        ## Schedule

        - Daily at 08:00 Asia/Dubai time.
        - GitHub Actions stores cron schedules in UTC, so the workflow runs at `04:00 UTC`.
        - You can also run it manually from the GitHub Actions tab.

        ## Files

        - `scripts/update_news.py` fetches and ranks news items.
        - `.github/workflows/daily-news.yml` runs the script and pushes updates.
        - `data/latest.json` stores the generated news payload.

        ## Configuration

        Optional environment variables:

        - `NEWS_RSS_FEEDS`: pipe-separated RSS feed URLs.
        - `NEWS_LIMIT`: number of items to keep. Defaults to `10`.
        """
    )
    README.write_text("".join(lines) + footer, encoding="utf-8")


def main() -> None:
    limit = int(os.environ.get("NEWS_LIMIT", "10"))
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    items = collect_news(configured_feeds(), limit)
    write_latest(items, generated_at)
    update_readme(items, generated_at)
    print(f"Updated {len(items)} news items.")


if __name__ == "__main__":
    main()
