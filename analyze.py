"""Analisis post + komentar satu akun Instagram (lihat config.USERNAME).

Membaca data/posts.jsonl dan data/comments.jsonl (hasil collect.py), lalu:
  - data/posts.csv, data/comments.csv   -> data siap olah di Excel/Sheets
  - data/summary.json                   -> angka ringkas untuk dipakai ulang
  - laporan.md                          -> laporan naratif bahasa Indonesia

Pemakaian:
    python analyze.py
"""

from __future__ import annotations

import csv
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime
from statistics import mean, median

import config
from sentiment import score as sentiment_score, LABEL_ID

POSITIVE_HINT = {"positif", "sangat positif"}
NEGATIVE_HINT = {"negatif", "sangat negatif"}

THEMES = {
    "Lalu lintas / kendaraan": ["lalu lintas", "lantas", "tilang", "helm", "motor", "truk",
                                "terpal", "parkir", "plat", "sim ", "stnk", "kecelakaan"],
    "Kamtibmas / patroli": ["kamtibmas", "patroli", "kryd", "jaga", "keamanan", "ronda",
                            "malam", "siskamling"],
    "Narkoba": ["narkoba", "narkotika", "sabu", "ganja", "obat"],
    "Curanmor / kriminal": ["curanmor", "maling", "begal", "pencurian", "curat", "curas",
                            "penganiayaan", "celurit", "geng motor", "tawuran", "tersangka"],
    "Bantuan sosial / air bersih": ["air bersih", "bansos", "bantuan", "sembako", "donor",
                                    "santunan", "peduli", "berbagi"],
    "Pendidikan / sosialisasi": ["sekolah", "pelajar", "siswa", "edukasi", "sosialisasi",
                                 "bullying", "mahasiswa"],
    "Kritik / keluhan": ["kecewa", "pungli", "pencitraan", "tebar pesona", "bohong", "tutup",
                         "usut", "ogah", "capek", "males", "gak percaya", "tidak percaya",
                         "hanya", "jangan", "parah", "kok bisa", "sia-sia"],
    "Dukungan / apresiasi": ["mantap", "semangat", "sukses", "bangga", "terima kasih",
                             "apresiasi", "keren", "hebat", "salut", "dukung", "lanjutkan",
                             "alhamdulillah", "semoga"],
}

WORD_RE = re.compile(r"[@#]?\w+", re.UNICODE)
WORD_ONLY = re.compile(r"[a-zA-Z]{4,}")

STOPWORDS = {
    "yang", "untuk", "dengan", "dari", "dalam", "akan", "juga", "bisa", "tidak",
    "sudah", "masih", "sama", "kita", "kami", "saya", "anda", "para", "pada",
    "adalah", "ini", "itu", "dan", "atau", "tapi", "kalau", "kalo", "biar",
    "banget", "bgt", "sih", "aja", "saja", "dong", "deh", "mah", "teh", "nya",
    "terima", "kasih", "makasih", "semoga", "mari", "ayo", "jangan", "harus",
    "lebih", "sangat", "paling", "banyak", "orang", "kalo", "gak", "nggak", "engga",
    "the", "and", "you", "good", "nice", "sangat", "sekali", "banget", "malah",
    "instagram", "video", "foto", "konten",
} | {w.lower() for w in config.EXTRA_STOPWORDS}


def top_phrases(comments: list[dict], limit: int = 10) -> list[tuple[str, int]]:
    """Frasa dua kata yang paling sering muncul di komentar (tanpa stopword)."""
    counter: Counter = Counter()
    for c in comments:
        words = [w.lower() for w in WORD_ONLY.findall(c["text"] or "")]
        words = [w for w in words if w not in STOPWORDS]
        for a, b in zip(words, words[1:]):
            counter[f"{a} {b}"] += 1
    return counter.most_common(limit)



def load_jsonl(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def themes_of(text: str) -> list[str]:
    t = norm(text)
    return [name for name, keys in THEMES.items() if any(k in t for k in keys)]


def week_key(iso: str) -> str:
    d = datetime.fromisoformat(iso)
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def pct(part: int, total: int) -> str:
    return f"{(100 * part / total):.1f}%" if total else "0.0%"


def main() -> None:
    posts = [p for p in load_jsonl(config.POSTS_FILE) if p["date_utc"][:10] >= config.ANCHOR_DATE]
    comments = [c for c in load_jsonl(config.COMMENTS_FILE) if c["post_date"][:10] >= config.ANCHOR_DATE]
    posts.sort(key=lambda p: p["date_utc"])

    if not posts:
        raise SystemExit("Belum ada data post di rentang tanggal ini. Jalankan collect.py dulu.")

    media_by_post = defaultdict(list)
    if os.path.exists(config.MEDIA_FILE):
        with open(config.MEDIA_FILE, encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                media_by_post[row["shortcode"]].append(row["media_url"])

    # ---------- komentar: sentimen & tema ----------
    for c in comments:
        c["sentiment"], c["sent_score"] = sentiment_score(c["text"])
        c["themes"] = themes_of(c["text"])

    per_post = defaultdict(list)
    for c in comments:
        per_post[c["post_shortcode"]].append(c)

    # ---------- siapa yang sebenarnya berkomentar ----------
    commenters = Counter(c["author"] for c in comments)

    # ---------- post-level ----------
    for p in posts:
        cs = per_post.get(p["shortcode"], [])
        pos = sum(1 for c in cs if c["sentiment"] in POSITIVE_HINT)
        neg = sum(1 for c in cs if c["sentiment"] in NEGATIVE_HINT)
        p["_comment_rows"] = len(cs)
        p["_pos"] = pos
        p["_neg"] = neg
        p["_themes"] = sorted({t for c in cs for t in c["themes"]})

    total_likes = sum(max(p["likes"], 0) for p in posts)
    total_comments_meta = sum(p["comment_count"] for p in posts)

    # ---------- ekspor CSV ----------
    os.makedirs(config.DATA_DIR, exist_ok=True)

    with open(f"{config.DATA_DIR}/posts.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["tanggal", "url", "shortcode", "tipe", "likes", "jumlah_komentar",
                    "komentar_relevan", "sentimen_positif", "sentimen_negatif",
                    "tema_dominan", "jumlah_media", "caption"])
        for p in posts:
            w.writerow([p["date_utc"][:19].replace("T", " "), p["url"], p["shortcode"],
                        p["type"], p["likes"], p["comment_count"], p["_comment_rows"],
                        p["_pos"], p["_neg"], "; ".join(p["_themes"]),
                        len(media_by_post.get(p["shortcode"], [])),
                        norm(p["caption"])])

    with open(f"{config.DATA_DIR}/comments.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["tanggal_post", "post_url", "shortcode", "komentar_id", "balasan_dari",
                    "penulis", "komentar", "tanggal_komentar", "likes_komentar",
                    "sentimen", "skor", "tema"])
        for c in sorted(comments, key=lambda c: c["created_at"]):
            w.writerow([c["post_date"][:10], c["post_url"], c["post_shortcode"], c["id"],
                        c["parent_id"] or "", c["author"], norm(c["text"]),
                        c["created_at"][:19].replace("T", " "), c["likes"],
                        c["sentiment"], c["sent_score"], "; ".join(c["themes"])])

    # ---------- agregat ----------
    sentiment_counts = Counter(c["sentiment"] for c in comments)
    theme_counts = Counter(t for c in comments for t in c["themes"])

    weekly_posts = defaultdict(lambda: {"posts": 0, "likes": 0, "comments": 0})
    for p in posts:
        wk = week_key(p["date_utc"])
        weekly_posts[wk]["posts"] += 1
        weekly_posts[wk]["likes"] += max(p["likes"], 0)
        weekly_posts[wk]["comments"] += p["comment_count"]

    top_by_comments = sorted(posts, key=lambda p: -p["comment_count"])[:10]
    top_by_likes = sorted(posts, key=lambda p: -p["likes"])[:10]
    top_comments = sorted(comments, key=lambda c: -c["likes"])[:15]

    phrases = top_phrases(comments)
    monthly: dict[str, dict[str, int]] = defaultdict(lambda: {"posts": 0, "likes": 0, "comments": 0})
    for p in posts:
        m = p["date_utc"][:7]
        monthly[m]["posts"] += 1
        monthly[m]["likes"] += max(p["likes"], 0)
        monthly[m]["comments"] += p["comment_count"]

    summary = {
        "akun": config.USERNAME,
        "periode": {"dari": config.ANCHOR_DATE or posts[0]["date_utc"][:10],
                    "sampai": posts[-1]["date_utc"][:10]},
        "jumlah_post": len(posts),
        "total_likes": total_likes,
        "total_komentar_meta": total_comments_meta,
        "komentar_terkumpul": len(comments),
        "komentator_unik": len(commenters),
        "rata_likes_per_post": round(mean(max(p["likes"], 0) for p in posts), 1),
        "median_likes_per_post": round(median(max(p["likes"], 0) for p in posts), 1),
        "rata_komentar_per_post": round(total_comments_meta / len(posts), 1),
        "post_dengan_komentar": sum(1 for p in posts if p["comment_count"] > 0),
        "sentimen": dict(sentiment_counts),
        "tema": dict(theme_counts.most_common(12)),
        "top_komentator": dict(commenters.most_common(10)),
    }
    with open(f"{config.DATA_DIR}/summary.json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)

    # ---------- laporan.md ----------
    L = []
    A = L.append
    positif = sum(v for k, v in sentiment_counts.items() if k in POSITIVE_HINT)
    negatif = sum(v for k, v in sentiment_counts.items() if k in NEGATIVE_HINT)
    netral = len(comments) - positif - negatif

    A(f"# Respon Publik IG @{config.USERNAME}")
    A("")
    A(f"Periode **{config.ANCHOR_DATE or posts[0]['date_utc'][:10]} – "
      f"{posts[-1]['date_utc'][:10]}**.")
    A("")
    A("## 1. Angka kunci")
    A("")
    A("| Metrik | Nilai |")
    A("| --- | --- |")
    A(f"| Post dianalisis | {len(posts):,} |")
    A(f"| Total like | {total_likes:,} |")
    A(f"| Total komentar (metadata IG) | {total_comments_meta:,} |")
    A(f"| Komentar berhasil ditarik | {len(comments):,} |")
    A(f"| Komentator unik | {len(commenters):,} |")
    A(f"| Rata-rata like/post | {summary['rata_likes_per_post']:,} |")
    A(f"| Median like/post | {summary['median_likes_per_post']:,} |")
    A(f"| Post yang punya komentar | {summary['post_dengan_komentar']:,} "
      f"({pct(summary['post_dengan_komentar'], len(posts))}) |")
    A("")
    A("## 2. Temuan utama")
    A("")

    top_theme = theme_counts.most_common(1)
    peak_week = max(weekly_posts.items(), key=lambda kv: kv[1]["comments"])
    peak_post = top_by_comments[0] if top_by_comments else None

    A(f"- Respon publik **condong positif**: {pct(positif, len(comments))} komentar positif, "
      f"{pct(negatif, len(comments))} negatif, {pct(netral, len(comments))} netral.")
    if top_theme:
        A(f"- Tema paling dominan adalah **{top_theme[0][0].lower()}** "
          f"({top_theme[0][1]:,} komentar), diikuti "
          + ", ".join(f"{n.lower()} ({c:,})" for n, c in theme_counts.most_common(3)[1:]) + ".")
    if peak_post:
        A(f"- Post paling ramai: {peak_post['url']} ({peak_post['date_utc'][:10]}) dengan "
          f"{peak_post['comment_count']:,} komentar dan {max(peak_post['likes'], 0):,} like — "
          f"isu yang paling menarik perhatian publik.")
    A(f"- Puncak percakapan terjadi minggu **{peak_week[0]}** "
      f"({peak_week[1]['comments']:,} komentar).")
    A(f"- Median like hanya {summary['median_likes_per_post']:,.0f} tapi rata-rata "
      f"{summary['rata_likes_per_post']:,.0f}, artinya distribusi engagement sangat timpang: "
      f"segelintir post viral menyeret total, mayoritas post datar.")
    if phrases:
        A("- Frasa yang paling sering dibicarakan: "
          + ", ".join(f"**{p}** ({n}x)" for p, n in phrases[:5]) + ".")
    A("")
    A("## 3. Aktivitas per bulan")
    A("")
    A("| Bulan | Post | Like | Komentar |")
    A("| --- | --- | --- | --- |")
    for m in sorted(monthly):
        d = monthly[m]
        A(f"| {m} | {d['posts']} | {d['likes']:,} | {d['comments']:,} |")
    A("")
    A("## 4. Aktivitas per minggu")
    A("")
    A("| Minggu | Post | Like | Komentar |")
    A("| --- | --- | --- | --- |")
    for wk in sorted(weekly_posts):
        d = weekly_posts[wk]
        A(f"| {wk} | {d['posts']} | {d['likes']:,} | {d['comments']:,} |")
    A("")
    A("## 5. Sentimen komentar")
    A("")
    A(f"- Positif: **{positif:,}** ({pct(positif, len(comments))})")
    A(f"- Negatif: **{negatif:,}** ({pct(negatif, len(comments))})")
    A(f"- Netral : **{netral:,}** ({pct(netral, len(comments))})")
    A("")
    A("> Sentimen dihitung dengan kamus kata Indonesia + penanganan negasi sederhana. "
      "Baca `data/comments.csv` untuk verifikasi manual; ini sinyal kasar, bukan klasifikasi sempurna.")
    A("")
    A("## 6. Tema yang muncul di komentar")
    A("")
    if theme_counts:
        A("| Tema | Jumlah komentar |")
        A("| --- | --- |")
        for name, n in theme_counts.most_common(12):
            A(f"| {name} | {n:,} |")
    else:
        A("_Belum ada komentar terkumpul._")
    A("")
    A("## 7. Isu yang paling ramai dibicarakan")
    A("")
    if phrases:
        A("| Frasa | Kemunculan |")
        A("| --- | --- |")
        for phrase, n in phrases:
            A(f"| {phrase} | {n:,} |")
        A("")
        A("Contoh komentar untuk isu teratas:")
        A("")
        for phrase, _ in phrases[:3]:
            tokens = phrase.split()
            samples = [c for c in comments
                       if all(t in norm(c["text"]) for t in tokens)][:3]
            if not samples:
                continue
            A(f"**{phrase}**")
            A("")
            for c in samples:
                A(f"> {norm(c['text'])[:220]}  \n> — @{c['author']}, {c['likes']} like, {c['post_url']}")
            A("")
    else:
        A("_Belum ada komentar terkumpul._")
    A("")
    A("## 8. Post dengan komentar terbanyak")
    A("")
    A("| Tanggal | Komentar | Like | Link | Caption |")
    A("| --- | --- | --- | --- | --- |")
    for p in top_by_comments:
        A(f"| {p['date_utc'][:10]} | {p['comment_count']:,} | {p['likes']:,} | {p['url']} "
          f"| {norm(p['caption'])[:70]}… |")
    A("")
    A("## 9. Post dengan like terbanyak")
    A("")
    A("| Tanggal | Like | Komentar | Link | Caption |")
    A("| --- | --- | --- | --- | --- |")
    for p in top_by_likes:
        A(f"| {p['date_utc'][:10]} | {p['likes']:,} | {p['comment_count']:,} | {p['url']} "
          f"| {norm(p['caption'])[:70]}… |")
    A("")
    A("## 10. Komentar paling banyak disukai (sinyal publik)")
    A("")
    A("| Like | Penulis | Komentar | Post |")
    A("| --- | --- | --- | --- |")
    for c in top_comments:
        text = norm(c["text"]).replace("|", "/")[:160]
        A(f"| {c['likes']:,} | @{c['author']} | {text} | {c['post_url']} |")
    A("")
    A("## 11. Komentator paling aktif")
    A("")
    A("| Akun | Jumlah komentar |")
    A("| --- | --- |")
    for user, n in commenters.most_common(15):
        A(f"| @{user} | {n:,} |")
    A("")
    A("## 12. Catatan metodologi")
    A("")
    A("- Sumber: profil publik Instagram, diambil dengan `instaloader` (tanpa login).")
    A("- Link media (foto/video) di-resolve dengan `@coflyn/scrapr` → `data/media.csv`.")
    A("- Komentar yang dihapus/dibatasi oleh Instagram atau akun pemilik tidak ikut terambil, "
      "jadi jumlah komentar riil bisa lebih besar dari yang tercatat.")
    A("- Jumlah like bisa tersembunyi (`-1`) pada sebagian post; di laporan dihitung 0.")
    A("")
    A("### Berkas data")
    A("")
    A("- `data/posts.csv` — 1 baris per post, lengkap dengan link, like, komentar, tema.")
    A("- `data/comments.csv` — 1 baris per komentar/balasan, lengkap dengan sentimen & tema.")
    A("- `data/media.csv` — link foto/video per post.")
    A("- `data/summary.json` — angka ringkas versi mesin.")
    A("")

    with open("laporan.md", "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))

    print(f"post: {len(posts)} | komentar: {len(comments)} | komentator unik: {len(commenters)}")
    print("tulis: data/posts.csv, data/comments.csv, data/summary.json, laporan.md")


if __name__ == "__main__":
    main()
