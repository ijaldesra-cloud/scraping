"""Penilai sentimen sederhana untuk komentar bahasa Indonesia (termasuk slang).

Bukan model ML: hanya kamus kata + penanganan negasi + emoji. Cukup untuk
membaca arah umum respon, dan hasilnya tetap bisa diverifikasi manual di
data/comments.csv.
"""

from __future__ import annotations

import re

POSITIVE = {
    "mantap", "mantab", "mantul", "keren", "bagus", "baik", "hebat", "salut",
    "sukses", "semangat", "bangga", "apresiasi", "dukung", "mendukung",
    "makasih", "terimakasih", "thanks", "thankyou", "alhamdulillah", "syukur",
    "aman", "nyaman", "tertib", "disiplin", "sigap", "peduli", "bermanfaat",
    "membantu", "luarbiasa", "joss", "jos", "sip", "oke", "ok", "setuju",
    "lanjutkan", "pertahankan", "inspiratif", "teladan", "profesional",
    "humanis", "kekeluargaan", "guyub", "rukun", "damai", "sehat", "berkah",
    "maju", "jaya", "selamat", "congratulations", "love", "nice", "good",
    "great", "best", "proud", "respect", "top", "solid", "cepat", "sigapp",
    "membanggakan", "kerennya", "jempol", "apresiasi", "cakep", "asik", "asyik",
    "seru", "kompak", "sopan", "ramah", "bijak", "adil", "transparan",
}

NEGATIVE = {
    "kecewa", "mengecewakan", "parah", "buruk", "jelek", "gagal", "bohong",
    "bohongin", "tipu", "nipu", "penipuan", "pencitraan", "arogan", "sombong",
    "pungli", "korupsi", "korup", "mafia", "tebangpilih", "capek", "cape",
    "males", "malas", "bosan", "jengkel", "kesal", "marah", "benci", "ogah",
    "sia-sia", "mubazir", "boros", "lambat", "lama", "ribet", "berbelit",
    "hoaks", "hoax", "provokasi", "fitnah", "salah", "keliru", "becus",
    "sembarangan", "seenaknya", "reseh", "norak", "tolol", "bodoh", "goblok",
    "dongo", "kampret", "bangsat", "anjir", "anjay", "sampah", "payah",
    "ngecewain", "nyesel", "rugi", "diskriminasi", "represif", "kasar",
    "tidakadil", "gakadil", "nggakadil", "gakbecus", "tidakbecus",
}

# Frasa dua kata yang lebih akurat daripada kata tunggal.
POSITIVE_PHRASES = {
    "terima kasih", "makasih banyak", "luar biasa", "lanjutkan pak", "tetap semangat",
    "semoga sukses", "selamat bertugas", "selamat datang", "selamat menjalankan",
    "sukses selalu", "sehat selalu", "bekerja dengan baik", "pertahankan pak",
}

NEGATIVE_PHRASES = {
    "tidak percaya", "gak percaya", "nggak percaya", "tidak profesional",
    "tidak adil", "gak adil", "nggak adil", "asal-asalan", "tebar pesona",
    "hanya pencitraan", "cuma pencitraan", "tidak becus", "gak becus",
    "semoga ditindak", "harus ditindak", "kok bisa", "tidak tegas", "gak tegas",
}

NEGATORS = {"tidak", "tak", "gak", "nggak", "enggak", "bukan", "belum", "jangan", "tanpa"}

POS_EMOJI = {"😍", "🥰", "❤️", "❤", "🙏", "👏", "👍", "🔥", "💪", "😊", "🤩", "😁", "🥳", "✅"}
NEG_EMOJI = {"😡", "😠", "👎", "🤬", "😤", "🙄", "😑", "😒", "💩", "❌", "🚫"}

LABEL_ID = {
    "sangat positif": "Sangat positif",
    "positif": "Positif",
    "netral": "Netral",
    "negatif": "Negatif",
    "sangat negatif": "Sangat negatif",
}

WORD_RE = re.compile(r"[\w@#]+", re.UNICODE)


def _normalize_token(tok: str) -> str:
    tok = tok.lower().strip("@#")
    return re.sub(r"(.)\1{2,}", r"\1\1", tok)  # mantappp -> mantapp


def score(text: str) -> tuple[str, int]:
    """Kembalikan (label, skor) untuk satu komentar."""
    if not text:
        return "netral", 0

    low = re.sub(r"\s+", " ", text.lower())
    total = 0

    for phrase, val in ((p, 1) for p in POSITIVE_PHRASES):
        if phrase in low:
            total += val
    for phrase in NEGATIVE_PHRASES:
        if phrase in low:
            total -= 1

    tokens = [_normalize_token(t) for t in WORD_RE.findall(low)]
    negate_for = 0
    for tok in tokens:
        if tok in NEGATORS:
            negate_for = 2
            continue
        if tok in POSITIVE:
            total += -1 if negate_for else 1
        elif tok in NEGATIVE:
            total += 1 if negate_for else -1
        if negate_for:
            negate_for -= 1

    total += sum(1 for ch in text if ch in POS_EMOJI)
    total -= sum(1 for ch in text if ch in NEG_EMOJI)

    if total >= 2:
        return "sangat positif", total
    if total == 1:
        return "positif", total
    if total == 0:
        return "netral", 0
    if total == -1:
        return "negatif", total
    return "sangat negatif", total
