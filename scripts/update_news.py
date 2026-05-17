from __future__ import annotations

import email.utils
import html
import json
import os
import re
import smtplib
import sys
import textwrap
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
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
DEFAULT_EMAIL_TO = "wang_zian@cscec.ae"


@dataclass(frozen=True)
class NewsItem:
    title: str
    link: str
    source: str
    published_at: str | None
    rank_score: int


@dataclass(frozen=True)
class InterpretedNewsItem:
    item: NewsItem
    category_en: str
    category_zh: str
    summary_en: str
    summary_zh: str
    why_it_matters_en: str
    why_it_matters_zh: str


CATEGORY_RULES = [
    (
        ("war", "drone", "missile", "ukraine", "russia", "israel", "iran", "gaza", "taiwan", "china", "military"),
        "Geopolitics and security",
        "地缘政治与安全",
        "This story points to a live security or diplomatic flashpoint.",
        "这条新闻指向正在变化的安全或外交热点。",
        "It may affect regional stability, sanctions, energy markets, defense planning, or diplomatic negotiations.",
        "它可能影响地区稳定、制裁、能源市场、防务安排或外交谈判。",
    ),
    (
        ("election", "vote", "senator", "president", "minister", "parliament", "campaign", "runoff", "trump"),
        "Politics and governance",
        "政治与治理",
        "This story is about a political decision, leadership contest, or public mandate.",
        "这条新闻涉及政治决策、领导权竞争或公众授权。",
        "Political shifts can change policy direction, regulation, alliances, and market expectations.",
        "政治变化可能改变政策方向、监管环境、联盟关系和市场预期。",
    ),
    (
        ("market", "stock", "inflation", "rate", "tariff", "trade", "oil", "bank", "fed", "economy"),
        "Economy and markets",
        "经济与市场",
        "This story has a direct connection to business conditions or financial expectations.",
        "这条新闻与商业环境或金融预期直接相关。",
        "It can influence investor sentiment, prices, supply chains, and household costs.",
        "它可能影响投资者情绪、价格、供应链和居民成本。",
    ),
    (
        ("ai", "tech", "cyber", "data", "software", "chip", "semiconductor", "app", "platform"),
        "Technology",
        "科技",
        "This story reflects a change in technology, digital infrastructure, or platform power.",
        "这条新闻反映了技术、数字基础设施或平台影响力的变化。",
        "Technology stories often reshape competition, privacy, security, and productivity.",
        "科技新闻常常会重塑竞争格局、隐私安全和生产效率。",
    ),
    (
        ("climate", "storm", "flood", "fire", "earthquake", "weather", "heat", "hurricane", "nuclear"),
        "Climate, environment, and safety",
        "气候、环境与安全",
        "This story concerns environmental risk, infrastructure safety, or public emergency response.",
        "这条新闻关系到环境风险、基础设施安全或公共应急响应。",
        "Such events can create human, economic, insurance, and policy consequences beyond the immediate location.",
        "这类事件可能在事发地之外带来人道、经济、保险和政策层面的连锁影响。",
    ),
    (
        ("dead", "killed", "injured", "crash", "strike", "shooting", "attack", "hospital", "disease"),
        "Public safety and society",
        "公共安全与社会",
        "This story centers on harm to people, emergency response, or social disruption.",
        "这条新闻聚焦人员伤亡、应急处置或社会秩序冲击。",
        "The key follow-up is whether authorities identify causes, prevent recurrence, and support affected communities.",
        "后续关键在于相关部门能否查明原因、防止复发，并支持受影响群体。",
    ),
]

DEFAULT_INTERPRETATION = (
    "Global affairs",
    "全球事务",
    "This story is gaining attention because it may signal a broader change or public concern.",
    "这条新闻受到关注，可能说明某个更大趋势或公共议题正在升温。",
    "Watch whether it develops into policy action, market reaction, diplomatic response, or wider social debate.",
    "需要继续观察它是否会演变为政策行动、市场反应、外交回应或更广泛的社会讨论。",
)


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


def interpret_item(item: NewsItem) -> InterpretedNewsItem:
    title = item.title.lower()
    for keywords, category_en, category_zh, summary_en, summary_zh, why_en, why_zh in CATEGORY_RULES:
        if any(keyword in title for keyword in keywords):
            return InterpretedNewsItem(
                item=item,
                category_en=category_en,
                category_zh=category_zh,
                summary_en=summary_en,
                summary_zh=summary_zh,
                why_it_matters_en=why_en,
                why_it_matters_zh=why_zh,
            )

    category_en, category_zh, summary_en, summary_zh, why_en, why_zh = DEFAULT_INTERPRETATION
    return InterpretedNewsItem(
        item=item,
        category_en=category_en,
        category_zh=category_zh,
        summary_en=summary_en,
        summary_zh=summary_zh,
        why_it_matters_en=why_en,
        why_it_matters_zh=why_zh,
    )


def interpret_news(items: list[NewsItem]) -> list[InterpretedNewsItem]:
    return [interpret_item(item) for item in items]


def write_latest(items: list[InterpretedNewsItem], generated_at: str) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    payload = {
        "generated_at": generated_at,
        "timezone": "UTC",
        "count": len(items),
        "items": [
            {
                "rank": index,
                "title": interpreted.item.title,
                "source": interpreted.item.source,
                "url": interpreted.item.link,
                "published_at": interpreted.item.published_at,
                "category": {
                    "en": interpreted.category_en,
                    "zh": interpreted.category_zh,
                },
                "interpretation": {
                    "summary_en": interpreted.summary_en,
                    "summary_zh": interpreted.summary_zh,
                    "why_it_matters_en": interpreted.why_it_matters_en,
                    "why_it_matters_zh": interpreted.why_it_matters_zh,
                },
            }
            for index, interpreted in enumerate(items, start=1)
        ],
    }
    LATEST_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def update_readme(items: list[InterpretedNewsItem], generated_at: str) -> None:
    header = textwrap.dedent(
        """\
        # Daily World Hot News / 每日全球热点新闻

        This repository automatically updates every morning with the top 10 global hot news stories and bilingual interpretation.

        本仓库每天早上自动抓取全球前十热点新闻，并生成中英双语解读。

        The workflow uses public RSS feeds, writes the latest result to `data/latest.json`, refreshes this README, and commits the change back to the repository when the news list changes.

        工作流会读取公开 RSS 新闻源，更新 `data/latest.json` 和本 README，并在内容变化时自动提交。

        ## Latest Top 10 / 最新前十热点
        """
    )
    lines = [header, f"\nGenerated at `{generated_at}` UTC.\n\n"]
    for index, interpreted in enumerate(items, start=1):
        item = interpreted.item
        published = f" Published: `{item.published_at}`." if item.published_at else ""
        lines.append(f"### {index}. [{item.title}]({item.link})\n\n")
        lines.append(f"- Source / 来源: {item.source}.{published}\n")
        lines.append(f"- Category / 分类: {interpreted.category_en} / {interpreted.category_zh}\n")
        lines.append(f"- EN Summary: {interpreted.summary_en}\n")
        lines.append(f"- 中文概要: {interpreted.summary_zh}\n")
        lines.append(f"- EN Why it matters: {interpreted.why_it_matters_en}\n")
        lines.append(f"- 中文解读: {interpreted.why_it_matters_zh}\n\n")

    footer = textwrap.dedent(
        """

        ## Schedule / 更新时间

        - Daily at 08:00 Asia/Dubai time.
        - GitHub Actions stores cron schedules in UTC, so the workflow runs at `04:00 UTC`.
        - You can also run it manually from the GitHub Actions tab.
        - 每天 Asia/Dubai 时间 08:00 自动运行，也可以在 GitHub Actions 页面手动运行。

        ## Files / 文件

        - `scripts/update_news.py` fetches and ranks news items.
        - `.github/workflows/daily-news.yml` runs the script and pushes updates.
        - `data/latest.json` stores the generated bilingual news and interpretation payload.

        ## Configuration / 配置

        Optional environment variables:

        - `NEWS_RSS_FEEDS`: pipe-separated RSS feed URLs.
        - `NEWS_LIMIT`: number of items to keep. Defaults to `10`.
        - `NEWS_EMAIL_TO`: recipient email address. Defaults to `wang_zian@cscec.ae`.
        - `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`: SMTP settings for email delivery.
        """
    )
    README.write_text("".join(lines) + footer, encoding="utf-8")


def build_email_text(items: list[InterpretedNewsItem], generated_at: str) -> str:
    lines = [
        "Daily World Hot News / 每日全球热点新闻",
        f"Generated at {generated_at} UTC",
        "",
    ]
    for index, interpreted in enumerate(items, start=1):
        item = interpreted.item
        lines.extend(
            [
                f"{index}. {item.title}",
                f"URL: {item.link}",
                f"Source / 来源: {item.source}",
                f"Published / 发布时间: {item.published_at or 'Unknown'}",
                f"Category / 分类: {interpreted.category_en} / {interpreted.category_zh}",
                f"EN Summary: {interpreted.summary_en}",
                f"中文概要: {interpreted.summary_zh}",
                f"EN Why it matters: {interpreted.why_it_matters_en}",
                f"中文解读: {interpreted.why_it_matters_zh}",
                "",
            ]
        )
    return "\n".join(lines)


def build_email_html(items: list[InterpretedNewsItem], generated_at: str) -> str:
    sections = []
    for index, interpreted in enumerate(items, start=1):
        item = interpreted.item
        sections.append(
            f"""
            <section style="margin: 0 0 24px; padding-bottom: 18px; border-bottom: 1px solid #e5e7eb;">
              <h2 style="font-size: 18px; margin: 0 0 8px;">{index}. <a href="{html.escape(item.link)}">{html.escape(item.title)}</a></h2>
              <p style="margin: 0 0 8px; color: #4b5563;">Source / 来源: {html.escape(item.source)} | Published / 发布时间: {html.escape(item.published_at or "Unknown")}</p>
              <p style="margin: 0 0 8px;"><strong>Category / 分类:</strong> {html.escape(interpreted.category_en)} / {html.escape(interpreted.category_zh)}</p>
              <p style="margin: 0 0 8px;"><strong>EN Summary:</strong> {html.escape(interpreted.summary_en)}</p>
              <p style="margin: 0 0 8px;"><strong>中文概要:</strong> {html.escape(interpreted.summary_zh)}</p>
              <p style="margin: 0 0 8px;"><strong>EN Why it matters:</strong> {html.escape(interpreted.why_it_matters_en)}</p>
              <p style="margin: 0;"><strong>中文解读:</strong> {html.escape(interpreted.why_it_matters_zh)}</p>
            </section>
            """
        )
    return f"""
    <!doctype html>
    <html>
      <body style="font-family: Arial, 'Microsoft YaHei', sans-serif; line-height: 1.55; color: #111827;">
        <h1 style="font-size: 24px; margin: 0 0 8px;">Daily World Hot News / 每日全球热点新闻</h1>
        <p style="margin: 0 0 24px; color: #4b5563;">Generated at {html.escape(generated_at)} UTC</p>
        {''.join(sections)}
      </body>
    </html>
    """


def send_email(items: list[InterpretedNewsItem], generated_at: str) -> None:
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_username = os.environ.get("SMTP_USERNAME")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    recipient = os.environ.get("NEWS_EMAIL_TO", DEFAULT_EMAIL_TO)
    sender = os.environ.get("SMTP_FROM", smtp_username or recipient)

    if not smtp_host or not smtp_username or not smtp_password:
        print("Email delivery skipped because SMTP_HOST, SMTP_USERNAME, or SMTP_PASSWORD is not configured.")
        return

    message = EmailMessage()
    message["Subject"] = f"Daily World Hot News / 每日全球热点新闻 - {generated_at[:10]}"
    message["From"] = sender
    message["To"] = recipient
    message.set_content(build_email_text(items, generated_at))
    message.add_alternative(build_email_html(items, generated_at), subtype="html")

    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
        server.starttls()
        server.login(smtp_username, smtp_password)
        server.send_message(message)
    print(f"Sent email digest to {recipient}.")


def main() -> None:
    limit = int(os.environ.get("NEWS_LIMIT", "10"))
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    items = interpret_news(collect_news(configured_feeds(), limit))
    write_latest(items, generated_at)
    update_readme(items, generated_at)
    send_email(items, generated_at)
    print(f"Updated {len(items)} interpreted bilingual news items.")


if __name__ == "__main__":
    main()
