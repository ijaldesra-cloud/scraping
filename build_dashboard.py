"""Bangun data agregat untuk dashboard visualisasi (web/data.js).

Membaca data/posts.jsonl + data/comments.jsonl + data/media.csv, lalu menulis
web/data.js berisi `window.DASH_DATA = {...}` supaya index.html bisa dibuka
langsung dari file:// tanpa server.

Pemakaian:
    python build_dashboard.py
"""

from __future__ import annotations

import csv
import json
import os
from collections import Counter, defaultdict
from datetime import datetime
from statistics import mean, median

import config
from analyze import load_jsonl, norm, themes_of
from sentiment import score as sentiment_score

OUT_DIR = "web"
HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]

LIKE_BUCKETS = [(0, 0, "0"), (1, 50, "1–50"), (51, 100, "51–100"),
                (101, 250, "101–250"), (251, 500, "251–500"),
                (501, 1000, "501–1.000"), (1001, 10**9, ">1.000")]


def week_key(iso: str) -> str:
    y, w, _ = datetime.fromisoformat(iso).isocalendar()
    return f"{y}-W{w:02d}"


def bucket_of(likes: int) -> str:
    for lo, hi, label in LIKE_BUCKETS:
        if lo <= likes <= hi:
            return label
    return ">1.000"


def main() -> int:
    posts = [p for p in load_jsonl(config.POSTS_FILE)
             if p["date_utc"][:10] >= config.ANCHOR_DATE]
    comments = [c for c in load_jsonl(config.COMMENTS_FILE)
                if c["post_date"][:10] >= config.ANCHOR_DATE]
    posts.sort(key=lambda p: p["date_utc"])

    if not posts:
        raise SystemExit("Belum ada data. Jalankan collect.py dulu.")

    media_count = Counter()
    media_types = Counter()
    if os.path.exists(config.MEDIA_FILE):
        with open(config.MEDIA_FILE, encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                media_count[row["shortcode"]] += 1
                media_types[row["media_type"] or "lainnya"] += 1

    # ---- komentar: sentimen + tema ----
    per_post = defaultdict(list)
    sent = Counter()
    themes = Counter()
    for c in comments:
        label, _ = sentiment_score(c["text"])
        sent[label] += 1
        for t in themes_of(c["text"]):
            themes[t] += 1
        per_post[c["post_shortcode"]].append(c)

    # ---- agregat waktu ----
    weekly = defaultdict(lambda: {"posts": 0, "likes": 0, "comments": 0})
    monthly = defaultdict(lambda: {"posts": 0, "likes": 0, "comments": 0})
    daily = defaultdict(lambda: {"posts": 0, "likes": 0, "comments": 0})
    dow = defaultdict(lambda: {"posts": 0, "likes": 0, "comments": 0})
    hour = Counter()

    for p in posts:
        likes = max(p["likes"], 0)
        for store, key in ((weekly, week_key(p["date_utc"])),
                           (monthly, p["date_utc"][:7]),
                           (daily, p["date_utc"][:10])):
            store[key]["posts"] += 1
            store[key]["likes"] += likes
            store[key]["comments"] += p["comment_count"]
        d = datetime.fromisoformat(p["date_utc"])
        dow[HARI[d.weekday()]]["posts"] += 1
        dow[HARI[d.weekday()]]["likes"] += likes
        dow[HARI[d.weekday()]]["comments"] += p["comment_count"]
        hour[d.hour] += 1

    total_likes = sum(max(p["likes"], 0) for p in posts)
    total_comments = sum(p["comment_count"] for p in posts)
    commenters = {c["author"] for c in comments}
    commenters_counts = Counter(c["author"] for c in comments)

    # ---- histogram like ----
    hist = Counter(bucket_of(max(p["likes"], 0)) for p in posts)
    histogram = [{"label": label, "count": hist.get(label, 0)}
                 for _, _, label in LIKE_BUCKETS]

    # ---- frasa ----
    from analyze import top_phrases
    phrases = [{"phrase": ph, "count": n} for ph, n in top_phrases(comments, 12)]

    # ---- tabel ----
    top_posts = [{
        "date": p["date_utc"][:10],
        "url": p["url"],
        "likes": max(p["likes"], 0),
        "comments": p["comment_count"],
        "caption": norm(p["caption"])[:110],
        "themes": themes_of(p["caption"])[:2],
    } for p in sorted(posts, key=lambda x: -x["comment_count"])[:12]]

    top_comments = [{
        "likes": c["likes"],
        "author": c["author"],
        "text": norm(c["text"])[:180],
        "url": c["post_url"],
        "date": c["created_at"][:10],
        "sentiment": sentiment_score(c["text"])[0],
    } for c in sorted(comments, key=lambda x: -x["likes"])[:30]]

    data = {
        "meta": {
            "akun": config.USERNAME,
            "dari": config.ANCHOR_DATE,
            "sampai": posts[-1]["date_utc"][:10],
            "posts": len(posts),
            "likes": total_likes,
            "komentar_meta": total_comments,
            "komentar_ditarik": len(comments),
            "komentator": len(commenters),
            "media": sum(media_count.values()),
            "avg_likes": round(mean(max(p["likes"], 0) for p in posts), 1),
            "median_likes": round(median(max(p["likes"], 0) for p in posts), 1),
            "avg_comments": round(total_comments / len(posts), 2),
            "post_berkomentar": sum(1 for p in posts if p["comment_count"] > 0),
        },
        "weekly": [{"week": k, **v} for k, v in sorted(weekly.items())],
        "monthly": [{"month": k, **v} for k, v in sorted(monthly.items())],
        "daily": [{"date": k, **v} for k, v in sorted(daily.items())],
        "dow": [{"day": d, "posts": dow[d]["posts"],
                 "avg_likes": round(dow[d]["likes"] / dow[d]["posts"], 1) if dow[d]["posts"] else 0,
                 "avg_comments": round(dow[d]["comments"] / dow[d]["posts"], 2) if dow[d]["posts"] else 0}
                for d in HARI],
        "hour": [{"hour": h, "count": hour.get(h, 0)} for h in range(24)],
        "sentiment": [{"label": k, "count": v} for k, v in sent.most_common()],
        "themes": [{"name": k, "count": v} for k, v in themes.most_common(10)],
        "phrases": phrases,
        "histogram": histogram,
        "scatter": [{"likes": max(p["likes"], 0), "comments": p["comment_count"],
                     "url": p["url"], "date": p["date_utc"][:10]} for p in posts],
        "types": [{"type": k, "count": v} for k, v in
                  Counter("Video" if p["is_video"] else "Foto" for p in posts).most_common()],
        "top_posts": top_posts,
        "top_comments": top_comments,
        # --- data pendukung panel detail KPI ---
        "all_posts": [{
            "d": p["date_utc"][:10],
            "u": p["url"],
            "l": max(p["likes"], 0),
            "c": p["comment_count"],
            "m": media_count.get(p["shortcode"], 0),
        } for p in sorted(posts, key=lambda x: x["date_utc"], reverse=True)],
        "top_commenters": [{"author": a, "count": n}
                           for a, n in commenters_counts.most_common(20)],
        "media_types": [{"type": k, "count": v} for k, v in media_types.most_common()],
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(f"{OUT_DIR}/data.js", "w", encoding="utf-8") as fh:
        fh.write("window.DASH_DATA = ")
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
        fh.write(";\n")

    size = os.path.getsize(f"{OUT_DIR}/data.js") / 1024
    print(f"post {len(posts)} | komentar {len(comments)} | {OUT_DIR}/data.js {size:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
