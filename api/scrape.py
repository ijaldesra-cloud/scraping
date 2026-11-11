"""Endpoint serverless: ambil satu post Instagram publik + komentarnya → CSV.

Dipakai dashboard `web/` lewat form "Ambil CSV dari link post".
Berjalan sebagai Vercel Python function (`/api/scrape`) atau server lokal:

    python api/scrape.py          # http://127.0.0.1:8000/api/scrape

Body request:  {"url": "https://www.instagram.com/p/SHORTCODE/"}
Balasan:       JSON {ok, shortcode, ..., csv: {post, comments}}

Env var opsional (sangat disarankan di Vercel):
    IG_USERNAME    akun Instagram yang dipakai
    IG_SESSIONID   nilai cookie `sessionid` akun tersebut
Tanpa sesi, Instagram membatasi respons dan sering meminta login.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from sentiment import score as sentiment_score  # noqa: E402

SHORTCODE_RE = re.compile(r"instagram\.com/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)")
BARE_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{5,20}$")
MAX_COMMENTS = 250
MAX_REPLIES_PER_COMMENT = 5
RATE_LIMIT_SECONDS = 10

# Jeda per IP supaya satu instance tidak dipakai berlebihan.
_last_call: dict[str, float] = {}

POST_HEADER = [
    "tanggal", "url", "shortcode", "tipe", "likes", "jumlah_komentar",
    "komentar_diambil", "sentimen_positif", "sentimen_negatif",
    "jumlah_media", "caption",
]

COMMENT_HEADER = [
    "tanggal_post", "post_url", "shortcode", "penulis", "komentar",
    "tanggal_komentar", "likes_komentar", "balasan_dari", "sentimen", "skor",
]


class ScrapeError(Exception):
    """Kesalahan yang aman ditampilkan ke pengguna."""


class BadRequest(ScrapeError):
    """Input pengguna tidak valid (HTTP 400)."""


def parse_shortcode(raw: str) -> str:
    """Ambil shortcode dari URL post/reel/tv Instagram atau input shortcode polos."""
    value = (raw or "").strip()
    if not value:
        raise BadRequest("Link post masih kosong.")

    match = SHORTCODE_RE.search(value)
    if match:
        return match.group(1)

    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if host and "instagram.com" not in host:
        raise BadRequest("Itu bukan link Instagram. Contoh: https://www.instagram.com/p/xxxxx/")

    if BARE_CODE_RE.match(value):
        return value

    raise BadRequest(
        "Link tidak dikenali. Tempel link post/reel, misalnya "
        "https://www.instagram.com/p/xxxxx/"
    )


def _loader():
    """Instaloader tanpa unduhan file, memakai sesi dari env bila tersedia."""
    import instaloader

    loader = instaloader.Instaloader(
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        quiet=True,
    )

    sessionid = os.environ.get("IG_SESSIONID", "").strip()
    if sessionid:
        data = {"sessionid": sessionid}
        csrf = os.environ.get("IG_CSRFTOKEN", "").strip()
        if csrf:
            data["csrftoken"] = csrf
        loader.load_session(os.environ.get("IG_USERNAME", "").strip() or "session", data)

    return loader


def _media_urls(post) -> list[str]:
    urls: list[str] = []
    try:
        if post.typename == "GraphSidecar":
            for node in post.get_sidecar_nodes():
                urls.append(node.video_url if node.is_video else node.display_url)
        else:
            urls.append(post.video_url if post.is_video else post.url)
    except Exception:  # media tidak boleh menggagalkan seluruh permintaan
        pass
    return [u for u in urls if u]


def _collect_comments(post) -> list[dict]:
    rows: list[dict] = []
    try:
        for comment in post.get_comments():
            rows.append(_comment_row(comment, parent=None))
            replies = 0
            try:
                for answer in comment.answers:
                    if replies >= MAX_REPLIES_PER_COMMENT:
                        break
                    rows.append(_comment_row(answer, parent=comment.id))
                    replies += 1
            except Exception:
                pass
            if len(rows) >= MAX_COMMENTS:
                break
    except Exception:
        pass
    return rows[:MAX_COMMENTS]


def _comment_row(comment, parent) -> dict:
    label, value = sentiment_score(comment.text or "")
    return {
        "author": comment.owner.username if comment.owner else "",
        "text": (comment.text or "").replace("\r", " ").replace("\n", " "),
        "likes": int(comment.likes or 0),
        "created_at": comment.created_at,
        "parent_id": parent,
        "sentiment": label,
        "score": value,
    }


def build_post_csv(meta: dict, media: list[str], sentiment: Counter) -> str:
    """Satu baris CSV berisi ringkasan post."""
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(POST_HEADER)
    writer.writerow([
        meta["date"], meta["url"], meta["shortcode"], meta["type"],
        meta["likes"], meta["comment_count"], meta["comments_fetched"],
        sentiment.get("positif", 0) + sentiment.get("sangat positif", 0),
        sentiment.get("negatif", 0) + sentiment.get("sangat negatif", 0),
        len(media), " ".join((meta["caption"] or "").split()),
    ])
    return buf.getvalue()


def build_comments_csv(meta: dict, comments: list[dict]) -> str:
    """Satu baris per komentar/balasan, sudah lengkap dengan sentimen."""
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(COMMENT_HEADER)
    for c in comments:
        created = c["created_at"]
        writer.writerow([
            meta["date"], meta["url"], meta["shortcode"], c["author"],
            " ".join(c["text"].split()),
            created.strftime("%Y-%m-%d %H:%M:%S") if isinstance(created, datetime) else "",
            c["likes"], c["parent_id"] or "", c["sentiment"], c["score"],
        ])
    return buf.getvalue()


def scrape(raw_url: str) -> dict:
    """Ambil post + komentar, kembalikan payload JSON siap kirim."""
    import instaloader
    from instaloader import exceptions as il_exc

    # Nama exception berbeda antar versi instaloader.
    not_found = tuple(
        exc
        for name in ("PostNotFoundException", "QueryReturnedNotFoundException")
        if (exc := getattr(il_exc, name, None)) is not None
    ) or (il_exc.QueryReturnedBadRequestException,)

    shortcode = parse_shortcode(raw_url)
    loader = _loader()

    try:
        post = instaloader.Post.from_shortcode(loader.context, shortcode)
    except not_found:
        raise ScrapeError("Post tidak ditemukan, dihapus, atau bukan akun publik.")
    except il_exc.LoginRequiredException:
        raise ScrapeError(
            "Instagram meminta login. Set env var IG_USERNAME dan IG_SESSIONID di server."
        )
    except (il_exc.PrivateProfileNotFollowedException, il_exc.QueryReturnedForbiddenException):
        raise ScrapeError("Akun ini privat atau membatasi akses, jadi tidak bisa diambil.")
    except (il_exc.BadResponseException, il_exc.QueryReturnedBadRequestException):
        raise ScrapeError(
            "Instagram menolak permintaan tanpa login. Set env var IG_USERNAME dan "
            "IG_SESSIONID di server, lalu coba lagi."
        )
    except il_exc.ConnectionException:
        raise ScrapeError("Gagal menghubungi Instagram (rate limit / jaringan). Coba lagi nanti.")

    media = _media_urls(post)
    comments = _collect_comments(post)
    sentiment = Counter(c["sentiment"] for c in comments)

    type_map = {"GraphVideo": "video", "GraphImage": "foto", "GraphSidecar": "sidecar"}
    meta = {
        "shortcode": post.shortcode,
        "url": f"https://www.instagram.com/p/{post.shortcode}/",
        "date": post.date_utc.strftime("%Y-%m-%d"),
        "type": type_map.get(post.typename, post.typename),
        "likes": max(int(post.likes or 0), 0),
        "comment_count": int(post.comments or 0),
        "comments_fetched": len(comments),
        "caption": post.caption or "",
    }

    return {
        "ok": True,
        **meta,
        "media": media,
        "sentiment": dict(sentiment),
        "csv": {
            "post": build_post_csv(meta, media, sentiment),
            "comments": build_comments_csv(meta, comments),
        },
    }


def _client_ip(headers) -> str:
    forwarded = headers.get("x-forwarded-for") or ""
    return (forwarded.split(",")[0].strip() or headers.get("x-real-ip") or "local").strip()


class handler(BaseHTTPRequestHandler):
    """Handler Vercel (`@vercel/python`) sekaligus server lokal."""

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", "no-store")
        self.send_header("access-control-allow-origin", os.environ.get("ALLOW_ORIGIN", "*"))
        self.send_header("access-control-allow-methods", "POST, GET, OPTIONS")
        self.send_header("access-control-allow-headers", "content-type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):  # noqa: N802
        self._send(204, {})

    def do_GET(self):  # noqa: N802
        self._send(200, {
            "ok": True,
            "endpoint": "/api/scrape",
            "usage": 'POST {"url": "https://www.instagram.com/p/SHORTCODE/"}',
            "session": bool(os.environ.get("IG_SESSIONID")),
        })

    def do_POST(self):  # noqa: N802
        ip = _client_ip(self.headers)
        now = time.monotonic()
        if now - _last_call.get(ip, 0) < RATE_LIMIT_SECONDS:
            self._send(429, {"ok": False, "error": "Tunggu beberapa detik sebelum mencoba lagi."})
            return
        _last_call[ip] = now

        try:
            length = int(self.headers.get("content-length") or 0)
            if length > 10_000:
                raise ScrapeError("Body request terlalu besar.")
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise ScrapeError("Body harus JSON: {\"url\": \"...\"}")
            if not isinstance(body, dict):
                raise ScrapeError("Body harus berupa objek JSON.")
        except ScrapeError as exc:
            self._send(400, {"ok": False, "error": str(exc)})
            return

        try:
            data = scrape(str(body.get("url") or ""))
        except BadRequest as exc:
            self._send(400, {"ok": False, "error": str(exc)})
        except ScrapeError as exc:
            self._send(502, {"ok": False, "error": str(exc)})
        except Exception as exc:  # jangan bocorkan detail internal
            print(f"scrape error: {exc!r}", file=sys.stderr)
            self._send(500, {"ok": False, "error": "Terjadi kesalahan di server. Coba lagi."})
        else:
            self._send(200, data)


if __name__ == "__main__":
    from http.server import ThreadingHTTPServer

    port = int(os.environ.get("PORT", "8000"))
    print(f"API lokal: http://127.0.0.1:{port}/api/scrape")
    ThreadingHTTPServer(("127.0.0.1", port), handler).serve_forever()
