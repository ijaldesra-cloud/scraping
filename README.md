# Scraping IG @humas.polrespurwakarta — pasca pisah sambut Kapolres

Mengambil **post + komentar** akun Instagram publik `humas.polrespurwakarta`
sejak **29 Juli 2026** (sertijab/pisah sambut Kapolres Purwakarta dari
AKBP I Dewa Putu Gede Anom Danujaya ke AKBP Febri Nurzam) sampai hari ini,
lalu menyusunnya jadi data terstruktur + laporan respon publik.

## Isi project

| Berkas | Fungsi |
| --- | --- |
| `collect.py` | Ambil semua post + komentar (resumable, retry otomatis) |
| `resolve_media.js` | Resolve link foto/video tiap post pakai `@coflyn/scrapr` |
| `analyze.py` | Hitung metrik, sentimen, tema → CSV + `laporan.md` |
| `build_dashboard.py` | Agregasi data → `web/data.js` untuk dashboard |
| `web/` | Dashboard EDA (HTML + CSS + JS murni, tanpa library) + PWA |
| `api/scrape.py` | Endpoint `POST /api/scrape`: 1 link post → CSV post & komentar |
| `vercel.json` | Konfigurasi deploy Vercel (static `web/` + Python function) |
| `make_session.py` | Bikin file session instaloader dari cookie `sessionid` |
| `sentiment.py` | Kamus sentimen bahasa Indonesia |
| `config.py` | Username, tanggal mulai (29 Juli 2026), jeda request |

## Setup

```bash
python -m venv .venv
.venv/Scripts/python -m pip install instaloader
npm install
```

## Login (sangat disarankan)

Tanpa login, Instagram hanya memberi **kode post** per halaman sehingga butuh
1 request per post — untuk ±380 post + komentarnya itu 700+ request dan
hampir pasti diblokir. Dengan login, metadata post datang per halaman
(10–30 request total) dan komentar lebih stabil.

Pilih salah satu:

**A. Login lewat terminal sendiri (password tidak masuk chat)**

```bash
.venv/Scripts/instaloader --login humas.polrespurwakarta
# masukkan password + kode 2FA kalau diminta
```

**B. Pakai cookie `sessionid`**

1. Login Instagram di browser → `F12` → tab **Application/Storage** →
   **Cookies** → `https://www.instagram.com` → salin nilai `sessionid`.
2. Jalankan:
   ```bash
   .venv/Scripts/python make_session.py
   ```
3. Tempel cookie saat diminta (input tersembunyi).

Session tersimpan di `data/session-humas`. Perlakukan seperti password.
`collect.py` otomatis memakainya kalau ada. Untuk mencabut akses: logout
Instagram di perangkat tersebut.

> Disarankan memakai akun Instagram sekunder, bukan akun utama.

## Menjalankan

```bash
.venv/Scripts/python collect.py        # post + komentar  (bisa diulang, resume)
node resolve_media.js                  # link foto/video via scrapr
.venv/Scripts/python analyze.py        # metrik + laporan
```

Kalau `collect.py` terputus, jalankan ulang perintah yang sama — progres
tersimpan dan akan lanjut dari cursor terakhir.

## Output

| Berkas | Isi |
| --- | --- |
| `data/posts.csv` | 1 baris per post: tanggal, link, like, jumlah komentar, tema |
| `web/data.js` | data agregat khusus dashboard (dibuat `build_dashboard.py`) |
| `data/comments.csv` | 1 baris per komentar: penulis, teks, waktu, like, sentimen, tema |
| `data/media.csv` | link foto/video per post (hasil scrapr) |
| `data/summary.json` | angka ringkas untuk dipakai ulang |
| `laporan.md` | laporan naratif: angka kunci, sentimen, tema, top post/komentar |
| `web/index.html` | dashboard EDA interaktif (buka langsung di browser) |

## Dashboard visualisasi

```bash
.venv/Scripts/python build_dashboard.py   # regenerasi web/data.js
```

Lalu buka `web/index.html` di browser (klik dua kali, tidak perlu server).

Dashboard juga bisa dipasang sebagai aplikasi (PWA): ada `manifest.webmanifest`,
service worker `web/sw.js` yang menyimpan app shell untuk offline, serta tombol
**Pasang aplikasi** di header saat browser mendukung. Registrasi service worker
hanya jalan lewat `http(s)` (Vercel atau server lokal), bukan `file://`.
Isinya: kartu KPI, tren like/komentar per minggu, volume per bulan, histogram
like, donut sentimen, tema komentar, frasa teratas, scatter like vs komentar,
pola jam dan hari posting, serta tabel 12 post dan 30 komentar teratas.
Semua grafik digambar dengan SVG murni — tanpa Chart.js atau CDN.

**8 kartu KPI bisa diklik** dan membuka panel detail:

| Kartu | Isi panel |
| --- | --- |
| Total post | 15 post terbaru + tautan CSV |
| Total like | 10 post like tertinggi |
| Komentar (IG) | 12 post dengan komentar terbanyak |
| Komentar ditarik | rincian sentimen + alasan tidak 100% |
| Komentator unik | 20 akun paling aktif |
| Rata-rata like | sebaran like per rentang |
| Median like | 10 post paling sedikit like |
| Link media | jumlah foto/video + post bermedia terbanyak |

Panel ditutup dengan tombol ×, klik latar, atau tombol Esc.

## Ambil CSV dari satu link post

Di dashboard ada form **Ambil CSV dari link post**: tempel URL post/reel Instagram
publik, lalu server mengambil metadata post, link media, dan komentarnya, memberi
sentimen, dan mengirim CSV siap unduh (post + komentar).

Endpoint-nya ada di `api/scrape.py`:

```
POST /api/scrape
Content-Type: application/json

{"url": "https://www.instagram.com/p/SHORTCODE/"}
```

Balasannya JSON `{ok, shortcode, date, likes, comment_count, comments_fetched,
media, sentiment, csv: {post, comments}}`. Tanpa `IG_SESSIONID` Instagram hampir
selalu menolak permintaan anonim, jadi set env var dulu (lihat bawah).

Jalankan lokal tanpa Vercel:

```bash
.venv/Scripts/python api/scrape.py     # http://127.0.0.1:8000/api/scrape
# atau, kalau CLI Vercel sudah terpasang:
vercel dev
```

Form di dashboard memanggil `api/scrape` relatif terhadap halaman, jadi saat
menguji dengan `python api/scrape.py` langsung (port 8000) dashboard harus dibuka
lewat server yang sama origin-nya — cara paling mudah: `vercel dev`.

## Deploy ke Vercel

1. Import repo ini di Vercel (framework preset: **Other**). Tidak perlu build
   command; `vercel.json` sudah menyajikan `web/` sebagai static dan
   `api/scrape.py` sebagai Python function (maks. 60 detik).
2. Isi **Environment Variables** di project settings:

   | Nama | Wajib | Isi |
   | --- | --- | --- |
   | `IG_USERNAME` | disarankan | akun Instagram yang dipakai |
   | `IG_SESSIONID` | disarankan | nilai cookie `sessionid` akun itu |
   | `IG_CSRFTOKEN` | opsional | cookie `csrftoken` (kadang diperlukan) |
   | `ALLOW_ORIGIN` | opsional | default `*`; batasi ke domain dashboard bila perlu |

   Cookie diambil seperti di bagian **Login** di atas. Perlakukan seperti
   password: jangan commit, jangan taruh di `web/`. Pakai akun sekunder.
3. Deploy, lalu buka `https://<project>.vercel.app/`. Dashboard + PWA jalan dari
   root, API dari `/api/scrape`.

Catatan: `data/*.csv`, `data/*.jsonl`, dan file session di-ignore git sehingga
**tidak ikut ter-deploy**; tautan CSV arsip di panel KPI hanya ada di mesin lokal.
Fitur "Ambil CSV dari link" tidak bergantung pada file arsip itu.

## Batasan yang perlu diketahui

- Instagram tidak menampilkan komentar yang dihapus/dibatasi, dan some posts
  menyembunyikan jumlah like (`-1`, dihitung 0).
- Sentimen memakai kamus kata + negasi sederhana, bukan model ML. Selalu bisa
  diverifikasi di `data/comments.csv`.
- Balasan komentar ikut diambil; untuk melewatinya pakai `--no-replies`.
- Scraping publik tetap tunduk pada ToS Instagram. Gunakan secukupnya,
  jangan untuk pembuatan konten otomatis atau profiling individu.
- Endpoint `/api/scrape` membatasi komentar yang diambil (maks. 250, balasan
  maks. 5 per komentar) dan punya jeda 10 detik per IP per instance, supaya
  tidak melewati batas waktu function dan tidak dipakai berlebihan.
