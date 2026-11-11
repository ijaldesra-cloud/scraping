"""Konfigurasi scraping Instagram: akun target dan rentang tanggal.

Semua bisa diubah lewat environment variable, jadi tools ini tidak terikat ke
satu akun tertentu:

    IG_TARGET      akun Instagram yang di-scrape, tanpa @
    IG_SINCE       batas awal analisis, format YYYY-MM-DD (kosong = semua post)
    IG_SCAN_SINCE  batas mundur pengambilan post (default: IG_SINCE, atau semua)
"""

import os


def load_dotenv(path: str = ".env") -> None:
    """Baca .env sederhana (KEY=value) kalau ada. Env sistem tetap menang."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("\"'").strip())


load_dotenv()

# Akun yang di-scrape. Ganti di sini atau lewat env IG_TARGET.
USERNAME = (os.environ.get("IG_TARGET") or "humas.polrespurwakarta").strip().lstrip("@")

# Tanggal awal yang dianalisis. Kosong = semua post yang tersimpan dipakai.
ANCHOR_DATE = os.environ.get("IG_SINCE", "").strip()

# Post yang lebih tua dari ini tidak diambil lagi saat koleksi.
SCAN_SINCE = os.environ.get("IG_SCAN_SINCE", "").strip() or ANCHOR_DATE or "1970-01-01"

# Kata yang diabaikan saat mencari frasa di komentar (nama akun, instansi, dll).
EXTRA_STOPWORDS = ("humas", "polres", "purwakarta", "polrespurwakarta",
                   "polri", "polisi", "kapolres")

# Jeda antar request (detik) supaya tidak kena rate limit Instagram.
DELAY_SECONDS = 3.0

DATA_DIR = "data"
SESSION_FILE = f"{DATA_DIR}/session"
POSTS_FILE = f"{DATA_DIR}/posts.jsonl"
COMMENTS_FILE = f"{DATA_DIR}/comments.jsonl"
MEDIA_FILE = f"{DATA_DIR}/media.csv"
