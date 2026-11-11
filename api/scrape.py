"""Endpoint serverless: ambil satu post publik (Instagram/TikTok/X) + komentarnya → CSV.

Dipakai dashboard `web/` lewat form "Ambil CSV dari link post".
Berjalan sebagai Vercel Python function (`/api/scrape`) atau server lokal:

    python api/scrape.py          # http://127.0.0.1:8000/api/scrape

Body request:  {"url": "https://www.instagram.com/p/SHORTCODE/"}
Balasan:       JSON {ok, platform, shortcode, ..., csv: {post, comments}}

Platform yang dikenali:
    Instagram  https://www.instagram.com/p/…, /reel/…, /tv/…      (instaloader)
    TikTok     https://www.tiktok.com/@user/video/…, vm.tiktok.com/…  (yt-dlp)
    X          https://x.com/user/status/…, twitter.com/…           (syndication)

Env var:
    IG_USERNAME / IG_SESSIONID / IG_CSRFTOKEN   sesi Instagram (sangat disarankan)
    TIKTOK_COOKIES                              header cookie TikTok, opsional
    ALLOW_ORIGIN                                origin CORS (default *)

Catatan: Instagram butuh sesi untuk komentar; TikTok dan X hanya memberi
komentar lewat API resmi/berbayar, jadi CSV-nya bisa berisi metadata saja.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from urllib.parse import quote, urlparse, urlsplit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import config  # noqa: E402,F401  (memuat .env saat dijalankan lokal)
from sentiment import score as sentiment_score  # noqa: E402

# Username opsional: instagram.com/p/KODE, /reel/KODE, /akun/p/KODE, /akun/reel/KODE
IG_RE = re.compile(
    r"instagram\.com/(?:[A-Za-z0-9._]{1,30}/)?(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)", re.I
)
IG_BARE_RE = re.compile(r"^[A-Za-z0-9_-]{5,20}$")
TT_RE = re.compile(r"tiktok\.com/(?:@[A-Za-z0-9_.-]+/)?(?:video|photo|v)/(\d{6,25})", re.I)
TT_SHORT_PATH_RE = re.compile(r"^/(?:t/)?([A-Za-z0-9]{5,})/?$")
X_RE = re.compile(r"(?:twitter|x)\.com/[A-Za-z0-9_]{1,30}/status(?:es)?/(\d{1,25})", re.I)

PLATFORM_NAME = {"instagram": "Instagram", "tiktok": "TikTok", "x": "X"}
MAX_COMMENTS = 250
MAX_REPLIES_PER_COMMENT = 5
RATE_LIMIT_SECONDS = 10
HTTP_TIMEOUT = 25
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Jeda per IP supaya satu instance tidak dipakai berlebihan.
_last_call: dict[str, float] = {}

POST_HEADER = [
    "platform", "tanggal", "url", "shortcode", "tipe", "likes", "jumlah_komentar",
    "komentar_diambil", "sentimen_positif", "sentimen_negatif",
    "jumlah_media", "caption",
]

COMMENT_HEADER = [
    "platform", "tanggal_post", "post_url", "shortcode", "penulis", "komentar",
    "tanggal_komentar", "likes_komentar", "balasan_dari", "sentimen", "skor",
]


class ScrapeError(Exception):
    """Kesalahan yang aman ditampilkan ke pengguna."""


class BadRequest(ScrapeError):
    """Input pengguna tidak valid (HTTP 400)."""


# --------------------------------------------------------------------------
# Parsing link
# --------------------------------------------------------------------------

def _is_tiktok_short(url: str) -> bool:
    """Cek link pendek TikTok: vm.tiktok.com/ZM…, vt.tiktok.com/ZS…, /t/ZM…"""
    parsed = urlparse(url)
    if "tiktok.com" not in (parsed.hostname or "").lower():
        return False
    return bool(TT_SHORT_PATH_RE.match(parsed.path or "")) and not TT_RE.search(url)


def parse_target(raw: str) -> tuple[str, str]:
    """Tebak platform + id post dari sebuah link.

    Mengembalikan ("instagram"|"tiktok"|"x", id). Untuk link pendek TikTok
    (`vm.tiktok.com/…`) id masih kosong dan di-resolve saat pengambilan data.
    """
    value = (raw or "").strip()
    if not value:
        raise BadRequest("Link post masih kosong.")

    if match := IG_RE.search(value):
        return "instagram", match.group(1)
    if match := X_RE.search(value):
        return "x", match.group(1)
    if match := TT_RE.search(value):
        return "tiktok", match.group(1)

    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if _is_tiktok_short(value):
        return "tiktok", ""
    if host and "instagram.com" in host:
        raise BadRequest(
            "Link Instagram tidak dikenali. Tempel link post/reel, contoh: "
            "https://www.instagram.com/p/xxxxx/ atau https://www.instagram.com/reel/xxxxx/"
        )
    if host and ("tiktok.com" in host or "douyin.com" in host):
        raise BadRequest(
            "Link TikTok tidak dikenali. Contoh: https://www.tiktok.com/@akun/video/123…"
        )
    if host and ("x.com" in host or "twitter.com" in host):
        raise BadRequest("Link X tidak dikenali. Contoh: https://x.com/akun/status/123…")

    if IG_BARE_RE.match(value):
        return "instagram", value

    raise BadRequest(
        "Link tidak dikenali. Tempel link post Instagram, TikTok, atau X. "
        "Contoh: https://www.instagram.com/p/xxxxx/"
    )


# --------------------------------------------------------------------------
# Helper HTTP + tanggal
# --------------------------------------------------------------------------

def _http_get(url: str, headers: dict | None = None, max_bytes: int = 12_000_000) -> bytes:
    request = urllib.request.Request(url, headers={"user-agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            return response.read(max_bytes)
    except urllib.error.HTTPError as exc:
        if exc.code in (404, 410):
            raise ScrapeError("Post tidak ditemukan, dihapus, atau bukan konten publik.")
        if exc.code in (401, 403):
            raise ScrapeError(
                "Platform menolak permintaan tanpa login (HTTP %d). Coba lagi nanti." % exc.code
            )
        if exc.code == 429:
            raise ScrapeError("Kena rate limit platform (HTTP 429). Coba lagi beberapa menit.")
        raise ScrapeError("Platform membalas HTTP %d. Coba lagi nanti." % exc.code)
    except urllib.error.URLError as exc:
        raise ScrapeError("Gagal menghubungi platform: %s." % (exc.reason,))
    except TimeoutError:
        raise ScrapeError("Permintaan ke platform terlalu lama (timeout). Coba lagi.")


def _http_json(url: str, headers: dict | None = None) -> dict:
    raw = _http_get(url, headers)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ScrapeError("Platform tidak mengirim data JSON yang bisa dibaca.")
    if not isinstance(data, dict):
        raise ScrapeError("Format data dari platform tidak dikenali.")
    return data


def _to_int(value) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def _from_epoch(value) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _from_iso(value) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=None)
        except ValueError:
            continue
    return None


def _clean_text(value) -> str:
    return " ".join(str(value or "").replace("\r", " ").split())


# --------------------------------------------------------------------------
# Adapter Instagram (instaloader)
# --------------------------------------------------------------------------

def _ig_loader():
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


def _ig_media_urls(post) -> list[str]:
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


def _ig_comment_error(exc: Exception) -> str:
    """Ubah exception instaloader jadi kalimat yang bisa ditampilkan ke pengguna."""
    name = type(exc).__name__
    text = str(exc).lower()
    if name == "LoginRequiredException" or "login" in text or "logged in" in text:
        return (
            "Instagram menolak daftar komentar tanpa sesi login. Set env var "
            "IG_USERNAME dan IG_SESSIONID di server, lalu coba lagi."
        )
    if "feedback_required" in text or name == "AbortDownloadException":
        return (
            "Instagram menolak permintaan komentar (feedback_required). Login ulang di "
            "browser lalu perbarui IG_SESSIONID dan IG_CSRFTOKEN."
        )
    if name in ("TooManyRequestsException", "ConnectionException") or "429" in text:
        return "Instagram membatasi permintaan komentar (rate limit). Coba lagi beberapa menit."
    if "timeout" in text or name in ("ReadTimeout", "TimeoutError"):
        return "Pengambilan komentar terlalu lama (timeout). Coba lagi."
    return f"Komentar gagal diambil dari Instagram ({name}). Coba lagi nanti."


def _ig_comments(post) -> tuple[list[dict], str]:
    """Ambil komentar + balasan. Mengembalikan (baris, catatan kegagalan)."""
    rows: list[dict] = []
    try:
        for comment in post.get_comments():
            rows.append(_comment_row(comment.owner.username if comment.owner else "",
                                     comment.text, comment.likes, comment.created_at, None))
            replies = 0
            try:
                for answer in comment.answers:
                    if replies >= MAX_REPLIES_PER_COMMENT:
                        break
                    rows.append(_comment_row(
                        answer.owner.username if answer.owner else "",
                        answer.text, answer.likes, answer.created_at, comment.id,
                    ))
                    replies += 1
            except Exception:
                pass
            if len(rows) >= MAX_COMMENTS:
                break
    except Exception as exc:  # jangan diam: pengguna perlu tahu kenapa kosong
        return rows[:MAX_COMMENTS], _ig_comment_error(exc)
    return rows[:MAX_COMMENTS], ""


IG_APP_ID = "936619743392459"
IG_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


def _shortcode_to_media_id(shortcode: str) -> str:
    """Konversi shortcode post (DfmgoUHnY7R) ke media id numerik Instagram."""
    value = 0
    for char in shortcode:
        value = value * 64 + IG_ALPHABET.index(char)
    return str(value)


def _ig_api_headers() -> dict:
    """Header API web Instagram, memakai sesi dari env bila ada."""
    headers = {
        "x-ig-app-id": IG_APP_ID,
        "referer": "https://www.instagram.com/",
        "x-requested-with": "XMLHttpRequest",
    }
    sessionid = os.environ.get("IG_SESSIONID", "").strip()
    if sessionid:
        cookie = f"sessionid={sessionid}"
        csrf = os.environ.get("IG_CSRFTOKEN", "").strip()
        if csrf:
            cookie += f"; csrftoken={csrf}"
        headers["cookie"] = cookie
    return headers


def _ig_api_media_url(node: dict) -> str:
    if not isinstance(node, dict):
        return ""
    videos = node.get("video_versions") or []
    if videos and isinstance(videos[0], dict) and videos[0].get("url"):
        return str(videos[0]["url"])
    candidates = (node.get("image_versions2") or {}).get("candidates") or []
    if candidates and isinstance(candidates[0], dict) and candidates[0].get("url"):
        return str(candidates[0]["url"])
    return ""


def _ig_api_comments(media_id: str, headers: dict) -> tuple[list[dict], str]:
    """Komentar lewat API web (tanpa GraphQL). Balasan tidak ikut diambil."""
    rows: list[dict] = []
    min_id = ""
    for _ in range(8):
        endpoint = (
            f"https://i.instagram.com/api/v1/media/{media_id}/comments/"
            "?can_support_threading=true&permalink_enabled=false"
        )
        if min_id:
            endpoint += f"&min_id={quote(min_id)}"
        try:
            payload = _http_json(endpoint, headers)
        except ScrapeError as exc:
            if not rows:
                return [], f"Komentar gagal diambil dari Instagram ({exc})"
            break
        batch = payload.get("comments")
        if not isinstance(batch, list) or not batch:
            break
        for item in batch:
            if not isinstance(item, dict):
                continue
            rows.append(_comment_row(
                (item.get("user") or {}).get("username", ""),
                item.get("text"), item.get("comment_like_count"),
                _from_epoch(item.get("created_at")), None,
            ))
            if len(rows) >= MAX_COMMENTS:
                break
        if len(rows) >= MAX_COMMENTS:
            break
        min_id = str(payload.get("next_min_id") or "")
        if not min_id:
            break

    if not rows:
        if os.environ.get("IG_SESSIONID", "").strip():
            return [], (
                "Instagram menolak daftar komentar untuk sesi ini (balasan \"fail\"), "
                "tapi data post tetap terisi. Login ulang di browser lalu perbarui "
                "IG_SESSIONID dan IG_CSRFTOKEN."
            )
        return [], (
            "Daftar komentar hanya bisa dibaca dengan sesi login. Isi IG_SESSIONID "
            "dan IG_CSRFTOKEN, lalu coba lagi."
        )
    return rows[:MAX_COMMENTS], "Balasan (reply) komentar tidak ikut pada mode cadangan."


def _ig_api_post(shortcode: str) -> dict:
    """Jalur cadangan saat endpoint GraphQL menolak ("feedback_required")."""
    try:
        media_id = _shortcode_to_media_id(shortcode)
    except ValueError:
        raise ScrapeError("Kode post Instagram tidak valid.")

    headers = _ig_api_headers()
    payload = _http_json(f"https://i.instagram.com/api/v1/media/{media_id}/info/", headers)
    items = payload.get("items") or []
    item = items[0] if items and isinstance(items[0], dict) else None
    if not item:
        raise ScrapeError("Post tidak ditemukan, dihapus, atau bukan akun publik.")

    media: list[str] = []
    if item.get("media_type") == 8:
        for node in item.get("carousel_media") or []:
            url = _ig_api_media_url(node)
            if url:
                media.append(url)
    else:
        url = _ig_api_media_url(item)
        if url:
            media.append(url)

    comments, comment_note = _ig_api_comments(media_id, headers)
    taken_at = _from_epoch(item.get("taken_at"))
    type_map = {1: "foto", 2: "video", 8: "sidecar"}
    code = str(item.get("code") or shortcode)

    meta = {
        "platform": "instagram",
        "shortcode": code,
        "url": f"https://www.instagram.com/p/{code}/",
        "date": taken_at.strftime("%Y-%m-%d") if taken_at else "",
        "type": type_map.get(item.get("media_type"), "post"),
        "author": (item.get("user") or {}).get("username", ""),
        "likes": _to_int(item.get("like_count")),
        "comment_count": _to_int(item.get("comment_count")),
        "caption": ((item.get("caption") or {}).get("text") or ""),
    }
    return {"meta": meta, "media": media, "comments": comments, "note": comment_note}


def _instagram(post_id: str) -> dict:
    import instaloader
    from instaloader import exceptions as il_exc

    # Nama exception berbeda antar versi instaloader.
    not_found = tuple(
        exc
        for name in ("PostNotFoundException", "QueryReturnedNotFoundException")
        if (exc := getattr(il_exc, name, None)) is not None
    ) or (il_exc.QueryReturnedBadRequestException,)

    loader = _ig_loader()

    # GraphQL kadang membalas "feedback_required"; API web jadi jalur cadangan.
    graphql_down = tuple(
        exc
        for name in (
            "AbortDownloadException",
            "BadResponseException",
            "QueryReturnedBadRequestException",
            "ConnectionException",
            "TooManyRequestsException",
        )
        if (exc := getattr(il_exc, name, None)) is not None
    )

    try:
        post = instaloader.Post.from_shortcode(loader.context, post_id)
    except graphql_down:
        return _ig_api_post(post_id)
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

    media = _ig_media_urls(post)
    comments, comment_note = _ig_comments(post)
    type_map = {"GraphVideo": "video", "GraphImage": "foto", "GraphSidecar": "sidecar"}

    meta = {
        "platform": "instagram",
        "shortcode": post.shortcode,
        "url": f"https://www.instagram.com/p/{post.shortcode}/",
        "date": post.date_utc.strftime("%Y-%m-%d"),
        "type": type_map.get(post.typename, post.typename),
        "author": post.owner_username or "",
        "likes": _to_int(post.likes),
        "comment_count": _to_int(post.comments),
        "caption": post.caption or "",
    }
    if not comments and not comment_note and _to_int(post.comments) > 0:
        comment_note = (
            "Instagram membalas jumlah komentar, tapi daftarnya tidak bisa dibaca "
            "(kemungkinan karena dibatasi untuk permintaan anonim). Set IG_SESSIONID "
            "lalu coba lagi."
        )

    return {"meta": meta, "media": media, "comments": comments, "note": comment_note}


# --------------------------------------------------------------------------
# Adapter TikTok (yt-dlp + endpoint komentar)
# --------------------------------------------------------------------------

def _tiktok_comments(post_id: str) -> tuple[list[dict], str]:
    """Ambil komentar teratas. TikTok sering membalas kosong tanpa cookie."""
    endpoint = (
        "https://www.tiktok.com/api/comment/list/"
        f"?aweme_id={post_id}&count=50&cursor=0&aid=1988&app_language=id"
        "&app_name=tiktok_web&browser_language=id-ID&browser_platform=Win32"
        "&channel=tiktok_web&device_platform=web_pc&priority_region=ID&region=ID"
    )
    headers = {
        "referer": "https://www.tiktok.com/",
        "accept": "application/json, text/plain, */*",
    }
    cookie = os.environ.get("TIKTOK_COOKIES", "").strip()
    if cookie:
        headers["cookie"] = cookie

    rows: list[dict] = []
    cursor = 0
    for _ in range(6):
        try:
            payload = _http_json(endpoint + f"&cursor={cursor}", headers)
        except ScrapeError:
            break
        batch = payload.get("comments") or []
        if not isinstance(batch, list) or not batch:
            break
        for item in batch:
            if not isinstance(item, dict):
                continue
            rows.append(_comment_row(
                (item.get("user") or {}).get("unique_id", ""),
                item.get("text"), item.get("digg_count"),
                _from_epoch(item.get("create_time")), None,
            ))
            replies = 0
            for reply in item.get("reply_comment") or []:
                if replies >= MAX_REPLIES_PER_COMMENT or not isinstance(reply, dict):
                    break
                rows.append(_comment_row(
                    (reply.get("user") or {}).get("unique_id", ""),
                    reply.get("text"), reply.get("digg_count"),
                    _from_epoch(reply.get("create_time")), item.get("cid"),
                ))
                replies += 1
            if len(rows) >= MAX_COMMENTS:
                break
        if len(rows) >= MAX_COMMENTS or not payload.get("has_more"):
            break
        cursor = _to_int(payload.get("cursor"))

    if rows:
        return rows[:MAX_COMMENTS], ""
    return [], (
        "TikTok membatasi daftar komentar untuk permintaan tanpa login, jadi CSV "
        "komentar kosong. Post dan metriknya tetap terisi."
    )


def _tiktok_media(info: dict, entries: list[dict]) -> list[str]:
    """URL media dari hasil yt-dlp (video tunggal atau carousel foto)."""
    if entries:
        return [
            url
            for entry in entries
            if (url := entry.get("url") or entry.get("thumbnail"))
        ]

    formats = [
        f for f in (info.get("formats") or [])
        if f.get("vcodec") not in (None, "none") and f.get("url")
    ]
    if formats:
        best = max(formats, key=lambda f: (f.get("height") or 0, f.get("tbr") or 0))
        return [best["url"]]
    if info.get("url"):
        return [info["url"]]
    return [info["thumbnail"]] if info.get("thumbnail") else []


def _tiktok(url: str) -> dict:
    """yt-dlp dipakai karena halaman TikTok sendiri sering diblokir WAF."""
    try:
        import yt_dlp
    except ImportError:
        raise ScrapeError("Server belum memasang yt-dlp, jadi TikTok belum bisa diambil.")

    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "socket_timeout": HTTP_TIMEOUT,
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        text = str(exc).lower()
        if any(word in text for word in ("private", "not available", "404", "removed")):
            raise ScrapeError("Post TikTok tidak ditemukan, privat, atau dihapus.")
        raise ScrapeError("Gagal mengambil data TikTok. Coba lagi nanti.")

    if not isinstance(info, dict):
        raise ScrapeError("Data post TikTok tidak bisa dibaca.")

    entries = [e for e in (info.get("entries") or []) if isinstance(e, dict)]
    post_id = str(info.get("id") or "")
    author = info.get("uploader") or info.get("channel") or ""
    created = _from_epoch(info.get("timestamp"))
    if created is None and info.get("upload_date"):
        try:
            created = datetime.strptime(str(info["upload_date"]), "%Y%m%d")
        except ValueError:
            created = None

    comments, note = _tiktok_comments(post_id)
    meta = {
        "platform": "tiktok",
        "shortcode": post_id,
        "url": info.get("webpage_url") or url,
        "date": (created or datetime.utcnow()).strftime("%Y-%m-%d"),
        "type": "foto" if entries else "video",
        "author": author,
        "likes": _to_int(info.get("like_count")),
        "comment_count": _to_int(info.get("comment_count")),
        "caption": info.get("description") or info.get("title") or "",
    }
    return {
        "meta": meta,
        "media": _tiktok_media(info, entries),
        "comments": comments,
        "note": note,
    }


# --------------------------------------------------------------------------
# Adapter X (endpoint syndication publik)
# --------------------------------------------------------------------------

def _x(tweet_id: str) -> dict:
    payload = _http_json(
        f"https://cdn.syndication.twimg.com/tweet-result?id={tweet_id}&lang=id&token=a",
        {"accept": "application/json"},
    )
    if payload.get("__typename") not in (None, "Tweet") or not payload.get("id_str"):
        raise ScrapeError("Post X tidak ditemukan, dihapus, atau akunnya dikunci.")

    text = payload.get("text") or ""
    for entity in ((payload.get("entities") or {}).get("urls") or []):
        short = entity.get("url")
        if short:
            text = text.replace(short, entity.get("expanded_url") or short)

    media = [
        m.get("media_url_https") or m.get("media_url") or ""
        for m in (payload.get("mediaDetails") or [])
        if isinstance(m, dict)
    ]
    media = [u for u in media if u]
    if not media:
        media = [p.get("url") for p in (payload.get("photos") or []) if isinstance(p, dict)]
        media = [u for u in media if u]

    has_video = any(
        isinstance(m, dict) and (m.get("type") or "").lower() in ("video", "animated_gif")
        for m in (payload.get("mediaDetails") or [])
    )
    author = (payload.get("user") or {}).get("screen_name") or ""
    created = _from_iso(payload.get("created_at")) or datetime.utcnow()

    meta = {
        "platform": "x",
        "shortcode": str(payload.get("id_str") or tweet_id),
        "url": f"https://x.com/{author}/status/{payload.get('id_str') or tweet_id}",
        "date": created.strftime("%Y-%m-%d"),
        "type": "video" if has_video else ("foto" if media else "teks"),
        "author": author,
        "likes": _to_int(payload.get("favorite_count")),
        "comment_count": _to_int(payload.get("conversation_count")),
        "caption": text,
    }
    return {
        "meta": meta,
        "media": media,
        "comments": [],
        "note": (
            "X hanya menyediakan daftar balasan lewat API resmi berbayar, jadi CSV "
            "komentar kosong. Post dan metriknya tetap terisi."
        ),
    }


# --------------------------------------------------------------------------
# Normalisasi + CSV
# --------------------------------------------------------------------------

def _comment_row(author: str, text, likes, created_at, parent_id) -> dict:
    label, value = sentiment_score(text or "")
    return {
        "author": author or "",
        "text": _clean_text(text),
        "likes": _to_int(likes),
        "created_at": created_at,
        "parent_id": parent_id,
        "sentiment": label,
        "score": value,
    }


def build_post_csv(meta: dict, media: list[str], sentiment: Counter) -> str:
    """Satu baris CSV berisi ringkasan post."""
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(POST_HEADER)
    writer.writerow([
        meta["platform"], meta["date"], meta["url"], meta["shortcode"], meta["type"],
        meta["likes"], meta["comment_count"], meta["comments_fetched"],
        sentiment.get("positif", 0) + sentiment.get("sangat positif", 0),
        sentiment.get("negatif", 0) + sentiment.get("sangat negatif", 0),
        len(media), _clean_text(meta["caption"]),
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
            meta["platform"], meta["date"], meta["url"], meta["shortcode"],
            c["author"], _clean_text(c["text"]),
            created.strftime("%Y-%m-%d %H:%M:%S") if isinstance(created, datetime) else "",
            c["likes"], c["parent_id"] or "", c["sentiment"], c["score"],
        ])
    return buf.getvalue()


def scrape(raw_url: str) -> dict:
    """Ambil post + komentar dari platform mana pun, kembalikan payload JSON."""
    platform, post_id = parse_target(raw_url)
    url = (raw_url or "").strip()

    if platform == "instagram":
        result = _instagram(post_id)
    elif platform == "tiktok":
        result = _tiktok(url)
    else:
        result = _x(post_id)

    meta = result["meta"]
    comments = result["comments"]
    media = result["media"]
    meta["comments_fetched"] = len(comments)
    sentiment = Counter(c["sentiment"] for c in comments)

    return {
        "ok": True,
        **meta,
        "media": media,
        "sentiment": dict(sentiment),
        "note": result.get("note", ""),
        "csv": {
            "post": build_post_csv(meta, media, sentiment),
            "comments": build_comments_csv(meta, comments),
        },
    }


# --------------------------------------------------------------------------
# HTTP handler (Vercel + server lokal)
# --------------------------------------------------------------------------

def _client_ip(headers) -> str:
    forwarded = headers.get("x-forwarded-for") or ""
    return (forwarded.split(",")[0].strip() or headers.get("x-real-ip") or "local").strip()


WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
SERVE_WEB = False  # hanya aktif saat dijalankan lokal (`python api/scrape.py`)
STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".webmanifest": "application/manifest+json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
}


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

    def _send_file(self, relative: str) -> None:
        """Sajikan file dari folder web/ untuk pemakaian lokal."""
        target = os.path.normpath(os.path.join(WEB_DIR, relative.lstrip("/")))
        if not target.startswith(WEB_DIR) or not os.path.isfile(target):
            self._send(404, {"ok": False, "error": "Halaman tidak ditemukan."})
            return
        with open(target, "rb") as handle:
            body = handle.read()
        kind = STATIC_TYPES.get(os.path.splitext(target)[1].lower(), "application/octet-stream")
        self.send_response(200)
        self.send_header("content-type", kind)
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if SERVE_WEB and not self.path.startswith("/api/"):
            path = urlsplit(self.path).path
            self._send_file("index.html" if path in ("", "/") else path)
            return
        self._send(200, {
            "ok": True,
            "endpoint": "/api/scrape",
            "platforms": list(PLATFORM_NAME.values()),
            "usage": 'POST {"url": "https://www.instagram.com/p/SHORTCODE/"}',
            "session": {
                "instagram": bool(os.environ.get("IG_SESSIONID")),
                "tiktok": bool(os.environ.get("TIKTOK_COOKIES")),
            },
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

    SERVE_WEB = True
    port = int(os.environ.get("PORT", "8000"))
    print(f"Dashboard lokal: http://127.0.0.1:{port}/")
    print(f"API lokal:       http://127.0.0.1:{port}/api/scrape")
    ThreadingHTTPServer(("127.0.0.1", port), handler).serve_forever()
