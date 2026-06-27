import json
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import feedparser
import requests
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
DEFAULT_MAX_AGE_DAYS = 14
FAVORITE_BONUS = 25
TOP_STORIES_LIMIT = 20
DEFAULT_TOP_MAX = 1
REQUEST_TIMEOUT = 10
REDDIT_REQUEST_DELAY = 2
REDDIT_MAX_ATTEMPTS = 2
REDDIT_HEADERS = {
    "User-Agent": "feedz/1.0 (+https://feedz.jetgirl.art)",
}
last_reddit_request_at = 0

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
    max_age_days = feed.get("max_age_days", DEFAULT_MAX_AGE_DAYS)
    top_max = feed.get("top_max", DEFAULT_TOP_MAX)
    weight = feed.get("weight", DEFAULT_WEIGHT)

    try:
        max_items = int(max_items)
    except (TypeError, ValueError):
        max_items = DEFAULT_MAX_ITEMS

    if max_items < 1:
        max_items = DEFAULT_MAX_ITEMS

    try:
        max_age_days = int(max_age_days)
    except (TypeError, ValueError):
        max_age_days = DEFAULT_MAX_AGE_DAYS

    if max_age_days <= 0:
        max_age_days = DEFAULT_MAX_AGE_DAYS

    try:
        top_max = int(top_max)
    except (TypeError, ValueError):
        top_max = DEFAULT_TOP_MAX

    if top_max < 1:
        top_max = DEFAULT_TOP_MAX

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
        "max_age_days": max_age_days,
        "top_max": top_max,
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


def favicon_url(*urls):
    """Use Google's small favicon helper for the first usable URL domain."""
    for url in urls:
        domain = domain_from_url(url)
        if domain:
            return f"https://www.google.com/s2/favicons?domain={domain}&sz=32"

    return ""


def is_reddit_feed(url):
    """Return True when a feed URL points at Reddit."""
    return "reddit.com" in url.lower()


def reddit_subreddit_from_url(url):
    """Extract the subreddit name from a Reddit URL."""
    path_parts = [part for part in urlparse(url).path.split("/") if part]

    for index, part in enumerate(path_parts):
        if part.lower() == "r" and index + 1 < len(path_parts):
            return path_parts[index + 1].lower()

    return None


def reddit_combined_feed_url(feeds):
    """Build one RSS URL for all configured Reddit feeds."""
    subreddits = []

    for feed in feeds:
        subreddit = reddit_subreddit_from_url(feed["url"])
        if subreddit and subreddit not in subreddits:
            subreddits.append(subreddit)

    return f"https://www.reddit.com/r/{'+'.join(subreddits)}/.rss?limit=100"


def wait_for_reddit_request_slot():
    """Space out Reddit requests to avoid quick 429 rate-limit responses."""
    global last_reddit_request_at

    if last_reddit_request_at:
        elapsed = time.monotonic() - last_reddit_request_at
        if elapsed < REDDIT_REQUEST_DELAY:
            time.sleep(REDDIT_REQUEST_DELAY - elapsed)

    last_reddit_request_at = time.monotonic()


def parse_feed(feed):
    """Parse one RSS feed, using a custom User-Agent for Reddit."""
    if not is_reddit_feed(feed["url"]):
        return feedparser.parse(feed["url"]), None

    for attempt in range(REDDIT_MAX_ATTEMPTS):
        try:
            wait_for_reddit_request_slot()
            response = requests.get(
                feed["url"],
                headers=REDDIT_HEADERS,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            break
        except requests.RequestException as error:
            if attempt == REDDIT_MAX_ATTEMPTS - 1:
                return feedparser.parse(b""), f"Reddit fetch failed: {error}"

    parsed = feedparser.parse(response.content)
    if parsed.bozo:
        return parsed, f"Reddit parse warning: {parsed.bozo_exception}"

    return parsed, None


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


def article_age_hours(published_at, now):
    """Return the age of an article in hours."""
    age_hours = (now - published_at).total_seconds() / 3600
    return max(0, age_hours)


def score_article(feed, age_hours):
    """Score an article from its feed weight and age in hours."""
    weight = float(feed["weight"])
    if feed["favorite"]:
        weight += FAVORITE_BONUS

    return weight - age_hours


def build_article(feed, entry, published_at, age_hours):
    """Turn one parsed RSS entry into the article shape used by the site."""
    link = entry.get("link", "#")

    return {
        "title": entry.get("title", "Untitled"),
        "link": link,
        "source": feed["name"],
        "category": feed["category"],
        "date": published_at,
        "score": score_article(feed, age_hours),
        "favicon": favicon_url(link, feed["url"]),
        "favorite": feed["favorite"],
        "thumbnail": youtube_thumbnail_url(feed["category"], link),
        "top_max": feed["top_max"],
    }


def fetch_feed_articles(feed, now):
    """Fetch one RSS feed and return its visible articles plus status."""
    parsed, error = parse_feed(feed)
    entries = parsed.entries or []

    return build_feed_result(feed, entries, now, not parsed.bozo, error)


def build_feed_result(feed, entries, now, parsed_ok, error):
    """Build visible articles and status from parsed feed entries."""

    lookahead = max(feed["max_items"], FEED_LOOKAHEAD)
    articles = []

    for entry in entries[:lookahead]:
        published_at = parse_feed_date(entry)
        age_hours = article_age_hours(published_at, now)

        if age_hours > feed["max_age_days"] * 24:
            continue

        articles.append(build_article(feed, entry, published_at, age_hours))

    articles.sort(key=lambda article: article["score"], reverse=True)
    visible_articles = articles[: feed["max_items"]]

    status = {
        "name": feed["name"],
        "url": feed["url"],
        "category": feed["category"],
        "ok": parsed_ok and len(entries) > 0,
        "count": len(entries),
        "visible": len(visible_articles),
        "max_items": feed["max_items"],
        "max_age_days": feed["max_age_days"],
        "top_max": feed["top_max"],
        "favorite": feed["favorite"],
        "error": error,
    }

    return visible_articles, status


def fetch_reddit_feed_articles(feeds, now):
    """Fetch all Reddit feeds with one combined Reddit RSS request."""
    if not feeds:
        return {}

    combined_feed = {"url": reddit_combined_feed_url(feeds)}
    parsed, error = parse_feed(combined_feed)
    combined_entries = parsed.entries or []
    entries_by_subreddit = {}
    results = {}

    for entry in combined_entries:
        subreddit = reddit_subreddit_from_url(entry.get("link", ""))
        if subreddit:
            entries_by_subreddit.setdefault(subreddit, []).append(entry)

    for feed in feeds:
        subreddit = reddit_subreddit_from_url(feed["url"])
        feed_error = error

        if not subreddit:
            feed_error = "Could not determine subreddit from Reddit feed URL."

        entries = entries_by_subreddit.get(subreddit, []) if not feed_error else []
        results[feed["url"]] = build_feed_result(
            feed,
            entries,
            now,
            not parsed.bozo,
            feed_error,
        )

    return results


def group_articles_by_category(articles):
    """Group articles by category for template rendering."""
    categories = {}

    for article in articles:
        categories.setdefault(article["category"], []).append(article)

    return categories


def distribute_category_columns(categories):
    """Balance categories into four display columns by estimated height."""
    category_columns = [[], [], [], []]
    column_heights = [0, 0, 0, 0]

    for category, links in categories.items():
        estimated_height = 2 + len(links)
        shortest_column_index = column_heights.index(min(column_heights))

        category_columns[shortest_column_index].append({
            "name": category,
            "links": links,
        })
        column_heights[shortest_column_index] += estimated_height

    return category_columns


def select_top_items(articles):
    """Pick top stories from score-sorted articles, honoring each source limit."""
    source_counts = {}
    top_items = []

    for article in articles:
        source = article["source"]
        current_count = source_counts.get(source, 0)
        top_max = article.get("top_max", DEFAULT_TOP_MAX)

        if current_count >= top_max:
            continue

        top_items.append(article)
        source_counts[source] = current_count + 1

        if len(top_items) >= TOP_STORIES_LIMIT:
            break

    return top_items


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
    categories = group_articles_by_category(articles)
    category_columns = distribute_category_columns(categories)

    html = template.render(
        category_columns=category_columns,
        top_items=select_top_items(articles),
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
    reddit_feeds = [feed for feed in feeds if is_reddit_feed(feed["url"])]
    reddit_results = fetch_reddit_feed_articles(reddit_feeds, now)

    for feed in feeds:
        if is_reddit_feed(feed["url"]):
            feed_articles, status = reddit_results[feed["url"]]
        else:
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
