/* PWA + tools: registrasi service worker, tombol pasang, dan form
   "Ambil CSV dari link" yang memanggil /api/scrape. */
(function () {
  "use strict";

  const nf = new Intl.NumberFormat("id-ID");
  const fmt = (n) => nf.format(Number(n) || 0);

  /* ---------------- service worker + install ---------------- */

  if ("serviceWorker" in navigator && location.protocol.indexOf("http") === 0) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("sw.js").catch(function () {
        /* offline tetap jalan tanpa SW; abaikan */
      });
    });
  }

  const installBtn = document.getElementById("install");
  let deferred = null;

  window.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault();
    deferred = e;
    if (installBtn) installBtn.hidden = false;
  });

  window.addEventListener("appinstalled", function () {
    deferred = null;
    if (installBtn) installBtn.hidden = true;
  });

  if (installBtn) {
    installBtn.addEventListener("click", function () {
      if (!deferred) {
        installBtn.hidden = true;
        return;
      }
      deferred.prompt();
      deferred.userChoice.then(function () {
        deferred = null;
        installBtn.hidden = true;
      });
    });
  }

  /* ---------------- unduh CSV ---------------- */

  function download(name, csv) {
    // BOM supaya Excel membaca UTF-8 dengan benar.
    const blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () {
      URL.revokeObjectURL(url);
    }, 4000);
  }

  /* ---------------- form ambil CSV ---------------- */

  const form = document.getElementById("link-form");
  if (!form) return;

  const input = document.getElementById("link-input");
  const submit = document.getElementById("link-submit");
  const status = document.getElementById("tool-status");
  const result = document.getElementById("tool-result");

  function setStatus(text, kind) {
    status.textContent = text || "";
    status.className = "tool-status" + (kind ? " " + kind : "");
  }

  function escapeHtml(str) {
    return String(str == null ? "" : str).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  function statBox(label, value) {
    return (
      '<div class="stat-box"><div class="k">' + escapeHtml(label) +
      '</div><div class="v">' + escapeHtml(value) + "</div></div>"
    );
  }

  function renderResult(data) {
    const sent = data.sentiment || {};
    const pos = (sent["sangat positif"] || 0) + (sent["positif"] || 0);
    const neg = (sent["sangat negatif"] || 0) + (sent["negatif"] || 0);

    result.innerHTML =
      '<div class="stat-row">' +
      statBox("Platform", data.platform_name || data.platform || "-") +
      statBox("Tanggal post", data.date || "-") +
      statBox("Like", fmt(data.likes)) +
      statBox("Komentar di platform", fmt(data.comment_count)) +
      statBox("Komentar diambil", fmt(data.comments_fetched)) +
      statBox("Sentimen +/-", fmt(pos) + " / " + fmt(neg)) +
      statBox("Media", fmt((data.media || []).length)) +
      "</div>" +
      '<p class="tool-caption"><a href="' + escapeHtml(data.url) +
      '" target="_blank" rel="noopener">' + escapeHtml(data.url) + "</a><br>" +
      escapeHtml((data.caption || "(tanpa caption)").slice(0, 220)) + "</p>" +
      (data.note ? '<p class="tool-caption tool-note">' + escapeHtml(data.note) + "</p>" : "") +
      '<div class="modal-actions">' +
      '<button type="button" class="btn-link" data-csv="post">Unduh CSV post</button>' +
      '<button type="button" class="btn-link" data-csv="comments">Unduh CSV komentar</button>' +
      "</div>";

    result.hidden = false;

    result.querySelectorAll("[data-csv]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const isPost = btn.dataset.csv === "post";
        download(
          (isPost ? "post-" : "komentar-") + (data.platform || "sosmed") + "-" +
            data.shortcode + ".csv",
          isPost ? data.csv.post : data.csv.comments
        );
      });
    });
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    const url = (input.value || "").trim();
    if (!url) return;

    submit.disabled = true;
    result.hidden = true;
    setStatus("Mengambil data dari link… biasanya 10–40 detik.", "busy");

    fetch("api/scrape", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ url: url }),
    })
      .then(function (res) {
        return res
          .json()
          .catch(function () {
            throw new Error("Server membalas " + res.status + " tanpa data JSON.");
          })
          .then(function (body) {
            if (!res.ok || !body.ok) throw new Error(body.error || "Gagal mengambil data.");
            return body;
          });
      })
      .then(function (data) {
        // CSV komentar langsung diunduh; CSV post tersedia lewat tombol.
        download(
          "komentar-" + (data.platform || "sosmed") + "-" + data.shortcode + ".csv",
          data.csv.comments
        );
        renderResult(data);
        setStatus("Selesai. CSV komentar sudah terunduh.", "ok");
      })
      .catch(function (err) {
        const offline = err instanceof TypeError;
        setStatus(
          offline
            ? "Tidak bisa menghubungi server. Fitur ini butuh backend (/api/scrape) — buka dari Vercel atau jalankan `vercel dev`, bukan dari file://."
            : err.message,
          "err"
        );
      })
      .then(function () {
        submit.disabled = false;
      });
  });
})();
