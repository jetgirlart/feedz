import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import feedparser
import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape


BASE_DIR = Path(__file__).parent
FEEDS_FILE = BASE_DIR / "feeds.yml"
TEMPLATE_DIR = BASE_DIR / "templates"
OUTPUT_HTML = BASE_DIR / "index.html"
OUTPUT_FEEDS_JSON = BASE_DIR / "feeds.json"
OUTPUT_STATUS_JSON = BASE_DIR / "feed-status.json"

DEFAULT_CATEGORY = "Other"
DEFAULT_WEIGHT = 50
DEFAULT_MAX_ITEMS = 7
FAVORITE_BONUS = 25
TOP_STORIES_LIMIT = 20

# We only look at a modest number of entries from each RSS feed. This keeps a
# very busy feed from taking over the page while still giving scoring room to work.
FEED_LOOKAHEAD = 25


def read_feeds():
    """Read the feed list from feeds.yml."""
    with FEEDS_FILE.open("r", encoding="utf-8") as file:
        feeds = yaml.safe_load(file) or []

    if not isinstance(feeds, list):
        raise ValueError("feeds.yml must contain a list of feeds.")

    return feeds


def clean_feed_config(feed):
    """Fill in defaults for optional feed settings."""
    max_items = feed.get("max_items", DEFAULT_MAX_ITEMS)
    weight = feed.get("weight", DEFAULT_WEIGHT)

    try:
        max_items = int(max_items)
    except (TypeError, ValueError):
        max_items = DEFAULT_MAX_ITEMS

    if max_items < 1:
        max_items = DEFAULT_MAX_ITEMS

    try:
        weight = float(weight)
    except (TypeError, ValueError):
        weight = DEFAULT_WEIGHT

    return {
        "name": feed["name"],
        "url": feed["url"],
        "category": feed.get("category", DEFAULT_CATEGORY),
        "weight": weight,
        "favorite": bool(feed.get("favorite", False)),
        "max_items": max_items,
    }


def parse_feed_date(entry):
    """Return a timezone-aware published date for a feed entry."""
    published = entry.get("published") or entry.get("updated") or ""

    try:
        date = parsedate_to_datetime(published)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)

    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)

    return date.astimezone(timezone.utc)


def domain_from_url(url):
    """Extract a simple domain name from a URL."""
    try:
        return urlparse(url).netloc.removeprefix("www.")
    except Exception:
        return ""


def favicon_url(feed_url):
    """Use Google's small favicon helper for the feed's domain."""
    domain = domain_from_url(feed_url)
    return f"https://www.google.com/s2/favicons?domain={domain}&sz=32"


def youtube_video_id(link):
    """Extract a YouTube video ID from common YouTube URL formats."""
    parsed = urlparse(link)
    host = parsed.netloc.lower().removeprefix("www.")
    path_parts = [part for part in parsed.path.split("/") if part]

    if host == "youtu.be" and path_parts:
        return path_parts[0]

    if host in {"youtube.com", "m.youtube.com", "youtube-nocookie.com"}:
        query_video_id = parse_qs(parsed.query).get("v", [None])[0]
        if query_video_id:
            return query_video_id

        if len(path_parts) >= 2 and path_parts[0] in {"embed", "shorts", "live"}:
            return path_parts[1]

    return None


def youtube_thumbnail_url(category, link):
    """Return a YouTube thumbnail URL only for feeds in the YouTube category."""
    if category != "YouTube":
        return None

    video_id = youtube_video_id(link)
    if not video_id:
        return None

    return f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg"


def score_article(feed, published_at, now):
    """Score an article from its feed weight and age in hours."""
    age_hours = (now - published_at).total_seconds() / 3600
    age_hours = max(0, age_hours)

    weight = float(feed["weight"])
    if feed["favorite"]:
        weight += FAVORITE_BONUS

    return weight - age_hours


def build_article(feed, entry, now):
    """Turn one parsed RSS entry into the article shape used by the site."""
    published_at = parse_feed_date(entry)
    link = entry.get("link", "#")

    return {
        "title": entry.get("title", "Untitled"),
        "link": link,
        "source": feed["name"],
        "category": feed["category"],
        "date": published_at,
        "score": score_article(feed, published_at, now),
        "favicon": favicon_url(feed["url"]),
        "favorite": feed["favorite"],
        "thumbnail": youtube_thumbnail_url(feed["category"], link),
    }


def fetch_feed_articles(feed, now):
    """Fetch one RSS feed and return its visible articles plus status."""
    parsed = feedparser.parse(feed["url"])
    entries = parsed.entries or []

    status = {
        "name": feed["name"],
        "url": feed["url"],
        "category": feed["category"],
        "ok": not parsed.bozo and len(entries) > 0,
        "count": len(entries),
        "visible": min(feed["max_items"], len(entries)),
        "max_items": feed["max_items"],
        "favorite": feed["favorite"],
    }

    lookahead = max(feed["max_items"], FEED_LOOKAHEAD)
    articles = [build_article(feed, entry, now) for entry in entries[:lookahead]]
    articles.sort(key=lambda article: article["score"], reverse=True)

    return articles[: feed["max_items"]], status


def group_articles_by_category(articles):
    """Group articles by category for template rendering."""
    categories = {}

    for article in articles:
        categories.setdefault(article["category"], []).append(article)

    return categories


def article_to_json(article):
    """Convert datetime values into JSON-friendly strings."""
    return {
        "title": article["title"],
        "link": article["link"],
        "source": article["source"],
        "category": article["category"],
        "date": article["date"].isoformat(),
        "score": round(article["score"], 2),
        "favicon": article["favicon"],
        "favorite": article["favorite"],
        "thumbnail": article["thumbnail"],
    }


def write_json(path, data):
    """Write pretty JSON with stable UTF-8 output."""
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
        file.write("\n")


def render_site(articles, feed_status, feeds, now):
    """Render templates/index.html into index.html."""
    environment = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = environment.get_template("index.html")

    html = template.render(
        categories=group_articles_by_category(articles),
        top_items=articles[:TOP_STORIES_LIMIT],
        total=len(articles),
        feed_count=len(feeds),
        updated=now.strftime("%Y-%m-%d %H:%M UTC"),
        feed_status=feed_status,
    )

    OUTPUT_HTML.write_text(html, encoding="utf-8")


def main():
    feeds = [clean_feed_config(feed) for feed in read_feeds()]
    now = datetime.now(timezone.utc)

    articles = []
    feed_status = []

    for feed in feeds:
        feed_articles, status = fetch_feed_articles(feed, now)
        articles.extend(feed_articles)
        feed_status.append(status)

    articles.sort(key=lambda article: article["score"], reverse=True)

    write_json(OUTPUT_FEEDS_JSON, [article_to_json(article) for article in articles])
    write_json(OUTPUT_STATUS_JSON, feed_status)
    render_site(articles, feed_status, feeds, now)

    print(
        f"Built index.html, feeds.json, and feed-status.json "
        f"with {len(articles)} visible items from {len(feeds)} feeds."
    )


if __name__ == "__main__":
    main()
