"""Konfigurasi scraping akun Instagram humas.polrespurwakarta."""

USERNAME = "humas.polrespurwakarta"

# Tanggal pisah sambut / sertijab Kapolres Purwakarta Anom -> Febri.
# Semua post mulai tanggal ini yang dianalisis.
ANCHOR_DATE = "2026-07-29"

# Batas mundur pencarian post (inklusif). 29 Juli 2026 = tanggal sertijab
# Kapolres Purwakarta dari AKBP I Dewa Putu Gede Anom Danujaya ke AKBP Febri Nurzam.
SCAN_SINCE = "2026-07-28"

# Kata kunci untuk menandai post yang secara eksplisit soal pisah sambut/sertijab.
ANCHOR_KEYWORDS = ("pisah sambut", "sertijab", "serah terima jabatan",
                   "estafet kepemimpinan", "pindah tugas", "terima kasih atas dedikasi")
ANCHOR_NAMES = ("anom", "febri")

# Jeda antar request (detik) supaya tidak kena rate limit Instagram.
DELAY_SECONDS = 3.0

DATA_DIR = "data"
POSTS_FILE = f"{DATA_DIR}/posts.jsonl"
COMMENTS_FILE = f"{DATA_DIR}/comments.jsonl"
MEDIA_FILE = f"{DATA_DIR}/media.csv"
