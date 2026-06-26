import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import yaml
from jinja2 import Template

MAX_ITEMS = 150
ITEMS_PER_FEED = 20


def parse_feed_date(entry):
    published = entry.get("published", entry.get("updated", ""))

    try:
        date = parsedate_to_datetime(published)
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        return date.astimezone(timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


with open("feeds.yml", "r") as f:
    feeds = yaml.safe_load(f)

items = []

for feed in feeds:
    parsed = feedparser.parse(feed["url"])

    for entry in parsed.entries[:ITEMS_PER_FEED]:
        date = parse_feed_date(entry)

        age_hours = (datetime.now(timezone.utc) - date).total_seconds() / 3600
        score = feed.get("weight", 50) - age_hours

        items.append({
            "title": entry.get("title", "Untitled"),
            "link": entry.get("link", "#"),
            "source": feed["name"],
            "category": feed.get("category", "Other"),
            "date": date,
            "score": score,
        })

items.sort(key=lambda x: x["score"], reverse=True)
items = items[:MAX_ITEMS]

categories = {}
for item in items:
    categories.setdefault(item["category"], []).append(item)

updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

# Write feeds.json for future search/favorites/read-status features
json_items = []

for item in items:
    json_items.append({
        "title": item["title"],
        "link": item["link"],
        "source": item["source"],
        "category": item["category"],
        "date": item["date"].isoformat(),
        "score": round(item["score"], 2),
    })

with open("feeds.json", "w") as f:
    json.dump(json_items, f, indent=2)

template = Template("""
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>feeds.jetgirl.art</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">

  <style>
    body {
      font-family: Arial, Helvetica, sans-serif;
      background: #f8f8f8;
      color: #111;
      max-width: 1100px;
      margin: 30px auto;
      padding: 0 18px;
    }

    header {
      text-align: center;
      border-bottom: 5px solid #111;
      margin-bottom: 20px;
    }

    h1 {
      font-size: 46px;
      margin: 0;
      letter-spacing: -2px;
    }

    .sub {
      font-size: 13px;
      margin: 8px 0 14px;
      color: #555;
    }

    .grid {
      columns: 3 280px;
      column-gap: 32px;
    }

    section {
      break-inside: avoid;
      margin-bottom: 28px;
    }

    h2 {
      font-size: 18px;
      border-bottom: 2px solid #111;
      margin-bottom: 8px;
      text-transform: uppercase;
    }

    .item {
      margin: 0 0 10px;
      font-size: 15px;
      line-height: 1.25;
    }

    a {
      color: #0000cc;
      font-weight: bold;
      text-decoration: none;
    }

    a:visited {
      color: #777;
    }

    .meta {
      font-size: 11px;
      color: #777;
      margin-top: 2px;
    }

    footer {
      text-align: center;
      font-size: 12px;
      color: #777;
      border-top: 1px solid #ccc;
      margin-top: 30px;
      padding-top: 12px;
    }
  </style>
</head>

<body>
  <header>
    <h1>feeds.jetgirl.art</h1>
    <div class="sub">{{ total }} links · updated {{ updated }}</div>
  </header>

  <main class="grid">
    {% for category, links in categories.items() %}
      <section>
        <h2>{{ category }}</h2>
        {% for item in links[:25] %}
          <div class="item">
            <a href="{{ item.link }}" target="_blank" rel="noopener noreferrer">{{ item.title }}</a>
            <div class="meta">{{ item.source }} · {{ item.date.strftime("%b %d, %H:%M UTC") }}</div>
          </div>
        {% endfor %}
      </section>
    {% endfor %}
  </main>

  <footer>
    Personal feed page. Built automatically from RSS. JSON available at <code>feeds.json</code>.
  </footer>
</body>
</html>
""")

html = template.render(
    categories=categories,
    total=len(items),
    updated=updated,
)

with open("index.html", "w") as f:
    f.write(html)

print(f"Built index.html and feeds.json with {len(items)} items.")