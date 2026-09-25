"use strict";
// The main page: one table, the minds terminal, the pick, the standings.

const SVGNS = "http://www.w3.org/2000/svg";
const C = 350, RING = 250;
const SHOWN = new Set(["round_start", "say", "whisper", "vote", "reveal", "revote", "tiebreak", "exile",
  "closing", "jury", "winner", "fallback", "budget_stop", "season_end"]);
const S = {
  index: [], stats: null, id: null, entry: null, events: [], steps: [], cursor: 0,
  playing: false, timer: null, speed: 1, roundStarts: [], seats: [], nodes: {}, vm: null,
};

function svg(tag, attrs) {
  const n = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, String(v));
  return n;
}

function store(key, val) {
  try {
    if (val === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, val);
  } catch (_) { /* private mode: picks just aren't remembered */ }
  return null;
}

/* ---------- boot ---------- */

async function boot() {
  try {
    const idx = await getJSON("seasons/index.json");
    S.index = (Array.isArray(idx) ? idx : []).filter((s) => s && typeof s.id === "string" && SEASON_ID.test(s.id));
  } catch (err) {
    $("term").replaceChildren(el("li", "empty", "Could not load the seasons. " + err.message));
    return;
  }
  try { S.stats = await getJSON("seasons/stats.json"); } catch (_) { S.stats = null; }
  const sel = $("season");
  sel.replaceChildren();
  for (const s of S.index) {
    const o = el("option", "", (s.dry_run ? "demo · " : "") + s.id);
    o.value = s.id;
    sel.append(o);
  }
  sel.disabled = !S.index.length;
  sel.addEventListener("change", () => load(sel.value, null));
  renderStandings();
  countdown();
  setInterval(countdown, 1000);
  const h = location.hash.match(/^#s=([a-z0-9-]{1,64})(?:&e=(\d{1,7}))?$/);
  const first = S.index.find((s) => !s.dry_run) || S.index[0];
  if (!first) return;
  const pick = h && S.index.some((s) => s.id === h[1]) ? h[1] : first.id;
  load(pick, h && h[2] ? Number(h[2]) : null);
}

function countdown() {
  const now = new Date();
  const next = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), 18, 0, 0));
  if (next <= now) next.setUTCDate(next.getUTCDate() + 1);
  const s = Math.floor((next - now) / 1000);
  const p = (n) => String(n).padStart(2, "0");
  $("next").textContent = p(Math.floor(s / 3600)) + ":" + p(Math.floor(s / 60) % 60) + ":" + p(s % 60);
}

async function load(id, seq) {
  pause();
  if (!SEASON_ID.test(id)) return;
  $("season").value = id;
  history.replaceState(null, "", "#s=" + id);
  let text;
  try {
    const r = await fetch("seasons/" + id + "/log.jsonl", { cache: "no-cache" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    text = await r.text();
  } catch (err) {
    $("term").replaceChildren(el("li", "empty", "Could not load season " + id + ": " + err.message));
    return;
  }
  const events = [];
  for (const line of text.split("\n")) {
    if (!line.trim()) continue;
    try {
      const e = JSON.parse(line);
      if (e && typeof e === "object" && typeof e.kind === "string") events.push(e);
    } catch (_) { /* a broken line is skipped, never rendered raw */ }
  }
  S.id = id;
  S.entry = S.index.find((s) => s.id === id) || {};
  S.events = events;
  S.steps = events.filter((e) => SHOWN.has(e.kind));
  S.roundStarts = [];
  S.steps.forEach((e, i) => { if (e.kind === "round_start") S.roundStarts.push(i); });
  const start = events.find((e) => e.kind === "season_start");
  S.seats = start && Array.isArray(start.roster) ? start.roster.map((r) => ({ name: str(r.name), model: str(r.model) })) : [];
  const range = $("round");
  range.max = String(Math.max(0, S.roundStarts.length - 1));
  range.disabled = S.roundStarts.length < 2;
  const end = [...events].reverse().find((e) => e.kind === "season_end" || e.kind === "budget_stop");
  $("stat").textContent = end ? end.calls + " calls · ~$" + num(end.usd_est_total).toFixed(3) : "";
  renderBanner(start, end);
  buildTable();
  renderPick();
  const at = seq ? S.steps.findIndex((s) => s.seq >= seq) : -1;
  jump(at >= 0 ? at + 1 : 0);
}

function renderBanner(start, end) {
  const box = $("banner");
  box.replaceChildren();
  box.hidden = true;
  if (start && start.dry_run) {
    box.hidden = false;
    box.className = "banner";
    box.textContent = "Demo season with mock players: canned lines, no model was called. Live seasons are marked live.";
  }
  if (end && end.kind === "budget_stop") {
    box.hidden = false;
    box.className = "banner stop";
    box.textContent = "This season hit its " + (end.reason === "max_calls" ? "call cap" : "spending cap") + " in round " + end.round + " and stopped with no winner.";
  }
}

/* ---------- the table ---------- */

function buildTable() {
  const t = $("table");
  t.replaceChildren();
  add(t,
    svg("circle", { cx: C, cy: C, r: RING + 64, fill: "none", stroke: "var(--line)", "stroke-width": 1 }),
    svg("circle", { cx: C, cy: C, r: RING, fill: "none", stroke: "var(--line-2)", "stroke-width": 1, "stroke-dasharray": "2 6" }),
    svg("circle", { cx: C, cy: C, r: 178, fill: "rgba(255,255,255,0.012)", stroke: "var(--line)", "stroke-width": 1 }));
  for (let k = 0; k < 4; k++) {
    const a = k * Math.PI / 2;
    t.append(svg("line", { x1: C + Math.cos(a) * (RING + 52), y1: C + Math.sin(a) * (RING + 52),
      x2: C + Math.cos(a) * (RING + 76), y2: C + Math.sin(a) * (RING + 76), stroke: "var(--muted)", "stroke-width": 1 }));
  }
  const edges = svg("g", { id: "edges" });
  t.append(edges);
  S.nodes = {};
  const n = S.seats.length || 7;
  S.seats.forEach((seat, i) => {
    const a = (i / n) * Math.PI * 2 - Math.PI / 2;
    const x = C + Math.cos(a) * RING, y = C + Math.sin(a) * RING;
    const col = "var(--p-" + (PLAYERS.includes(seat.name) ? seat.name : "Human") + ")";
    const g = svg("g", { class: "seat" });
    const halo = svg("circle", { class: "halo", cx: x, cy: y, r: 34, fill: "none", stroke: col, "stroke-width": 1.5, opacity: 0 });
    const body = svg("circle", { class: "body", cx: x, cy: y, r: 30, fill: col, "fill-opacity": 0.14, stroke: col, "stroke-width": 1.5 });
    const name = svg("text", { x, y: y + 4.5, "text-anchor": "middle", "font-size": 12.5, "font-weight": 600, fill: "var(--ink)" });
    name.textContent = seat.name;
    const out = Math.cos(a) >= 0 ? 1 : -1;
    const label = svg("text", { x: x + out * 44, y: y + 4, "text-anchor": out > 0 ? "start" : "end", "font-size": 11, fill: "var(--muted)", "font-family": "var(--mono)" });
    const badge = svg("text", { x, y: y + (Math.sin(a) > 0 ? 50 : -42), "text-anchor": "middle", "font-size": 11, fill: "var(--gold)", "font-family": "var(--mono)" });
    label.textContent = seat.model.replace(/^[^/]+\//, "");
    add(g, halo, body, name, label, badge);
    t.append(g);
    S.nodes[seat.name] = { g, body, badge, label, x, y };
  });
}

function edge(from, to, cls) {
  const a = S.nodes[from], b = S.nodes[to];
  if (!a || !b) return;
  const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
  const cx = mx + (C - mx) * 0.55, cy = my + (C - my) * 0.55;
  const dx = b.x - cx, dy = b.y - cy, d = Math.hypot(dx, dy) || 1;
  const ex = b.x - dx / d * 34, ey = b.y - dy / d * 34;
  const col = cls === "whisper" ? "var(--whisper)" : "var(--p-" + (PLAYERS.includes(from) ? from : "Human") + ")";
  const p = svg("path", { class: "edge " + cls, d: "M" + a.x + " " + a.y + " Q" + cx + " " + cy + " " + ex + " " + ey,
    stroke: cls === "vote" ? col : "var(--whisper)", "stroke-width": cls === "vote" ? 1.6 : 1.4 });
  $("edges").append(p);
  if (cls === "vote") $("edges").append(svg("circle", { cx: ex, cy: ey, r: 3, fill: col }));
}

/* ---------- the view model, rebuilt or advanced one event at a time ---------- */

function freshVM() {
  return { alive: new Set(S.seats.map((s) => s.name)), out: {}, speaking: null, winner: null,
    whispers: [], tally: {}, promised: {} };
}

function termLine(cls, parts) {
  const li = el("li", cls);
  for (const p of parts) {
    if (typeof p === "string") li.append(document.createTextNode(p));
    else li.append(p);
  }
  return li;
}

function nameSpan(n) { return color(el("span", "who", n), n); }

function apply(e, live) {
  const vm = S.vm, term = $("term"), lines = [];
  vm.speaking = null;
  const cap = (whoName, text, sub) => { if (live) caption(whoName, text, sub); };
  switch (e.kind) {
    case "round_start":
      if (e.phase !== "final") { vm.alive = new Set(e.alive || []); }
      vm.whispers = []; vm.tally = {}; vm.promised = {};
      $("edges").replaceChildren();
      lines.push(termLine("round", [e.phase === "final" ? "final · " + (e.alive || []).join(" vs ") : "round " + e.round + " · " + (e.alive || []).length + " alive"]));
      cap(null, e.phase === "final" ? "The final" : "Round " + e.round, e.phase === "final" ? "closing statements, then the jury" : (e.alive || []).length + " at the table");
      break;
    case "say":
    case "closing":
      vm.speaking = e.player;
      lines.push(termLine("say", [nameSpan(e.player), (e.kind === "closing" ? " (closing): " : ": ") + str(e.text)]));
      if (str(e.thought)) lines.push(termLine("th", [str(e.thought)]));
      cap(e.player, str(e.text), e.kind === "closing" ? "closing statement" : "");
      break;
    case "whisper":
      if (e.skip) { if (str(e.thought)) lines.push(termLine("th", [nameSpan(e.player), " " + str(e.thought)])); break; }
      vm.whispers.push([e.player, e.to]);
      vm.promised[e.player] = e.to;
      edge(e.player, e.to, "whisper");
      lines.push(termLine("wh", [nameSpan(e.player), " → ", nameSpan(e.to), " (whisper): " + str(e.text)]));
      if (str(e.thought)) lines.push(termLine("th", [str(e.thought)]));
      cap(e.player, "whispers to " + e.to, "only " + e.to + " hears it");
      break;
    case "vote":
      if (e.abstain) { lines.push(termLine("th", [nameSpan(e.player), " abstains"])); break; }
      lines.push(termLine("say", [nameSpan(e.player), " votes ", nameSpan(e.target), str(e.reason) ? " — " + str(e.reason) : ""]));
      if (str(e.thought)) lines.push(termLine("th", [str(e.thought)]));
      if (vm.promised[e.player] === e.target) lines.push(termLine("flag", ["⚑ turned on " + e.target + ": whispered to them this round, then voted them"]));
      cap(e.player, "casts a sealed vote", "");
      break;
    case "reveal": {
      $("edges").replaceChildren();
      for (const [v, t] of Object.entries(e.votes || {})) if (t) edge(v, t, "vote");
      vm.tally = e.tally || {};
      const list = Object.entries(vm.tally).sort((a, b) => b[1] - a[1]).map(([k, n]) => k + " " + n).join(" · ");
      lines.push(termLine("sys", ["votes revealed: " + (list || "no valid votes")]));
      cap(null, "Votes revealed", list);
      break;
    }
    case "revote":
      lines.push(termLine("sys", ["tie: " + (e.between || []).join(" vs ") + " · revote"]));
      cap(null, "A tie", (e.between || []).join(" vs ") + " · revote");
      break;
    case "tiebreak":
      lines.push(termLine("sys", ["still tied · random pick"]));
      break;
    case "exile":
      vm.alive.delete(e.player);
      vm.out[e.player] = e.round;
      vm.tally = {};
      lines.push(termLine("sys", [e.player + " is out · " + e.votes + " votes"]));
      cap(e.player, "is exiled", "joins the jury");
      break;
    case "jury":
      lines.push(termLine("say", [nameSpan(e.player), " (juror) → " + (e.abstain ? "abstains" : str(e.winner)) + (str(e.reason) ? " — " + str(e.reason) : "")]));
      if (str(e.thought)) lines.push(termLine("th", [str(e.thought)]));
      cap(e.player, e.abstain ? "abstains" : "votes " + str(e.winner), "jury");
      break;
    case "winner": {
      vm.winner = e.player;
      const j = Object.entries(e.jury_votes || {}).map(([k, n]) => k + " " + n).join(" – ");
      lines.push(termLine("sys", ["★ " + e.player + " wins · jury " + j]));
      cap(e.player, "wins the season", "jury " + j);
      if (live) settlePick();
      break;
    }
    case "fallback":
      lines.push(termLine("flag", ["gate: " + str(e.player) + " fallback (" + str(e.reason) + ")"]));
      break;
    case "budget_stop":
      lines.push(termLine("flag", ["season stopped: " + (e.reason === "max_calls" ? "call cap" : "spending cap")]));
      break;
    case "season_end":
      lines.push(termLine("sys", ["season over · " + e.calls + " calls"]));
      break;
  }
  for (const l of lines) term.append(l);
}

function caption(whoName, text, sub) {
  const box = $("caption");
  const w = el("div", "c-who", whoName || "petri");
  if (whoName) color(w, whoName);
  box.replaceChildren(w, el("div", "c-text", text || ""), el("div", "c-sub", sub || ""));
}

function paint() {
  const vm = S.vm;
  for (const [n, node] of Object.entries(S.nodes)) {
    node.g.classList.toggle("speaking", vm.speaking === n);
    node.g.classList.toggle("out", !!vm.out[n]);
    node.body.setAttribute("fill-opacity", vm.winner === n ? 0.5 : vm.speaking === n ? 0.34 : 0.14);
    node.body.setAttribute("stroke", vm.winner === n ? "var(--gold)" : "var(--p-" + (PLAYERS.includes(n) ? n : "Human") + ")");
    node.badge.textContent = vm.winner === n ? "★ winner" : vm.out[n] ? "out · R" + vm.out[n] : vm.tally[n] ? vm.tally[n] + (vm.tally[n] === 1 ? " vote" : " votes") : "";
  }
  let r = 0;
  S.roundStarts.forEach((idx, i) => { if (idx < S.cursor) r = i; });
  $("round").value = String(r);
  const st = S.steps[S.roundStarts[r]];
  $("roundlabel").textContent = st ? (st.phase === "final" ? "final" : "round " + st.round) : "—";
  const done = S.cursor >= S.steps.length;
  $("playbtn").textContent = S.playing ? "Pause" : done ? "Replay" : S.cursor ? "Resume" : "Watch";
  $("step").disabled = done;
}

function jump(n) {
  n = Math.max(0, Math.min(n, S.steps.length));
  S.vm = freshVM();
  $("term").replaceChildren();
  $("edges").replaceChildren();
  for (let i = 0; i < n; i++) apply(S.steps[i], false);
  S.cursor = n;
  if (!n) {
    $("term").append(el("li", "empty", "Pick a winner above, then press Watch. Thoughts and whispers stream here as the season plays."));
    caption(null, S.entry.dry_run ? "Demo table" : "Season " + S.id, "seven models · one vote · no way out");
  } else {
    const last = S.steps[n - 1];
    if (last.kind === "say" || last.kind === "closing") caption(last.player, str(last.text), "");
    else if (last.kind === "winner" || S.vm.winner) caption(S.vm.winner, "wins the season", "");
    else caption(null, last.phase === "final" ? "The final" : "Round " + last.round, "");
  }
  $("term").scrollTop = $("term").scrollHeight;
  if (S.vm.winner) settlePick();
  paint();
}

function stepOnce() {
  if (S.cursor >= S.steps.length) { pause(); return false; }
  const term = $("term");
  const follow = term.scrollHeight - term.scrollTop - term.clientHeight < 120;
  const empty = term.querySelector(".empty");
  if (empty) empty.remove();
  apply(S.steps[S.cursor], true);
  S.cursor++;
  if (follow) term.scrollTop = term.scrollHeight;
  lockPick();
  paint();
  return true;
}

function delay(e) {
  const base = e.kind === "say" || e.kind === "closing" ? 1100 + Math.min(3200, str(e.text).length * 18)
    : e.kind === "reveal" || e.kind === "exile" || e.kind === "winner" ? 2600
    : e.kind === "round_start" ? 1600 : e.kind === "whisper" ? 1300 : 700;
  return base / S.speed;
}

function tick() {
  S.timer = null;
  if (!S.playing || !stepOnce()) return;
  const next = S.steps[S.cursor];
  if (!next) { pause(); return; }
  S.timer = setTimeout(tick, delay(next));
}

function play() {
  if (!S.steps.length) return;
  if (S.cursor >= S.steps.length) jump(0);
  S.playing = true;
  paint();
  tick();
}

function pause() {
  S.playing = false;
  if (S.timer) clearTimeout(S.timer);
  S.timer = null;
  if (S.steps.length) paint();
}

/* ---------- the pick: call the winner before you watch ---------- */

function pickKey(id) { return "petri.pick." + id; }

function renderPick() {
  const box = $("chips");
  box.replaceChildren();
  const mine = store(pickKey(S.id));
  for (const seat of S.seats) {
    const b = color(el("button", "chip"), seat.name);
    b.type = "button";
    add(b, el("i"), el("span", "", seat.name));
    b.setAttribute("aria-pressed", String(mine === seat.name));
    b.addEventListener("click", () => {
      if (b.disabled) return;
      store(pickKey(S.id), seat.name);
      renderPick();
    });
    box.append(b);
  }
  $("pick-result").textContent = mine ? "Your pick: " + mine + ". Watch to find out." : "";
  $("pick-result").className = "result";
  lockPick();
  renderRecord();
}

function lockPick() {
  const locked = S.cursor > 0 || (S.vm && S.vm.winner);
  for (const b of $("chips").children) b.disabled = !!locked;
}

function settlePick() {
  const mine = store(pickKey(S.id));
  const w = S.vm && S.vm.winner;
  if (!w) return;
  const r = $("pick-result");
  if (!mine) { r.textContent = w + " won. Pick before the next season."; r.className = "result"; }
  else if (mine === w) { r.textContent = "You called it: " + w + "."; r.className = "result win"; }
  else { r.textContent = "You picked " + mine + ". " + w + " won."; r.className = "result"; }
  lockPick();
  renderRecord();
}

function renderRecord() {
  let picks = 0, hits = 0;
  for (const s of S.index) {
    const p = store(pickKey(s.id));
    if (!p || !s.winner) continue;
    picks++;
    if (p === s.winner) hits++;
  }
  $("record").replaceChildren(el("b", "", hits + " / " + picks), el("span", "", "your calls"));
}

/* ---------- standings ---------- */

function renderStandings() {
  const box = $("standings");
  box.replaceChildren();
  const real = S.stats && S.stats.real && S.stats.real.rows && S.stats.real.rows.length ? S.stats.real : null;
  const data = real || (S.stats && S.stats.demo) || { rows: [], totals: {} };
  $("standings-sub").textContent = real
    ? "Across " + real.totals.complete + " live season" + (real.totals.complete === 1 ? "" : "s") + ". Counted from the logs by code, not judged by a model."
    : "No live seasons yet, so this shows the demo seasons (mock players). Counted from the logs by code.";
  if (!data.rows.length) { box.append(el("li", "empty", "Nothing yet.")); return; }
  data.rows.forEach((r, i) => {
    const li = el("li");
    const nm = color(el("div", "nm"), r.player);
    add(nm, el("i"), add(el("div"), el("span", "", r.player), el("small", "", (r.models || []).join(", "))));
    const cell = (v, k, opt) => add(el("div", "n" + (opt ? " opt" : ""), v), el("small", "", k));
    add(li, el("span", "rk", String(i + 1).padStart(2, "0")), nm,
      cell(String(r.wins), "wins"),
      cell(r.avg_place === null ? "—" : r.avg_place.toFixed(1), "avg place"),
      cell(String(r.broken), "turned on", true),
      cell(pct(r.read_room), "read the room", true));
    box.append(li);
  });
}

/* ---------- wiring ---------- */

$("playbtn").addEventListener("click", () => (S.playing ? pause() : play()));
$("step").addEventListener("click", () => { pause(); stepOnce(); });
$("end").addEventListener("click", () => { pause(); jump(S.steps.length); });
for (const b of document.querySelectorAll("[data-speed]")) {
  b.addEventListener("click", () => {
    S.speed = Number(b.dataset.speed);
    for (const o of document.querySelectorAll("[data-speed]")) o.setAttribute("aria-pressed", String(o === b));
  });
}
$("round").addEventListener("input", (ev) => {
  const i = S.roundStarts[Number(ev.target.value)];
  pause();
  if (i !== undefined) jump(i + 1);
});

boot();
