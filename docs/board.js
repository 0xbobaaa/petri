"use strict";
// Leaderboard, moments and share cards. Uses the helpers from app.js.

(function () {
  const COLS = [
    ["player", "player", null],
    ["seasons", "seasons", (r) => r.seasons],
    ["wins", "wins", (r) => r.wins],
    ["win_rate", "win %", (r) => pct(r.win_rate)],
    ["avg_place", "avg place", (r) => r.avg_place === null ? "—" : r.avg_place.toFixed(2)],
    ["jury_share", "jury share", (r) => pct(r.jury_share)],
    ["broken", "broken promises", (r) => r.broken + (r.broken_rate === null ? "" : " · " + pct(r.broken_rate))],
    ["read_room", "read the room", (r) => pct(r.read_room)],
    ["fallback_rate", "format fails", (r) => pct(r.fallback_rate)],
    ["usd_per_season", "$ / season", (r) => r.usd_per_season === null ? "—" : "$" + r.usd_per_season.toFixed(3)],
  ];
  const board = { mode: "real", sort: null, dir: 1, filter: "all" };

  function rowsFor(mode) {
    const s = DATA.stats && DATA.stats[mode];
    return s && Array.isArray(s.rows) ? s.rows.slice() : [];
  }

  function renderBoard() {
    const note = $("board-note");
    let mode = board.mode;
    if (mode === "real" && !rowsFor("real").length) {
      note.textContent = "No finished real seasons yet. Real rows appear after the first season with actual models. Switch to demo to see how the table reads (demo = scripted mock players, meaningless as a ranking).";
    } else if (mode === "demo") {
      note.textContent = "Demo seasons use scripted mock players. These numbers only show how the leaderboard works; they say nothing about any model.";
    } else {
      const t = DATA.stats.real.totals;
      note.textContent = t.complete + " finished real season" + (t.complete === 1 ? "" : "s") + ". Few seasons means noisy numbers.";
    }
    let rows = rowsFor(mode);
    if (board.sort) {
      rows.sort((a, b) => {
        const x = a[board.sort], y = b[board.sort];
        if (x === y) return 0;
        if (x === null || x === undefined) return 1;
        if (y === null || y === undefined) return -1;
        return (x < y ? -1 : 1) * board.dir;
      });
    }
    const table = $("board-table");
    table.replaceChildren();
    const thead = el("thead");
    const hr = el("tr");
    hr.append(el("th", "", "#"));
    for (const [key, label] of COLS) {
      const th = el("th");
      if (key === "player") th.textContent = label;
      else {
        const b = el("button", "", label + (board.sort === key ? (board.dir > 0 ? " ↑" : " ↓") : ""));
        b.type = "button";
        b.addEventListener("click", () => {
          board.dir = board.sort === key ? -board.dir : (key === "avg_place" || key === "fallback_rate" ? 1 : -1);
          board.sort = key;
          renderBoard();
        });
        th.append(b);
      }
      hr.append(th);
    }
    thead.append(hr);
    const tbody = el("tbody");
    if (!rows.length) {
      const tr = el("tr");
      const td = el("td", "quiet", "nothing yet");
      td.colSpan = COLS.length + 1;
      tr.append(td);
      tbody.append(tr);
    }
    rows.forEach((r, i) => {
      const tr = el("tr");
      tr.append(el("td", "rank", String(i + 1)));
      const name = el("td");
      add(name, who(r.player), el("span", "models", (r.models || []).join(", ")));
      tr.append(name);
      for (const [key, , fmt] of COLS.slice(1)) {
        const td = el("td");
        if (key === "win_rate" && r.win_rate !== null) {
          const bar = el("span", "mini");
          bar.style.width = Math.max(2, Math.round(r.win_rate * 48)) + "px";
          td.append(bar);
        }
        td.append(document.createTextNode(String(fmt(r))));
        tr.append(td);
      }
      tbody.append(tr);
    });
    add(table, thead, tbody);
  }

  /* ---------- moments ---------- */

  function momentTitle(m) {
    switch (m.type) {
      case "betrayal": return m.player + " whispered to " + m.target + ", then voted " + (m.fatal ? "them out" : "against them");
      case "tie": return "A tie: " + (m.between || []).join(" vs ") + ". Revote.";
      case "coin": return "A coin flip decided it" + (m.picked ? ": " + m.picked : "");
      case "unanimous": return "Everyone voted " + m.player + " (" + m.votes + "–0)";
      case "final": {
        const v = m.jury_votes || {};
        return m.player + " beat " + m.runner_up + " " + num(v[m.player]) + "–" + num(v[m.runner_up]) + (m.close ? ", by one vote" : "");
      }
    }
    return m.type;
  }

  function quotes(m) {
    if (m.type === "betrayal") {
      const q = [["whisper to " + m.target, m.whisper, ""]];
      if (str(m.thought)) q.push([m.player + " thinks, at the vote", m.thought, "th"]);
      else if (str(m.reason)) q.push(["vote reason", m.reason, ""]);
      return q;
    }
    return [];
  }

  function momentLink(m) {
    return location.origin + location.pathname + "#s=" + m.season + "&e=" + m.seq;
  }

  function renderMoments() {
    const box = $("moment-list");
    box.replaceChildren();
    let list = allMoments();
    const hasReal = list.some((m) => !m.dry_run);
    if (hasReal) list = list.filter((m) => !m.dry_run);
    if (board.filter !== "all") list = list.filter((m) => m.type === board.filter || (board.filter === "tie" && m.type === "coin"));
    list = list.slice(0, 24);
    if (!list.length) { box.append(el("p", "quiet", "No moments of this kind yet.")); return; }
    for (const m of list) {
      const card = el("article", "moment");
      if (PLAYERS.includes(m.player)) color(card, m.player);
      add(card, add(el("div", "type"), el("span", "", m.type === "coin" ? "coin flip" : m.type),
        el("span", "", (m.dry_run ? "demo · " : "") + m.season + " · round " + m.round)));
      card.append(el("h3", "", momentTitle(m)));
      for (const [label, text, cls] of quotes(m)) {
        card.append(add(el("blockquote", cls), el("small", "", label), el("span", "", text)));
      }
      const acts = el("div", "acts");
      const open = el("a", "btn small", "open in replay");
      open.setAttribute("href", "#s=" + m.season + "&e=" + m.seq);
      const copy = el("button", "btn small", "copy link");
      copy.type = "button";
      copy.addEventListener("click", async () => {
        try { await navigator.clipboard.writeText(momentLink(m)); copy.textContent = "copied"; }
        catch (_) { copy.textContent = "copy failed"; }
        setTimeout(() => { copy.textContent = "copy link"; }, 1500);
      });
      const save = el("button", "btn small", "save card");
      save.type = "button";
      save.addEventListener("click", () => saveCard(m));
      add(acts, open, copy, save);
      card.append(acts);
      box.append(card);
    }
  }

  /* ---------- share card (canvas, no markup involved) ---------- */

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
  }

  function wrap(ctx, text, x, y, maxW, lineH, maxLines) {
    const words = String(text).split(/\s+/);
    let line = "", lines = 0;
    for (let i = 0; i < words.length; i++) {
      const test = line ? line + " " + words[i] : words[i];
      if (ctx.measureText(test).width > maxW && line) {
        if (lines === maxLines - 1) { ctx.fillText(line + " …", x, y); return y + lineH; }
        ctx.fillText(line, x, y);
        y += lineH; lines++; line = words[i];
      } else line = test;
    }
    if (line) { ctx.fillText(line, x, y); y += lineH; }
    return y;
  }

  function saveCard(m) {
    const c = $("card-canvas");
    const ctx = c.getContext("2d");
    const W = c.width, H = c.height;
    const dark = matchMedia("(prefers-color-scheme: dark)").matches;
    const bg = dark ? "#0a0c0f" : "#eef0ec", ink = dark ? "#e9ebe7" : "#101311", sub = dark ? "#9aa19a" : "#555c55";
    const accent = cssVar("--accent");
    ctx.fillStyle = bg; ctx.fillRect(0, 0, W, H);
    // dish in the corner
    ctx.save();
    ctx.globalAlpha = 0.9;
    ctx.strokeStyle = accent; ctx.lineWidth = 8;
    ctx.beginPath(); ctx.arc(W - 150, 150, 110, 0, Math.PI * 2); ctx.stroke();
    PLAYERS.slice(0, 7).forEach((p, i) => {
      const a = (i / 7) * Math.PI * 2;
      ctx.fillStyle = cssVar("--p-" + p);
      ctx.globalAlpha = p === m.player ? 1 : 0.45;
      ctx.beginPath(); ctx.arc(W - 150 + Math.cos(a) * 62, 150 + Math.sin(a) * 62, p === m.player ? 24 : 14, 0, Math.PI * 2); ctx.fill();
    });
    ctx.restore();
    const font = "system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif";
    ctx.fillStyle = accent; ctx.font = "700 26px " + font;
    ctx.fillText((m.type === "coin" ? "COIN FLIP" : m.type.toUpperCase()) + "  ·  ROUND " + m.round, 72, 96);
    ctx.fillStyle = ink; ctx.font = "800 58px " + font;
    let y = wrap(ctx, momentTitle(m), 72, 176, W - 400, 66, 3) + 20;
    ctx.font = "400 30px " + font;
    for (const [label, text] of quotes(m)) {
      ctx.fillStyle = sub; ctx.font = "600 22px " + font; ctx.fillText(label.toUpperCase(), 72, y); y += 38;
      ctx.fillStyle = ink; ctx.font = "400 30px " + font;
      y = wrap(ctx, "“" + text + "”", 72, y, W - 144, 40, 3) + 18;
      if (y > H - 110) break;
    }
    ctx.fillStyle = sub; ctx.font = "600 24px " + font;
    ctx.fillText("petri · seven models, one vote, no way out · " + m.season + (m.dry_run ? " (demo, mock players)" : ""), 72, H - 56);
    c.toBlob((blob) => {
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "petri-" + m.season + "-" + m.seq + ".png";
      document.body.append(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
    }, "image/png");
  }

  function init() {
    board.mode = rowsFor("real").length ? "real" : "demo";
    const setPressed = (sel, attr, val) => {
      for (const b of document.querySelectorAll(sel)) b.setAttribute("aria-pressed", String(b.dataset[attr] === val));
    };
    setPressed("#board-mode button", "mode", board.mode);
    for (const b of document.querySelectorAll("#board-mode button")) {
      b.addEventListener("click", () => { board.mode = b.dataset.mode; board.sort = null; setPressed("#board-mode button", "mode", board.mode); renderBoard(); });
    }
    for (const b of document.querySelectorAll("#moment-filter button")) {
      b.addEventListener("click", () => { board.filter = b.dataset.f; setPressed("#moment-filter button", "f", board.filter); renderMoments(); });
    }
    renderBoard();
    renderMoments();
  }

  window.PETRI_BOARD = { init };
})();
