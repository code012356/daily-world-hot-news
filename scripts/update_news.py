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
from collections import Counter
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

STOPWORDS = {
    "about",
    "after",
    "again",
    "against",
    "amid",
    "among",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "but",
    "by",
    "can",
    "could",
    "for",
    "from",
    "has",
    "have",
    "how",
    "into",
    "its",
    "may",
    "more",
    "new",
    "not",
    "now",
    "off",
    "on",
    "or",
    "over",
    "says",
    "than",
    "that",
    "the",
    "their",
    "this",
    "to",
    "up",
    "was",
    "were",
    "what",
    "when",
    "who",
    "why",
    "will",
    "with",
    "world",
}

CATEGORY_RULES = [
    {
        "keywords": ("war", "drone", "missile", "ukraine", "russia", "israel", "iran", "gaza", "taiwan", "china", "military"),
        "category_en": "Geopolitics and security",
        "category_zh": "地缘政治与安全",
        "summary_en": "This is a security or diplomatic flashpoint with possible cross-border effects.",
        "summary_zh": "这是一条安全或外交热点新闻，可能产生跨境影响。",
        "impact_en": "The main risk is escalation: military moves, sanctions, energy disruption, or a sharper diplomatic response could follow if the situation widens.",
        "impact_zh": "主要风险在于局势升级：如果事件扩大，可能引发军事行动、制裁、能源扰动或更强烈的外交回应。",
        "watch_en": ("official responses", "civilian and infrastructure impact", "sanctions or diplomatic talks"),
        "watch_zh": ("官方回应", "平民与基础设施影响", "制裁或外交谈判"),
    },
    {
        "keywords": ("election", "vote", "senator", "president", "minister", "parliament", "campaign", "runoff", "trump", "primary"),
        "category_en": "Politics and governance",
        "category_zh": "政治与治理",
        "summary_en": "This story points to a shift in political power, public mandate, or policy direction.",
        "summary_zh": "这条新闻指向政治权力、公众授权或政策方向的变化。",
        "impact_en": "Political changes can alter regulation, alliances, fiscal choices, and market expectations, especially when they involve national leadership or legislative control.",
        "impact_zh": "政治变化可能改变监管、联盟关系、财政选择和市场预期，尤其是涉及国家领导层或立法控制权时。",
        "watch_en": ("polling or vote margins", "party reactions", "policy promises after the result"),
        "watch_zh": ("民调或票差", "党派反应", "结果后的政策承诺"),
    },
    {
        "keywords": ("market", "stock", "inflation", "rate", "tariff", "trade", "oil", "bank", "fed", "economy", "prices"),
        "category_en": "Economy and markets",
        "category_zh": "经济与市场",
        "summary_en": "This story is tied to business conditions, financial expectations, or the cost of goods and capital.",
        "summary_zh": "这条新闻与商业环境、金融预期或商品与资金成本相关。",
        "impact_en": "The practical effect may show up through investor sentiment, supply chains, company earnings, consumer prices, or central-bank expectations.",
        "impact_zh": "实际影响可能体现在投资者情绪、供应链、企业盈利、消费价格或央行预期上。",
        "watch_en": ("price movements", "company and government guidance", "second-round supply-chain effects"),
        "watch_zh": ("价格变化", "企业与政府指引", "供应链二次影响"),
    },
    {
        "keywords": ("ai", "tech", "cyber", "data", "software", "chip", "semiconductor", "app", "platform"),
        "category_en": "Technology",
        "category_zh": "科技",
        "summary_en": "This story reflects a change in technology, digital infrastructure, platform power, or data risk.",
        "summary_zh": "这条新闻反映了技术、数字基础设施、平台影响力或数据风险的变化。",
        "impact_en": "Technology stories can reshape competition, privacy, security, productivity, and regulation because they spread quickly across sectors.",
        "impact_zh": "科技新闻可能重塑竞争、隐私、安全、生产效率和监管，因为技术变化会快速传导到多个行业。",
        "watch_en": ("regulatory reaction", "enterprise adoption", "security or privacy consequences"),
        "watch_zh": ("监管反应", "企业采用情况", "安全或隐私后果"),
    },
    {
        "keywords": ("climate", "storm", "flood", "fire", "earthquake", "weather", "heat", "hurricane", "nuclear"),
        "category_en": "Climate, environment, and safety",
        "category_zh": "气候、环境与安全",
        "summary_en": "This story concerns environmental risk, infrastructure safety, or public emergency response.",
        "summary_zh": "这条新闻关系到环境风险、基础设施安全或公共应急响应。",
        "impact_en": "The impact can extend beyond the immediate location through insurance costs, infrastructure checks, public safety rules, or energy policy.",
        "impact_zh": "影响可能超出事发地本身，延伸到保险成本、基础设施检查、公共安全规则或能源政策。",
        "watch_en": ("damage assessment", "public safety advisories", "policy or infrastructure reviews"),
        "watch_zh": ("损害评估", "公共安全提示", "政策或基础设施复盘"),
    },
    {
        "keywords": ("dead", "killed", "injured", "crash", "strike", "shooting", "attack", "hospital", "disease"),
        "category_en": "Public safety and society",
        "category_zh": "公共安全与社会",
        "summary_en": "This story centers on harm to people, emergency response, or social disruption.",
        "summary_zh": "这条新闻聚焦人员伤亡、应急处置或社会秩序冲击。",
        "impact_en": "The key question is whether authorities can identify causes, prevent recurrence, and support affected communities.",
        "impact_zh": "关键问题在于相关部门能否查明原因、防止复发，并支持受影响群体。",
        "watch_en": ("official investigation", "confirmed casualty numbers", "prevention measures"),
        "watch_zh": ("官方调查", "确认伤亡数字", "预防措施"),
    },
]

DEFAULT_RULE = {
    "category_en": "Global affairs",
    "category_zh": "全球事务",
    "summary_en": "This story is drawing attention because it may signal a broader public concern or changing global trend.",
    "summary_zh": "这条新闻受到关注，可能说明某个公共议题或全球趋势正在变化。",
    "impact_en": "Its importance depends on whether it develops into policy action, market reaction, diplomatic response, or wider social debate.",
    "impact_zh": "它的重要性取决于后续是否演变为政策行动、市场反应、外交回应或更广泛的社会讨论。",
    "watch_en": ("follow-up reporting", "official statements", "regional or market reaction"),
    "watch_zh": ("后续报道", "官方声明", "地区或市场反应"),
}


@dataclass(frozen=True)
class NewsItem:
    title: str
    link: str
    source: str
    description: str
    published_at: str | None
    rank_score: int


@dataclass(frozen=True)
class InterpretedNewsItem:
    item: NewsItem
    category_en: str
    category_zh: str
    keywords: list[str]
    summary_en: str
    summary_zh: str
    detailed_en: str
    detailed_zh: str
    what_to_watch_en: list[str]
    what_to_watch_zh: list[str]


def clean_text(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def text_of(parent: ET.Element, name: str) -> str:
    node = parent.find(name)
    if node is None or node.text is None:
        return ""
    return clean_text(node.text)


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
        headers={"User-Agent": "daily-world-hot-news/1.0 (+https://github.com/)"},
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
        items.append(
            NewsItem(
                title=title,
                link=link,
                source=text_of(item, "source") or "Unknown source",
                description=text_of(item, "description"),
                published_at=parse_date(text_of(item, "pubDate")),
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


def extract_keywords(item: NewsItem, limit: int = 10) -> list[str]:
    text = f"{item.title} {item.description}"
    tokens = [
        token.lower()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}", text)
        if token.lower() not in STOPWORDS
    ]
    counts = Counter(tokens)

    title_tokens = {
        token.lower()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}", item.title)
        if token.lower() not in STOPWORDS
    }
    scored = sorted(
        counts,
        key=lambda token: (counts[token] + (2 if token in title_tokens else 0), len(token)),
        reverse=True,
    )

    keywords: list[str] = []
    for token in scored:
        clean = token.strip("-'")
        if clean and clean not in keywords:
            keywords.append(clean)
        if len(keywords) >= limit:
            break
    return keywords


def matched_rule(item: NewsItem, keywords: list[str]) -> dict[str, object]:
    text = f"{item.title} {item.description} {' '.join(keywords)}".lower()
    for rule in CATEGORY_RULES:
        if any(str(keyword) in text for keyword in rule["keywords"]):
            return rule
    return DEFAULT_RULE


def sentence_from_keywords(keywords: list[str]) -> str:
    if not keywords:
        return "the main facts still need follow-up reporting"
    if len(keywords) == 1:
        return keywords[0]
    return ", ".join(keywords[:-1]) + f", and {keywords[-1]}"


def interpret_item(item: NewsItem) -> InterpretedNewsItem:
    keywords = extract_keywords(item)
    rule = matched_rule(item, keywords)
    keyword_sentence = sentence_from_keywords(keywords[:5])
    description = item.description or "The RSS feed does not provide a longer excerpt, so the interpretation is based on the headline, source, and extracted keywords."

    detailed_en = (
        f"Key signals: {keyword_sentence}. The available excerpt says: {description} "
        f"Read together with the source and timing, the story appears important because {rule['impact_en']}"
    )
    detailed_zh = (
        f"关键词信号：{keyword_sentence}。RSS 摘要显示：{description} "
        f"结合来源与发布时间看，这条新闻值得关注，因为{rule['impact_zh']}"
    )

    return InterpretedNewsItem(
        item=item,
        category_en=str(rule["category_en"]),
        category_zh=str(rule["category_zh"]),
        keywords=keywords,
        summary_en=str(rule["summary_en"]),
        summary_zh=str(rule["summary_zh"]),
        detailed_en=detailed_en,
        detailed_zh=detailed_zh,
        what_to_watch_en=list(rule["watch_en"]),
        what_to_watch_zh=list(rule["watch_zh"]),
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
                "description": interpreted.item.description,
                "keywords": interpreted.keywords,
                "category": {
                    "en": interpreted.category_en,
                    "zh": interpreted.category_zh,
                },
                "interpretation": {
                    "summary_en": interpreted.summary_en,
                    "summary_zh": interpreted.summary_zh,
                    "detailed_en": interpreted.detailed_en,
                    "detailed_zh": interpreted.detailed_zh,
                    "what_to_watch_en": interpreted.what_to_watch_en,
                    "what_to_watch_zh": interpreted.what_to_watch_zh,
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

        This repository automatically updates every morning with the top 10 global hot news stories, extracted keywords, and bilingual interpretation.

        本仓库每天早上自动抓取全球前十热点新闻，提取关键词，并生成更详细的中英双语解读。

        The workflow uses public RSS feeds, writes the latest result to `data/latest.json`, refreshes this README, and commits the change back to the repository when the news list changes.

        工作流会读取公开 RSS 新闻源，更新 `data/latest.json` 和本 README，并在内容变化时自动提交。

        ## Latest Top 10 / 最新前十热点
        """
    )
    lines = [header, f"\nGenerated at `{generated_at}` UTC.\n\n"]
    for index, interpreted in enumerate(items, start=1):
        item = interpreted.item
        published = f" Published: `{item.published_at}`." if item.published_at else ""
        keyword_text = ", ".join(interpreted.keywords) if interpreted.keywords else "N/A"
        watch_en = "; ".join(interpreted.what_to_watch_en)
        watch_zh = "；".join(interpreted.what_to_watch_zh)

        lines.append(f"### {index}. [{item.title}]({item.link})\n\n")
        lines.append(f"- Source / 来源: {item.source}.{published}\n")
        lines.append(f"- Keywords / 关键词: {keyword_text}\n")
        lines.append(f"- Category / 分类: {interpreted.category_en} / {interpreted.category_zh}\n")
        lines.append(f"- RSS Excerpt / RSS 摘要: {item.description or 'N/A'}\n")
        lines.append(f"- EN Summary: {interpreted.summary_en}\n")
        lines.append(f"- 中文概要: {interpreted.summary_zh}\n")
        lines.append(f"- EN Detailed Reading: {interpreted.detailed_en}\n")
        lines.append(f"- 中文详细解读: {interpreted.detailed_zh}\n")
        lines.append(f"- EN What to watch: {watch_en}\n")
        lines.append(f"- 后续关注: {watch_zh}\n\n")

    footer = textwrap.dedent(
        """

        ## Schedule / 更新时间

        - Daily at 08:00 Asia/Dubai time.
        - GitHub Actions stores cron schedules in UTC, so the workflow runs at `04:00 UTC`.
        - You can also run it manually from the GitHub Actions tab.
        - 每天 Asia/Dubai 时间 08:00 自动运行，也可以在 GitHub Actions 页面手动运行。

        ## Files / 文件

        - `scripts/update_news.py` fetches news, extracts keywords, ranks items, and generates bilingual interpretation.
        - `.github/workflows/daily-news.yml` runs the script and pushes updates.
        - `data/latest.json` stores the generated bilingual news, keywords, and interpretation payload.

        ## Configuration / 配置

        Optional environment variables:

        - `NEWS_RSS_FEEDS`: pipe-separated RSS feed URLs.
        - `NEWS_LIMIT`: number of items to keep. Defaults to `10`.
        """
    )
    README.write_text("".join(lines) + footer, encoding="utf-8")


def main() -> None:
    limit = int(os.environ.get("NEWS_LIMIT", "10"))
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    items = interpret_news(collect_news(configured_feeds(), limit))
    write_latest(items, generated_at)
    update_readme(items, generated_at)
    print(f"Updated {len(items)} detailed bilingual news items with keywords.")


if __name__ == "__main__":
    main()
