"""Kolektor post + komentar Instagram untuk satu akun publik.

Dua fase, keduanya resumable:
  1. Metadata post   -> data/posts.jsonl
  2. Komentar + balasan per post (GraphQL, paginasi) -> data/comments.jsonl

Pemakaian:
    python collect.py                    # post + komentar
    python collect.py --posts-only       # metadata post saja
    python collect.py --comments-only    # hanya melengkapi komentar
    python collect.py --max-posts 50
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timezone

import instaloader

import config

# Caption Instagram penuh emoji; konsol Windows default cp1252 akan crash.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

RETRYABLE = (
    instaloader.exceptions.ConnectionException,
    instaloader.exceptions.TooManyRequestsException,
)

# Query hash GraphQL untuk komentar sebuah post dan balasan sebuah komentar.
COMMENTS_QUERY = "97b41c52301f77ce508f55e66d17620e"
REPLIES_QUERY = "51fdd02b67508306ad4484ff574a0b62"


def log(msg: str) -> None:
    print(msg, flush=True)


def load_jsonl(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def load_set(path: str) -> set[str]:
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as fh:
        return set(json.load(fh))


def save_set(path: str, values: set[str]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(sorted(values), fh)
    os.replace(tmp, path)


def pause(base: float = None) -> None:
    time.sleep((base or config.DELAY_SECONDS) * random.uniform(0.8, 1.4))


def with_retry(fn, what: str, max_attempts: int = 5):
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except RETRYABLE as exc:
            if attempt == max_attempts:
                raise
            wait = min(45 * 2 ** (attempt - 1), 600)
            log(f"  .. {what}: {type(exc).__name__}, tunggu {wait}s ({attempt}/{max_attempts})")
            time.sleep(wait)
    raise RuntimeError("unreachable")


def find_session() -> str | None:
    explicit = os.environ.get("IG_SESSIONFILE")
    if explicit and os.path.exists(explicit):
        return explicit
    local = f"{config.DATA_DIR}/session-humas"
    if os.path.exists(local):
        return local
    try:
        cfg_dir = os.path.dirname(instaloader.instaloader.get_default_session_filename("probe"))
        if os.path.isdir(cfg_dir):
            for name in sorted(os.listdir(cfg_dir)):
                if name.startswith("session-"):
                    return os.path.join(cfg_dir, name)
    except Exception:
        pass
    return None


def make_loader() -> instaloader.Instaloader:
    L = instaloader.Instaloader(quiet=True, download_pictures=False, download_videos=False)
    L.context.max_connection_attempts = 2
    path = find_session()
    if path:
        L.load_session_from_file(config.USERNAME, path)
        real_user = L.test_login()
        if real_user:
            L.context.username = real_user
            log(f"login sebagai @{real_user} (session: {path})")
        else:
            log(f"session {path} tidak valid — lanjut anonim")
    else:
        log("mode anonim (tanpa login) — lambat dan rawan diblokir")
    return L


def post_to_dict(post: instaloader.Post) -> dict:
    try:
        caption = post.caption or ""
    except Exception:
        caption = ""

    media = []
    if post.typename == "GraphSidecar":
        try:
            for node in post.get_sidecar_nodes():
                media.append({"type": "video" if node.is_video else "image",
                              "url": node.video_url if node.is_video else node.display_url})
        except Exception:
            pass
    else:
        try:
            media.append({"type": "video" if post.is_video else "image",
                          "url": post.video_url if post.is_video else post.url})
        except Exception:
            pass

    return {
        "shortcode": post.shortcode,
        "url": f"https://www.instagram.com/p/{post.shortcode}/",
        "date_utc": post.date_utc.replace(tzinfo=timezone.utc).isoformat(),
        "type": post.typename,
        "is_video": post.is_video,
        "likes": post.likes,
        "comment_count": post.comments,
        "video_view_count": post.video_view_count if post.is_video else None,
        "video_duration": post.video_duration if post.is_video else None,
        "caption": caption,
        "media": media,
        "tagged_users": list(post.tagged_users) if post.tagged_users else [],
        "location": post.location.name if post.location else "",
    }


# --------------------------------------------------------------------------- #
# Komentar
# --------------------------------------------------------------------------- #

def _comment_row(node: dict, meta: dict, parent_id: str | None) -> dict:
    owner = node.get("owner") or {}
    return {
        "post_shortcode": meta["shortcode"],
        "post_date": meta["date_utc"],
        "post_url": meta["url"],
        "post_caption": meta["caption"][:220],
        "id": str(node.get("id")),
        "parent_id": parent_id,
        "author": owner.get("username", ""),
        "text": node.get("text", ""),
        "created_at": datetime.fromtimestamp(
            node.get("created_at", 0), tz=timezone.utc).isoformat(),
        "likes": int((node.get("edge_liked_by") or {}).get("count", 0) or 0),
    }


def iter_replies(context, comment_id: str):
    after = None
    for _ in range(10):
        variables = {"comment_id": str(comment_id), "first": 50}
        if after:
            variables["after"] = after
        data = context.graphql_query(REPLIES_QUERY, variables)
        edge = (data["data"].get("comment") or {}).get("edge_threaded_comments") or {}
        for item in edge.get("edges", []):
            yield item["node"]
        page = edge.get("page_info") or {}
        if not page.get("has_next_page"):
            return
        after = page.get("end_cursor")
        pause(1.0)


def iter_comments(context, shortcode: str, include_replies: bool = True):
    """Yield (node, parent_id) untuk komentar induk dan balasannya."""
    after = None
    for _ in range(60):
        variables = {"shortcode": shortcode, "first": 50}
        if after:
            variables["after"] = after
        data = context.graphql_query(COMMENTS_QUERY, variables)
        media = data["data"].get("shortcode_media") or {}
        edge = media.get("edge_media_to_parent_comment") or {}
        for item in edge.get("edges", []):
            node = item["node"]
            yield node, None
            if not include_replies:
                continue
            threaded = node.get("edge_threaded_comments") or {}
            count = threaded.get("count", 0) or 0
            if not count:
                continue
            parent_id = str(node.get("id"))
            inline = threaded.get("edges") or []
            if len(inline) >= count:
                for reply in inline:
                    yield reply["node"], parent_id
            else:
                try:
                    for reply in iter_replies(context, node.get("id")):
                        yield reply, parent_id
                except Exception:
                    pass
        page = edge.get("page_info") or {}
        if not page.get("has_next_page"):
            return
        after = page.get("end_cursor")
        pause(1.2)


def fetch_comments(L, meta: dict, include_replies: bool) -> list[dict]:
    return [_comment_row(node, meta, parent)
            for node, parent in iter_comments(L.context, meta["shortcode"], include_replies)]


# --------------------------------------------------------------------------- #
# Fase 1: post
# --------------------------------------------------------------------------- #

def collect_posts(L, scan_since, args, posts_meta: dict) -> tuple[int, bool]:
    profile = with_retry(
        lambda: instaloader.Profile.from_username(L.context, config.USERNAME), "ambil profil")
    log(f"@{profile.username}: {profile.followers} follower")

    state_path = f"{config.DATA_DIR}/iterator_state.json"
    new_posts = 0
    processed = 0
    stale_run = 0
    seen_idx = 0
    done = False

    while not done:
        try:
            iterator = profile.get_posts()
            if os.path.exists(state_path):
                try:
                    iterator.thaw(instaloader.load_structure_from_file(L.context, state_path))
                    log("lanjut dari cursor tersimpan")
                except Exception as exc:
                    log(f"cursor tidak dipakai: {type(exc).__name__}")

            for post in iterator:
                seen_idx += 1
                if seen_idx % 12 == 1 and seen_idx > 1:
                    time.sleep(random.uniform(8, 14))

                if post.date_utc.replace(tzinfo=timezone.utc) < scan_since:
                    stale_run += 1
                    if stale_run >= 4:
                        log(f"berhenti: sudah lewat {config.SCAN_SINCE}")
                        done = True
                        break
                    continue
                stale_run = 0

                if post.shortcode in posts_meta:
                    continue

                meta = post_to_dict(post)
                with open(config.POSTS_FILE, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(meta, ensure_ascii=False) + "\n")
                posts_meta[meta["shortcode"]] = meta
                new_posts += 1
                processed += 1

                log(f"[{new_posts:4}] {meta['date_utc'][:10]} L{meta['likes']:<5} "
                    f"C{meta['comment_count']:<4} {meta['shortcode']} "
                    f"{meta['caption'][:50]!r}")

                if args.max_posts and new_posts >= args.max_posts:
                    log("batas --max-posts tercapai")
                    done = True
                    break

                if processed % 5 == 0:
                    try:
                        instaloader.save_structure_to_file(iterator.freeze(), state_path)
                    except Exception:
                        pass
                    pause()
            done = True
        except RETRYABLE as exc:
            log(f"koneksi terputus ({type(exc).__name__}), coba lagi 90s")
            time.sleep(90)

    return new_posts, done


# --------------------------------------------------------------------------- #
# Fase 2: komentar
# --------------------------------------------------------------------------- #

def collect_comments(L, posts_meta: dict, include_replies: bool) -> int:
    done_path = f"{config.DATA_DIR}/comments_done.json"
    done = load_set(done_path)

    pending = [p for p in posts_meta.values()
               if p["date_utc"][:10] >= config.ANCHOR_DATE
               and p["comment_count"] > 0
               and p["shortcode"] not in done]
    pending.sort(key=lambda p: p["date_utc"])

    if not pending:
        log("komentar: semua post sudah lengkap")
        return 0

    log(f"komentar: {len(pending)} post belum ditarik")
    total = 0
    for i, meta in enumerate(pending, 1):
        try:
            rows = with_retry(
                lambda m=meta: fetch_comments(L, m, include_replies),
                f"komentar {meta['shortcode']}", max_attempts=3)
            with open(config.COMMENTS_FILE, "a", encoding="utf-8") as fh:
                for row in rows:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            total += len(rows)
            done.add(meta["shortcode"])
            save_set(done_path, done)
            log(f"  [{i}/{len(pending)}] {meta['date_utc'][:10]} {meta['shortcode']} "
                f"-> {len(rows)}/{meta['comment_count']} komentar")
        except Exception as exc:
            log(f"  ! {meta['shortcode']} gagal: {type(exc).__name__}: "
                f"{str(exc)[:120]}".replace("\n", " "))
            time.sleep(20)
        pause(1.5)
    return total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default=None, help="path file session instaloader")
    ap.add_argument("--posts-only", action="store_true")
    ap.add_argument("--comments-only", action="store_true")
    ap.add_argument("--no-replies", action="store_true")
    ap.add_argument("--max-posts", type=int, default=0)
    args = ap.parse_args()

    os.makedirs(config.DATA_DIR, exist_ok=True)
    scan_since = datetime.fromisoformat(config.SCAN_SINCE).replace(tzinfo=timezone.utc)
    posts_meta = {p["shortcode"]: p for p in load_jsonl(config.POSTS_FILE)}
    log(f"resume: {len(posts_meta)} post tersimpan")

    L = make_loader()
    if args.session:
        L.load_session_from_file(config.USERNAME, args.session)

    if not args.comments_only:
        collect_posts(L, scan_since, args, posts_meta)

    added = 0
    if not args.posts_only:
        added = collect_comments(L, posts_meta, not args.no_replies)

    log(f"selesai. post tersimpan: {len(posts_meta)} | komentar baru: {added}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
