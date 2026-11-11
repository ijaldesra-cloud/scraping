/**
 * Resolver link media Instagram memakai @coflyn/scrapr.
 *
 * Membaca data/posts.jsonl (hasil collect.py), lalu untuk setiap post sejak
 * tanggal pisah sambut mengambil URL foto/video langsung lewat scrapr.
 * Hasil ditulis ke data/media.csv dan resumable (data/media_done.json).
 *
 * Pemakaian:
 *   node resolve_media.js
 *   node resolve_media.js --since 2026-10-01
 *   node resolve_media.js --limit 20
 */

const fs = require("fs");
const path = require("path");
const axios = require("axios");

// Tanpa timeout, satu post yang menggantung bisa menahan seluruh antrean.
axios.defaults.timeout = 15000;

const { instagram } = require("@coflyn/scrapr");

const DATA = "data";
const POSTS = path.join(DATA, "posts.jsonl");
const OUT = path.join(DATA, "media.csv");
const DONE = path.join(DATA, "media_done.json");

const args = process.argv.slice(2);
const argOf = (name) => {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : null;
};
const LIMIT = argOf("--limit") ? Number(argOf("--limit")) : Infinity;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// indown paling cepat & paling stabil untuk post publik; direct hanya untuk
// post yang embed-nya masih menyimpan media.
const CHAIN = [
  ["indown", instagram.indown],
  ["direct", instagram.direct],
  ["snapsave", instagram.snapsave],
];

function readJsonl(file) {
  return fs
    .readFileSync(file, "utf8")
    .split("\n")
    .filter((l) => l.trim())
    .map((l) => JSON.parse(l));
}

function anchorDate(posts) {
  const explicit = argOf("--since");
  if (explicit) return explicit;
  const cache = path.join(DATA, "anchor.json");
  if (fs.existsSync(cache)) return JSON.parse(fs.readFileSync(cache, "utf8")).date;
  throw new Error("data/anchor.json belum ada. Jalankan collect.py dulu atau pakai --since.");
}

async function resolve(url) {
  for (const [name, fn] of CHAIN) {
    try {
      const res = await fn(url);
      if (res && res.status && res.result && (res.result.downloads || []).length) {
        return { source: name, downloads: res.result.downloads, title: res.result.title || "" };
      }
    } catch (err) {
      // lanjut ke sumber berikutnya
    }
  }
  return null;
}

(async () => {
  if (!fs.existsSync(POSTS)) throw new Error(`${POSTS} tidak ada, jalankan collect.py dulu`);
  const posts = readJsonl(POSTS);
  const since = anchorDate(posts);

  const done = fs.existsSync(DONE) ? new Set(JSON.parse(fs.readFileSync(DONE, "utf8"))) : new Set();
  const targets = posts
    .filter((p) => p.date_utc >= since)
    .sort((a, b) => (a.date_utc < b.date_utc ? -1 : 1))
    .filter((p) => !done.has(p.shortcode));

  const total = posts.filter((p) => p.date_utc >= since).length;
  console.log(`sejak ${since.slice(0, 10)}: ${total} post, ${targets.length} belum di-resolve`);

  if (!fs.existsSync(OUT)) {
    fs.writeFileSync(OUT, "shortcode,post_url,post_date,media_index,media_type,quality,media_url,source\n", "utf8");
  }

  let n = 0;
  let failed = 0;
  for (const post of targets) {
    if (n >= LIMIT) break;

    // Ambil URL dari instaloader kalau scrapr gagal.
    let rows = [];

    if (post.media && post.media.length) {
      post.media.forEach((m, idx) => {
        rows.push({
          index: idx,
          type: m.type,
          quality: "",
          url: m.url,
          source: "instaloader",
        });
      });
    }

    const res = await resolve(post.url);
    if (res) {
      rows = res.downloads.map((d, idx) => ({
        index: idx,
        type: d.type || (post.is_video ? "video" : "image"),
        quality: d.quality || "",
        url: d.url,
        source: res.source,
      }));
    } else {
      failed += 1;
      if (!rows.length) console.log(`  ! ${post.shortcode} tidak dapat media dari scrapr`);
    }

    const lines = rows
      .map((r) =>
        [
          post.shortcode,
          post.url,
          post.date_utc.slice(0, 10),
          r.index,
          r.type,
          r.quality,
          `"${String(r.url).replace(/"/g, '""')}"`,
          r.source,
        ].join(","),
      )
      .join("\n");

    if (lines) fs.appendFileSync(OUT, lines + "\n", "utf8");
    done.add(post.shortcode);
    fs.writeFileSync(DONE, JSON.stringify([...done]), "utf8");

    n += 1;
    if (n % 10 === 0) console.log(`  ${n}/${targets.length} post | terakhir ${post.date_utc.slice(0, 10)}`);
    await sleep(350);
  }

  console.log(`selesai: ${n} post diproses, ${done.size} total tersimpan, ${failed} gagal resolve`);
})().catch((err) => {
  console.error("ERROR:", err.message);
  process.exit(1);
});
