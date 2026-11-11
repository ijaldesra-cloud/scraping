/* Dashboard EDA — render semua grafik pakai SVG murni, tanpa library. */
(function () {
  "use strict";

  const D = window.DASH_DATA;
  if (!D) return;

  const NS = "http://www.w3.org/2000/svg";
  const C = {
    pink: "#f0568a",
    blue: "#4da3ff",
    green: "#38c172",
    red: "#e04f5f",
    grey: "#7b8798",
    grid: "#262d38",
    text: "#93a0b4",
  };
  const nf = new Intl.NumberFormat("id-ID");

  const fmt = (n) => nf.format(Math.round(n));
  const fmt1 = (n) => nf.format(Math.round(n * 10) / 10);

  /* ---------------- helper ---------------- */
  function s(tag, attrs, parent) {
    const node = document.createElementNS(NS, tag);
    for (const k in attrs) node.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(node);
    return node;
  }

  function canvas(host, height, width) {
    const W = width || 720;
    const H = height || 320;
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "xMidYMid meet" });
    host.innerHTML = "";
    host.appendChild(svg);
    return { svg, W, H };
  }

  function niceMax(v) {
    if (v <= 0) return 10;
    const mag = Math.pow(10, Math.floor(Math.log10(v)));
    const n = v / mag;
    const step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
    return step * mag;
  }

  /* ---------------- tooltip ---------------- */
  let tipEl = null;
  function tip(node, htmlFn) {
    node.style.cursor = "default";
    node.addEventListener("mouseenter", (e) => {
      if (!tipEl) {
        tipEl = document.createElement("div");
        tipEl.id = "tip";
        document.body.appendChild(tipEl);
      }
      tipEl.innerHTML = htmlFn();
      tipEl.classList.add("on");
      move(e);
    });
    node.addEventListener("mousemove", move);
    node.addEventListener("mouseleave", () => tipEl && tipEl.classList.remove("on"));
    function move(e) {
      if (!tipEl) return;
      tipEl.style.left = e.clientX + "px";
      tipEl.style.top = e.clientY + "px";
    }
  }

  /* ---------------- KPI ---------------- */
  function renderKpi() {
    const m = D.meta;
    const cards = [
      { key: "posts", label: "Total post", value: fmt(m.posts), hint: `${m.post_berkomentar} post punya komentar` },
      { key: "likes", label: "Total like", value: fmt(m.likes), hint: `rata-rata ${fmt(m.avg_likes)}/post` },
      { key: "comments_ig", label: "Komentar (IG)", value: fmt(m.komentar_meta), hint: "angka yang tampil di post" },
      { key: "comments_got", label: "Komentar ditarik", value: fmt(m.komentar_ditarik), hint: "berhasil di-scrape" },
      { key: "commenters", label: "Komentator unik", value: fmt(m.komentator), hint: "akun berbeda" },
      { key: "avg_likes", label: "Rata-rata like", value: fmt(m.avg_likes), hint: "per post" },
      { key: "median_likes", label: "Median like", value: fmt(m.median_likes), hint: "setengah post di bawah ini" },
      { key: "media", label: "Link media", value: fmt(m.media), hint: "foto & video" },
    ];
    const host = document.getElementById("kpi");
    host.innerHTML = cards
      .map(
        (c) => `<div class="kpi" role="button" tabindex="0" data-key="${c.key}"
          title="Klik untuk lihat detail" aria-label="Lihat detail ${c.label}">
          <div class="label">${c.label}</div>
          <div class="value">${c.value}</div>
          <div class="hint">${c.hint}</div>
        </div>`
      )
      .join("");

    host.querySelectorAll(".kpi").forEach((el) => {
      const open = () => showDetail(el.dataset.key);
      el.addEventListener("click", open);
      el.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          open();
        }
      });
    });
  }

  /* ---------------- modal & detail KPI ---------------- */
  function escapeHtml(str) {
    return String(str).replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[ch]));
  }

  function statBoxes(pairs) {
    return `<div class="stat-row">${pairs
      .map(([k, v]) => `<div class="stat-box"><div class="k">${k}</div><div class="v">${v}</div></div>`)
      .join("")}</div>`;
  }

  function table(head, rows) {
    return `<div class="table-wrap"><table><thead><tr>${head
      .map((h) => (typeof h === "string" ? `<th>${h}</th>` : `<th class="${h.cls}">${h.label}</th>`))
      .join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
  }

  function closeModal() {
    const modal = document.getElementById("modal");
    modal.hidden = true;
    document.body.style.overflow = "";
  }

  function openModal(title, sub, body) {
    document.getElementById("modal-title").textContent = title;
    document.getElementById("modal-sub").textContent = sub;
    document.getElementById("modal-body").innerHTML = body;
    const modal = document.getElementById("modal");
    modal.hidden = false;
    document.body.style.overflow = "hidden";
    modal.querySelector(".modal-panel").scrollTop = 0;
  }

  function postRows(list) {
    return list.map(
      (p) => `<tr>
        <td>${p.d}</td>
        <td class="num">${fmt(p.l)}</td>
        <td class="num">${fmt(p.c)}</td>
        <td><a href="${p.u}" target="_blank" rel="noopener">buka</a></td>
      </tr>`
    );
  }

  const DETAIL = {
    posts() {
      const m = D.meta;
      const weeks = D.weekly.length;
      return {
        title: "Total post",
        sub: `${fmt(m.posts)} post dipublikasikan antara ${m.dari} dan ${m.sampai}.`,
        body:
          statBoxes([
            ["Total post", fmt(m.posts)],
            ["Punya komentar", fmt(m.post_berkomentar)],
            ["Rata-rata/minggu", fmt(m.posts / weeks)],
            ["Hari terpantau", String(new Set(D.daily.map((d) => d.date)).size)],
          ]) +
          `<h4>15 post terbaru</h4>` +
          table(["Tanggal", "Like", "Komentar", "Link"], postRows(D.all_posts.slice(0, 15))) +
          `<div class="modal-actions"><a class="btn-link" href="../data/posts.csv">Unduh semua 334 post (CSV)</a></div>`,
      };
    },

    likes() {
      const m = D.meta;
      const top = [...D.all_posts].sort((a, b) => b.l - a.l).slice(0, 10);
      const max = Math.max(...D.all_posts.map((p) => p.l));
      return {
        title: "Total like",
        sub: `${fmt(m.likes)} like dari ${fmt(m.posts)} post.`,
        body:
          statBoxes([
            ["Total like", fmt(m.likes)],
            ["Rata-rata", fmt(m.avg_likes)],
            ["Median", fmt(m.median_likes)],
            ["Tertinggi", fmt(max)],
          ]) +
          `<h4>10 post dengan like terbanyak</h4>` +
          table(["Tanggal", "Like", "Komentar", "Link"], postRows(top)) +
          `<div class="modal-actions"><a class="btn-link" href="../data/posts.csv">Unduh data lengkap</a></div>`,
      };
    },

    comments_ig() {
      const m = D.meta;
      return {
        title: "Komentar (metadata Instagram)",
        sub: "Jumlah komentar yang ditampilkan Instagram di tiap post.",
        body:
          statBoxes([
            ["Komentar di IG", fmt(m.komentar_meta)],
            ["Berhasil ditarik", fmt(m.komentar_ditarik)],
            ["Cakupan", `${((100 * m.komentar_ditarik) / (m.komentar_meta || 1)).toFixed(1)}%`],
            ["Rata-rata/post", fmt1(m.avg_comments)],
          ]) +
          `<h4>Post dengan komentar terbanyak</h4>` +
          table(
            ["Tanggal", "Like", "Komentar", "Link"],
            postRows([...D.all_posts].sort((a, b) => b.c - a.c).slice(0, 12))
          ) +
          `<div class="modal-actions"><a class="btn-link" href="../data/comments.csv">Unduh komentar (CSV)</a></div>`,
      };
    },

    comments_got() {
      const m = D.meta;
      const total = D.sentiment.reduce((a, b) => a + b.count, 0) || 1;
      return {
        title: "Komentar berhasil ditarik",
        sub: `${fmt(m.komentar_ditarik)} komentar ter-scrape, ${((100 * m.komentar_ditarik) / (m.komentar_meta || 1)).toFixed(1)}% dari yang tampil di IG.`,
        body:
          statBoxes(D.sentiment.map((s2) => [
            s2.label,
            `${fmt(s2.count)} · ${((100 * s2.count) / total).toFixed(1)}%`,
          ])) +
          `<h4>Kenapa tidak 100%?</h4><p style="color:#93a0b4;font-size:13px;margin:0">` +
          `Komentar yang dihapus, dibatasi, atau disembunyikan pemilik akun tidak bisa diambil. ` +
          `Balasan bersarang yang dipagari Instagram juga bisa terlewat.</p>` +
          `<div class="modal-actions"><a class="btn-link" href="../data/comments.csv">Unduh komentar (CSV)</a></div>`,
      };
    },

    commenters() {
      const m = D.meta;
      const rows = D.top_commenters.map(
        (c, i) => `<tr><td class="num">${i + 1}</td><td>@${escapeHtml(c.author)}</td><td class="num">${fmt(c.count)}</td></tr>`
      );
      return {
        title: "Komentator unik",
        sub: `${fmt(m.komentator)} akun berbeda berkomentar di periode ini.`,
        body:
          statBoxes([
            ["Akun unik", fmt(m.komentator)],
            ["Total komentar", fmt(m.komentar_ditarik)],
            ["Rata-rata/akun", fmt1(m.komentar_ditarik / (m.komentator || 1))],
            ["Akun teraktif", `@${D.top_commenters[0] ? D.top_commenters[0].author : "-"}`],
          ]) +
          `<h4>20 akun paling aktif</h4>` +
          table(["#", "Akun", "Komentar"], rows),
      };
    },

    avg_likes() {
      const m = D.meta;
      const vals = D.all_posts.map((p) => p.l);
      return {
        title: "Rata-rata like per post",
        sub: "Rata-rata mudah tertarik ke atas oleh sedikit post viral — bandingkan dengan median.",
        body:
          statBoxes([
            ["Rata-rata", fmt(m.avg_likes)],
            ["Median", fmt(m.median_likes)],
            ["Tertinggi", fmt(Math.max(...vals))],
            ["Terendah", fmt(Math.min(...vals))],
          ]) +
          `<h4>Sebaran like</h4>` +
          table(
            ["Rentang like", { label: "Jumlah post", cls: "num" }],
            D.histogram.map((h) => `<tr><td>${h.label}</td><td class="num">${fmt(h.count)}</td></tr>`)
          ),
      };
    },

    median_likes() {
      const m = D.meta;
      const below = D.all_posts.filter((p) => p.l <= m.median_likes).length;
      return {
        title: "Median like",
        sub: "Setengah post mendapat like di bawah angka ini.",
        body:
          statBoxes([
            ["Median", fmt(m.median_likes)],
            ["Rata-rata", fmt(m.avg_likes)],
            ["Post ≤ median", fmt(below)],
            ["Selisih rata²−median", fmt(m.avg_likes - m.median_likes)],
          ]) +
          `<h4>10 post paling sedikit like</h4>` +
          table(
            ["Tanggal", "Like", "Komentar", "Link"],
            postRows([...D.all_posts].sort((a, b) => a.l - b.l).slice(0, 10))
          ),
      };
    },

    media() {
      const m = D.meta;
      const top = [...D.all_posts].filter((p) => p.m > 0).sort((a, b) => b.m - a.m).slice(0, 12);
      const jenis = (D.media_types || []).map((t) => [
        t.type === "image" ? "Foto" : t.type === "video" ? "Video" : t.type,
        fmt(t.count),
      ]);
      return {
        title: "Link media",
        sub: "URL foto dan video yang berhasil di-resolve lewat @coflyn/scrapr.",
        body:
          statBoxes([["Total link", fmt(m.media)], ...jenis]) +
          `<h4>Post dengan media terbanyak</h4>` +
          table(
            ["Tanggal", { label: "Media", cls: "num" }, "Link"],
            top.map((p) => `<tr><td>${p.d}</td><td class="num">${fmt(p.m)}</td><td><a href="${p.u}" target="_blank" rel="noopener">buka</a></td></tr>`)
          ) +
          `<div class="modal-actions"><a class="btn-link" href="../data/media.csv">Buka daftar lengkap (CSV)</a></div>`,
      };
    },
  };

  function showDetail(key) {
    const builder = DETAIL[key];
    if (!builder) return;
    const d = builder();
    openModal(d.title, d.sub, d.body);
  }

  /* ---------------- line ---------------- */
  function lineChart(host, rows, key, color, label, xKey) {
    const { svg, W, H } = canvas(host);
    const P = { l: 56, r: 16, t: 16, b: 36 };
    const iw = W - P.l - P.r;
    const ih = H - P.t - P.b;
    const yMax = niceMax(Math.max(1, ...rows.map((r) => r[key])));
    const X = (i) => P.l + (rows.length === 1 ? iw / 2 : (iw * i) / (rows.length - 1));
    const Y = (v) => P.t + ih - (v / yMax) * ih;

    for (let t = 0; t <= 4; t++) {
      const val = (yMax * t) / 4;
      const yy = Y(val);
      s("line", { x1: P.l, y1: yy, x2: P.l + iw, y2: yy, stroke: C.grid, "stroke-width": 1 }, svg);
      s("text", { x: P.l - 10, y: yy + 4, "text-anchor": "end", fill: C.text, "font-size": 11 }, svg)
        .textContent = fmt(val);
    }

    const pts = rows.map((r, i) => [X(i), Y(r[key])]);
    const d = pts.map((p, i) => (i ? "L" : "M") + p[0] + " " + p[1]).join(" ");
    s("path", {
      d: `${d} L ${pts[pts.length - 1][0]} ${P.t + ih} L ${pts[0][0]} ${P.t + ih} Z`,
      fill: color,
      opacity: ".12",
    }, svg);
    s("path", { d, fill: "none", stroke: color, "stroke-width": 2.4, "stroke-linejoin": "round" }, svg);

    pts.forEach(([cx, cy], i) => {
      const dot = s("circle", { cx, cy, r: 4, fill: "#0e1116", stroke: color, "stroke-width": 2 }, svg);
      tip(dot, () => `<b>${rows[i][xKey]}</b><br>${label}: ${fmt(rows[i][key])}<br>Post: ${fmt(rows[i].posts)}`);
    });

    const step = Math.ceil(rows.length / 7);
    rows.forEach((r, i) => {
      if (i % step !== 0 && i !== rows.length - 1) return;
      s("text", {
        x: X(i), y: H - 14, "text-anchor": "middle", fill: C.text, "font-size": 10.5,
      }, svg).textContent = r[xKey].replace("2026-", "");
    });
  }

  /* ---------------- vertical bars ---------------- */
  function barChart(host, items, color, labelOf, valueOf, titleOf, labelEvery) {
    const { svg, W, H } = canvas(host, 300);
    const P = { l: 56, r: 16, t: 18, b: 42 };
    const iw = W - P.l - P.r;
    const ih = H - P.t - P.b;
    const max = niceMax(Math.max(1, ...items.map(valueOf)));
    const bw = iw / items.length;

    for (let t = 0; t <= 4; t++) {
      const val = (max * t) / 4;
      const yy = P.t + ih - (val / max) * ih;
      s("line", { x1: P.l, y1: yy, x2: P.l + iw, y2: yy, stroke: C.grid }, svg);
      s("text", { x: P.l - 10, y: yy + 4, "text-anchor": "end", fill: C.text, "font-size": 11 }, svg)
        .textContent = fmt(val);
    }

    items.forEach((it, i) => {
      const v = valueOf(it);
      const h = (v / max) * ih;
      const x = P.l + i * bw + bw * 0.18;
      const w = bw * 0.64;
      const rect = s("rect", {
        x, y: P.t + ih - h, width: w, height: Math.max(h, 1), rx: 3, fill: color, opacity: ".85",
      }, svg);
      tip(rect, () => `<b>${labelOf(it)}</b><br>${titleOf || labelOf(it)}: ${fmt(v)}`);
      if (labelEvery && i % labelEvery !== 0) return;
      s("text", {
        x: x + w / 2, y: H - 16, "text-anchor": "middle", fill: C.text, "font-size": 10.5,
      }, svg).textContent = labelOf(it);
    });
  }

  /* ---------------- horizontal bars ---------------- */
  function hBarChart(host, items, color, labelOf, valueOf) {
    const rowH = 27;
    const H = items.length * rowH + 12;
    const { svg, W } = canvas(host, H, 400);
    const labelW = 148;
    const iw = W - labelW - 52;
    const max = Math.max(1, ...items.map(valueOf));

    items.forEach((it, i) => {
      const y = i * rowH + 6;
      const w = Math.max((valueOf(it) / max) * iw, 3);
      const name = labelOf(it);
      s("text", {
        x: labelW - 10, y: y + 13, "text-anchor": "end", fill: "#c8d2e0", "font-size": 10.5,
      }, svg).textContent = name.length > 24 ? name.slice(0, 23) + "…" : name;

      s("rect", { x: labelW, y: y + 3, width: iw, height: 13, rx: 6.5, fill: "#222a35" }, svg);
      const bar = s("rect", { x: labelW, y: y + 3, width: w, height: 13, rx: 6.5, fill: color }, svg);
      tip(bar, () => `<b>${name}</b><br>${fmt(valueOf(it))}`);

      s("text", {
        x: labelW + w + 7, y: y + 13, fill: C.text, "font-size": 10.5,
      }, svg).textContent = fmt(valueOf(it));
    });
  }

  /* ---------------- donut ---------------- */
  function donutChart(host, items, colors) {
    const { svg, W } = canvas(host, 220, 300);
    const cx = W / 2;
    const cy = 108;
    const r = 82;
    const inner = 52;
    const total = items.reduce((a, b) => a + b.count, 0) || 1;
    let angle = -Math.PI / 2;

    items.forEach((it, i) => {
      const slice = (it.count / total) * Math.PI * 2;
      const end = angle + slice;
      const large = slice > Math.PI ? 1 : 0;
      const p = (rad, a) => [cx + rad * Math.cos(a), cy + rad * Math.sin(a)];
      const [x1, y1] = p(r, angle);
      const [x2, y2] = p(r, end);
      const [x3, y3] = p(inner, end);
      const [x4, y4] = p(inner, angle);
      const path = s("path", {
        d: `M ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} L ${x3} ${y3} A ${inner} ${inner} 0 ${large} 0 ${x4} ${y4} Z`,
        fill: colors[i % colors.length],
        opacity: ".9",
        stroke: "#161b23",
        "stroke-width": 2,
      }, svg);
      tip(path, () => `<b>${it.label}</b><br>${fmt(it.count)} (${((100 * it.count) / total).toFixed(1)}%)`);
      angle = end;
    });

    s("text", {
      x: cx, y: cy + 2, "text-anchor": "middle", fill: "#e8edf5", "font-size": 21, "font-weight": 700,
    }, svg).textContent = fmt(total);
    s("text", {
      x: cx, y: cy + 20, "text-anchor": "middle", fill: C.text, "font-size": 10.5,
    }, svg).textContent = "total";
  }

  function legend(host, items, colors) {
    host.innerHTML = items
      .map(
        (it, i) =>
          `<li><span class="swatch" style="background:${colors[i % colors.length]}"></span>
           ${it.label} <b>${fmt(it.count)}</b></li>`
      )
      .join("");
  }

  /* ---------------- scatter ---------------- */
  function scatterChart(host, points) {
    const { svg, W, H } = canvas(host, 340);
    const P = { l: 56, r: 18, t: 18, b: 40 };
    const iw = W - P.l - P.r;
    const ih = H - P.t - P.b;
    const xMax = niceMax(Math.max(...points.map((p) => p.likes)));
    const yMax = niceMax(Math.max(...points.map((p) => p.comments)));
    const X = (v) => P.l + (v / xMax) * iw;
    const Y = (v) => P.t + ih - (v / yMax) * ih;

    for (let t = 0; t <= 4; t++) {
      const yy = P.t + ih - (ih * t) / 4;
      s("line", { x1: P.l, y1: yy, x2: P.l + iw, y2: yy, stroke: C.grid }, svg);
      s("text", { x: P.l - 10, y: yy + 4, "text-anchor": "end", fill: C.text, "font-size": 11 }, svg)
        .textContent = fmt((yMax * t) / 4);
      const xx = P.l + (iw * t) / 4;
      s("text", { x: xx, y: H - 16, "text-anchor": "middle", fill: C.text, "font-size": 11 }, svg)
        .textContent = fmt((xMax * t) / 4);
    }

    const avgX = points.reduce((a, p) => a + p.likes, 0) / points.length;
    const avgY = points.reduce((a, p) => a + p.comments, 0) / points.length;
    s("line", { x1: X(avgX), y1: P.t, x2: X(avgX), y2: P.t + ih, stroke: C.pink, "stroke-dasharray": "4 5", opacity: ".5" }, svg);
    s("line", { x1: P.l, y1: Y(avgY), x2: P.l + iw, y2: Y(avgY), stroke: C.pink, "stroke-dasharray": "4 5", opacity: ".5" }, svg);

    points.forEach((p) => {
      const dot = s("circle", {
        cx: X(p.likes), cy: Y(p.comments), r: 4, fill: C.blue, opacity: ".55",
      }, svg);
      tip(dot, () => `<b>${p.date}</b><br>${fmt(p.likes)} like · ${fmt(p.comments)} komentar<br>${p.url}`);
    });

    s("text", {
      x: P.l + iw / 2, y: H - 2, "text-anchor": "middle", fill: C.text, "font-size": 11,
    }, svg).textContent = "like per post";
    s("text", {
      x: 12, y: P.t + ih / 2, "text-anchor": "middle", fill: C.text, "font-size": 11,
      transform: `rotate(-90 12 ${P.t + ih / 2})`,
    }, svg).textContent = "komentar";
  }

  /* ---------------- tables ---------------- */
  function renderPosts() {
    const tb = document.querySelector("#table-posts tbody");
    tb.innerHTML = D.top_posts
      .map(
        (p) => `<tr>
          <td>${p.date}</td>
          <td class="num">${fmt(p.likes)}</td>
          <td class="num">${fmt(p.comments)}</td>
          <td>${escapeHtml(p.caption)}${p.themes.length ? `<br><span class="pill neu">${p.themes.join(" · ")}</span>` : ""}</td>
          <td><a href="${p.url}" target="_blank" rel="noopener">buka</a></td>
        </tr>`
      )
      .join("");
  }

  function renderComments() {
    const tb = document.querySelector("#table-comments tbody");
    tb.innerHTML = D.top_comments
      .map((c) => {
        const cls = c.sentiment.includes("positif") ? "pos" : c.sentiment.includes("negatif") ? "neg" : "neu";
        return `<tr>
          <td class="num">${fmt(c.likes)}</td>
          <td>@${escapeHtml(c.author)}</td>
          <td>${escapeHtml(c.text)}</td>
          <td><span class="pill ${cls}">${c.sentiment}</span></td>
          <td><a href="${c.url}" target="_blank" rel="noopener">lihat</a></td>
        </tr>`;
      })
      .join("");
  }

  /* ---------------- boot ---------------- */
  function init() {
    const m = D.meta;
    const akunEl = document.getElementById("akun");
    if (akunEl) akunEl.textContent = m.akun ? "@" + m.akun : "";
    document.getElementById("periode").textContent =
      `${m.dari} → ${m.sampai} · ${fmt(m.posts)} post · ${fmt(m.likes)} like · ${fmt(m.komentar_ditarik)} komentar`;
    document.getElementById("generated").textContent =
      `Sumber: @${m.akun} · dibuat ${new Date().toLocaleString("id-ID")}`;

    renderKpi();

    lineChart(document.getElementById("chart-likes"), D.weekly, "likes", C.pink, "Like", "week");
    lineChart(document.getElementById("chart-comments"), D.weekly, "comments", C.blue, "Komentar", "week");

    barChart(
      document.getElementById("chart-monthly"),
      D.monthly,
      C.pink,
      (m2) => m2.month,
      (m2) => m2.posts,
      "Post"
    );

    barChart(
      document.getElementById("chart-hist"),
      D.histogram,
      C.blue,
      (b) => b.label,
      (b) => b.count,
      "Jumlah post"
    );

    const sentColors = [C.grey, C.green, "#6ddb9a", "#ff8593", C.red];
    const sent = D.sentiment.map((s2) => ({
      label: s2.label.replace(/^./, (c) => c.toUpperCase()),
      count: s2.count,
    }));
    donutChart(document.getElementById("chart-sentiment"), sent, sentColors);
    legend(document.getElementById("legend-sentiment"), sent, sentColors);

    hBarChart(
      document.getElementById("chart-themes"),
      D.themes,
      C.pink,
      (t) => t.name,
      (t) => t.count
    );

    hBarChart(
      document.getElementById("chart-phrases"),
      D.phrases,
      C.blue,
      (p) => p.phrase,
      (p) => p.count
    );

    scatterChart(document.getElementById("chart-scatter"), D.scatter);

    barChart(
      document.getElementById("chart-hour"),
      D.hour,
      "#8b7bf0",
      (h) => String(h.hour).padStart(2, "0"),
      (h) => h.count,
      "Post",
      2
    );

    barChart(
      document.getElementById("chart-dow"),
      D.dow,
      C.green,
      (d) => d.day.slice(0, 3),
      (d) => d.avg_likes,
      "Rata-rata like"
    );

    const typeColors = [C.blue, C.pink];
    const types = D.types.map((t) => ({ label: t.type, count: t.count }));
    donutChart(document.getElementById("chart-type"), types, typeColors);
    legend(document.getElementById("legend-type"), types, typeColors);

    renderPosts();
    renderComments();

    document.querySelectorAll("[data-close]").forEach((el) =>
      el.addEventListener("click", closeModal)
    );
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeModal();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
