import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import feedparser
import yaml
from jinja2 import Template

MAX_ITEMS = 200
ITEMS_PER_FEED = 25
TOP_STORIES = 20


def parse_feed_date(entry):
    published = entry.get("published", entry.get("updated", ""))

    try:
        date = parsedate_to_datetime(published)
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        return date.astimezone(timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def domain_from_url(url):
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""


with open("feeds.yml", "r") as f:
    feeds = yaml.safe_load(f)

items = []
feed_status = []
now = datetime.now(timezone.utc)

for feed in feeds:
    parsed = feedparser.parse(feed["url"])
    feed_title = parsed.feed.get("title", feed["name"])
    feed_domain = domain_from_url(feed["url"])
    favicon = f"https://www.google.com/s2/favicons?domain={feed_domain}&sz=32"

    status = {
        "name": feed["name"],
        "url": feed["url"],
        "category": feed.get("category", "Other"),
        "ok": not parsed.bozo and len(parsed.entries) > 0,
        "count": len(parsed.entries),
    }
    feed_status.append(status)

    for entry in parsed.entries[:ITEMS_PER_FEED]:
        date = parse_feed_date(entry)
        age_hours = (now - date).total_seconds() / 3600

        weight = feed.get("weight", 50)
        if feed.get("favorite", False):
            weight += 25

        score = weight - age_hours

        items.append({
            "title": entry.get("title", "Untitled"),
            "link": entry.get("link", "#"),
            "source": feed["name"],
            "category": feed.get("category", "Other"),
            "date": date,
            "score": score,
            "favicon": favicon,
            "favorite": feed.get("favorite", False),
        })

items.sort(key=lambda x: x["score"], reverse=True)
items = items[:MAX_ITEMS]

categories = {}
for item in items:
    categories.setdefault(item["category"], []).append(item)

top_items = items[:TOP_STORIES]
updated = now.strftime("%Y-%m-%d %H:%M UTC")

json_items = []
for item in items:
    json_items.append({
        "title": item["title"],
        "link": item["link"],
        "source": item["source"],
        "category": item["category"],
        "date": item["date"].isoformat(),
        "score": round(item["score"], 2),
        "favicon": item["favicon"],
        "favorite": item["favorite"],
    })

with open("feeds.json", "w") as f:
    json.dump(json_items, f, indent=2)

with open("feed-status.json", "w") as f:
    json.dump(feed_status, f, indent=2)

template = Template("""
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>feedz.jetgirl.art</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">

  <style>
    :root {
      --bg: #f6f3ea;
      --text: #111;
      --muted: #666;
      --line: #111;
      --link: #0000cc;
      --visited: #777;
      --card: #fffdf7;
    }

    body.dark {
      --bg: #111;
      --text: #eee;
      --muted: #aaa;
      --line: #eee;
      --link: #9db7ff;
      --visited: #777;
      --card: #1a1a1a;
    }

    body {
      font-family: Arial, Helvetica, sans-serif;
      background: var(--bg);
      color: var(--text);
      max-width: 1180px;
      margin: 24px auto;
      padding: 0 18px;
    }

    header {
      text-align: center;
      border-top: 6px solid var(--line);
      border-bottom: 6px solid var(--line);
      padding: 12px 0;
      margin-bottom: 16px;
    }

    h1 {
      font-family: Georgia, serif;
      font-size: clamp(42px, 8vw, 86px);
      margin: 0;
      letter-spacing: -4px;
      line-height: .9;
    }

    .sub {
      font-size: 13px;
      color: var(--muted);
      margin-top: 10px;
    }

    .controls {
      display: flex;
      gap: 8px;
      margin: 16px 0;
      flex-wrap: wrap;
      justify-content: center;
    }

    input, button {
      font: inherit;
      padding: 8px 10px;
      border: 1px solid var(--line);
      background: var(--card);
      color: var(--text);
    }

    input {
      min-width: 260px;
    }

    button {
      cursor: pointer;
      font-weight: bold;
    }

    .top {
      border: 3px solid var(--line);
      background: var(--card);
      padding: 12px;
      margin-bottom: 22px;
    }

    .top h2 {
      text-align: center;
      font-size: 22px;
      margin-top: 0;
    }

    .layout {
      display: grid;
      grid-template-columns: 1fr 280px;
      gap: 28px;
    }

    .grid {
      columns: 3 240px;
      column-gap: 28px;
    }

    section {
      break-inside: avoid;
      margin-bottom: 28px;
    }

    h2 {
      font-size: 17px;
      border-bottom: 2px solid var(--line);
      margin-bottom: 8px;
      text-transform: uppercase;
    }

    .item {
      margin: 0 0 10px;
      font-size: 15px;
      line-height: 1.25;
    }

    .item.read {
      opacity: .45;
    }

    .item.hidden {
      display: none;
    }

    a {
      color: var(--link);
      font-weight: bold;
      text-decoration: none;
    }

    a:visited {
      color: var(--visited);
    }

    .meta {
      font-size: 11px;
      color: var(--muted);
      margin-top: 2px;
    }

    .favicon {
      width: 14px;
      height: 14px;
      vertical-align: -2px;
      margin-right: 4px;
    }

    aside {
      font-size: 13px;
    }

    .box {
      border: 1px solid var(--line);
      background: var(--card);
      padding: 10px;
      margin-bottom: 16px;
    }

    .status-ok {
      color: green;
      font-weight: bold;
    }

    .status-bad {
      color: crimson;
      font-weight: bold;
    }

    footer {
      text-align: center;
      font-size: 12px;
      color: var(--muted);
      border-top: 1px solid var(--line);
      margin-top: 30px;
      padding-top: 12px;
    }

    @media (max-width: 850px) {
      .layout {
        display: block;
      }

      aside {
        margin-top: 30px;
      }
    }
  </style>
</head>

<body>
  <header>
    <h1>feedz</h1>
    <div class="sub">{{ total }} links · {{ feed_count }} feeds · updated {{ updated }}</div>
  </header>

  <div class="controls">
    <input id="search" placeholder="Search feedz...">
    <button id="darkMode">Dark Mode</button>
    <button id="markRead">Mark All Read</button>
    <button id="clearRead">Clear Read</button>
  </div>

  <div class="top">
    <h2>Top Stories</h2>
    {% for item in top_items %}
      <div class="item" data-link="{{ item.link }}" data-title="{{ item.title|lower }}" data-source="{{ item.source|lower }}" data-category="{{ item.category|lower }}">
        <a href="{{ item.link }}" target="_blank" rel="noopener noreferrer">
          <img class="favicon" src="{{ item.favicon }}" alt="">
          {{ item.title }}
        </a>
        <div class="meta">{{ item.source }} · {{ item.category }} · {{ item.date.strftime("%b %d, %H:%M UTC") }}</div>
      </div>
    {% endfor %}
  </div>

  <div class="layout">
    <main class="grid">
      {% for category, links in categories.items() %}
        <section>
          <h2>{{ category }}</h2>
          {% for item in links[:30] %}
            <div class="item" data-link="{{ item.link }}" data-title="{{ item.title|lower }}" data-source="{{ item.source|lower }}" data-category="{{ item.category|lower }}">
              <a href="{{ item.link }}" target="_blank" rel="noopener noreferrer">
                <img class="favicon" src="{{ item.favicon }}" alt="">
                {{ item.title }}
              </a>
              <div class="meta">
                {{ item.source }}
                {% if item.favorite %}★{% endif %}
                · {{ item.date.strftime("%b %d, %H:%M UTC") }}
              </div>
            </div>
          {% endfor %}
        </section>
      {% endfor %}
    </main>

    <aside>
      <div class="box">
        <h2>Feed Status</h2>
        {% for feed in feed_status %}
          <div>
            {% if feed.ok %}
              <span class="status-ok">✓</span>
            {% else %}
              <span class="status-bad">!</span>
            {% endif %}
            {{ feed.name }} — {{ feed.count }}
          </div>
        {% endfor %}
      </div>

      <div class="box">
        <h2>Random</h2>
        <button id="randomLink">Random Article</button>
      </div>
    </aside>
  </div>

  <footer>
    Built from RSS. JSON: <code>feeds.json</code>.
  </footer>

  <script>
    const readKey = "feedz_read_links";
    const darkKey = "feedz_dark_mode";

    function getReadLinks() {
      return JSON.parse(localStorage.getItem(readKey) || "[]");
    }

    function saveReadLinks(links) {
      localStorage.setItem(readKey, JSON.stringify([...new Set(links)]));
    }

    function applyReadState() {
      const readLinks = getReadLinks();
      document.querySelectorAll(".item").forEach(item => {
        if (readLinks.includes(item.dataset.link)) {
          item.classList.add("read");
        } else {
          item.classList.remove("read");
        }
      });
    }

    document.querySelectorAll(".item a").forEach(link => {
      link.addEventListener("click", () => {
        const readLinks = getReadLinks();
        readLinks.push(link.href);
        saveReadLinks(readLinks);
        applyReadState();
      });
    });

    document.getElementById("search").addEventListener("input", e => {
      const q = e.target.value.toLowerCase();

      document.querySelectorAll(".item").forEach(item => {
        const haystack = [
          item.dataset.title,
          item.dataset.source,
          item.dataset.category
        ].join(" ");

        item.classList.toggle("hidden", !haystack.includes(q));
      });
    });

    document.getElementById("markRead").addEventListener("click", () => {
      const links = [...document.querySelectorAll(".item")].map(item => item.dataset.link);
      saveReadLinks(links);
      applyReadState();
    });

    document.getElementById("clearRead").addEventListener("click", () => {
      localStorage.removeItem(readKey);
      applyReadState();
    });

    document.getElementById("darkMode").addEventListener("click", () => {
      document.body.classList.toggle("dark");
      localStorage.setItem(darkKey, document.body.classList.contains("dark") ? "1" : "0");
    });

    if (localStorage.getItem(darkKey) === "1") {
      document.body.classList.add("dark");
    }

    document.getElementById("randomLink").addEventListener("click", () => {
      const links = [...document.querySelectorAll(".item a")];
      const pick = links[Math.floor(Math.random() * links.length)];
      if (pick) window.open(pick.href, "_blank");
    });

    applyReadState();
  </script>
</body>
</html>
""")

html = template.render(
    categories=categories,
    top_items=top_items,
    total=len(items),
    feed_count=len(feeds),
    updated=updated,
    feed_status=feed_status,
)

with open("index.html", "w") as f:
    f.write(html)

print(f"Built index.html, feeds.json, and feed-status.json with {len(items)} items.")