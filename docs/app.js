"use strict";

// Destinations for outbound links. Empty means "no destination yet":
// the label renders as plain muted text instead of a link.
const LINKS = { x: "", github: "https://github.com/0xbobaaa/petri" };

const PLAYERS = ["Claude", "GPT", "Gemini", "Grok", "DeepSeek", "Qwen", "Mistral", "Human"];
const SEASON_ID = /^[a-z0-9][a-z0-9-]{0,63}$/;
const SHOWN = new Set(["round_start", "say", "whisper", "vote", "reveal", "revote", "tiebreak", "exile",
  "closing", "jury", "winner", "fallback", "budget_stop", "season_end"]);

// Every piece of text on this site, model output included, goes in through
// textContent. Nothing here parses strings as markup.
function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function add(parent, ...kids) {
  for (const k of kids) if (k) parent.append(k);
  return parent;
}

function color(node, name) {
  if (PLAYERS.includes(name)) node.style.setProperty("--pc", "var(--p-" + name + ")");
  return node;
}

function who(name, suffix) {
  const w = color(el("span", "who"), name);
  add(w, el("span", "dot"), el("span", "", name));
  if (suffix) w.append(el("span", "tag", suffix));
  return w;
}

function str(v) { return typeof v === "string" ? v : ""; }
function num(v, d) { return Number.isFinite(v) ? v : (d === undefined ? 0 : d); }
function pct(v) { return v === null || v === undefined ? "—" : Math.round(v * 100) + "%"; }
const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const DATA = { index: [], stats: null };
const state = {
  id: null, events: [], steps: [], cursor: 0, timer: null, playing: false, speed: 1,
  roundStarts: [], start: null, end: null, mobile: false,
};
const feed = $("feed");

async function getJSON(url) {
  const r = await fetch(url, { cache: "no-cache" });
  if (!r.ok) throw new Error(url + " → HTTP " + r.status);
  return r.json();
}

function parseHash() {
  const m = location.hash.match(/^#s=([a-z0-9-]{1,64})(?:&e=(\d{1,7}))?$/);
  return m ? { id: m[1], seq: m[2] ? Number(m[2]) : null } : null;
}

/* ---------- boot ---------- */

async function boot() {
  renderLinks();
  const mq = window.matchMedia("(max-width: 760px)");
  state.mobile = mq.matches;
  mq.addEventListener("change", (e) => { state.mobile = e.matches; syncDetails(); });

  try {
    const idx = await getJSON("seasons/index.json");
    DATA.index = (Array.isArray(idx) ? idx : []).filter((s) => s && typeof s.id === "string" && SEASON_ID.test(s.id));
  } catch (err) {
    return fail("Could not load the season list. " + err.message);
  }
  try { DATA.stats = await getJSON("seasons/stats.json"); } catch (_) { DATA.stats = null; }

  const select = $("season");
  select.replaceChildren();
  if (!DATA.index.length) return fail("No seasons yet.");
  for (const s of DATA.index) {
    const label = [s.date || "", s.dry_run ? "demo" : "",
      s.status === "budget_stop" ? "stopped early" : (s.winner ? s.winner + " wins" : "")].filter(Boolean).join(" · ");
    const o = el("option", "", label ? s.id + " — " + label : s.id);
    o.value = s.id;
    select.append(o);
  }
  select.disabled = false;
  select.addEventListener("change", () => loadSeason(select.value, null, true));

  renderHero();
  renderStrip();
  if (window.PETRI_BOARD) window.PETRI_BOARD.init();

  const h = parseHash();
  const pick = h && DATA.index.some((s) => s.id === h.id) ? h : { id: DATA.index[0].id, seq: null };
  await loadSeason(pick.id, pick.seq, false);
  if (pick.seq) $("table").scrollIntoView();
  window.addEventListener("hashchange", () => {
    const x = parseHash();
    if (x && DATA.index.some((s) => s.id === x.id)) { loadSeason(x.id, x.seq, false); $("table").scrollIntoView(); }
  });
}

function fail(message) {
  pause();
  $("banners").replaceChildren(el("div", "banner error", message));
  feed.replaceChildren(el("li", "empty", "Nothing to replay."));
}

/* ---------- hero: the dish, the ticker, the strip ---------- */

const SVG = "http://www.w3.org/2000/svg";
function svg(tag, attrs) {
  const n = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, String(v));
  return n;
}

function latestReal() {
  return DATA.index.find((s) => !s.dry_run) || DATA.index[0];
}

function renderHero() {
  const s = latestReal();
  const info = DATA.stats && DATA.stats.seasons ? DATA.stats.seasons[s.id] : null;
  $("hero-kicker").textContent = (s.dry_run ? "demo season " : "latest season ") + s.id +
    (s.winner ? " · " + s.winner + " won" : s.status === "budget_stop" ? " · stopped early" : "");

  const dish = $("dish");
  dish.replaceChildren();
  const defs = svg("defs");
  const grad = svg("radialGradient", { id: "agar", cx: "50%", cy: "45%", r: "60%" });
  add(grad, svg("stop", { offset: "0%", "stop-color": "var(--agar)", "stop-opacity": ".55" }),
    svg("stop", { offset: "100%", "stop-color": "var(--agar)", "stop-opacity": ".12" }));
  defs.append(grad);
  dish.append(defs);
  add(dish, svg("circle", { cx: 200, cy: 200, r: 188, fill: "var(--glass)", stroke: "var(--accent)", "stroke-width": 3 }),
    svg("circle", { cx: 200, cy: 200, r: 170, fill: "url(#agar)", stroke: "var(--line)", "stroke-width": 1.5 }),
    svg("path", { d: "M 70 110 A 160 160 0 0 1 150 50", fill: "none", stroke: "#fff", "stroke-opacity": ".5", "stroke-width": 6, "stroke-linecap": "round" }));

  const places = info && info.places ? info.places : {};
  const names = PLAYERS.slice(0, 7);
  names.forEach((name, i) => {
    const a = (i / 7) * Math.PI * 2 - Math.PI / 2;
    const place = places[name];
    const isWin = place === 1;
    const out = place && place > 2;
    const r = isWin ? 46 : place === 2 ? 34 : out ? 16 + (7 - place) * 2 : 28;
    const dist = isWin ? 0 : 108;
    const cx = 200 + Math.cos(a) * dist, cy = 200 + Math.sin(a) * dist;
    const g = svg("g", { class: "colony" + (out ? " out" : ""), style: "animation-delay:" + (i * 0.6) + "s" });
    const fill = "var(--p-" + name + ")";
    // a colony: one body and a few satellites, deterministic per name
    g.append(svg("circle", { cx, cy, r, fill, "fill-opacity": out ? 0.28 : 0.85 }));
    for (let k = 0; k < 4; k++) {
      const b = a + (k - 1.5) * 0.7 + i;
      g.append(svg("circle", { cx: cx + Math.cos(b) * (r + 6), cy: cy + Math.sin(b) * (r + 6), r: 3 + ((i + k) % 3) * 2,
        fill, "fill-opacity": out ? 0.2 : 0.55 }));
    }
    const label = svg("text", { x: cx, y: cy + (isWin ? 6 : 4), "text-anchor": "middle", "font-size": isWin ? 17 : 12,
      "font-weight": 700, fill: out ? "var(--muted)" : "#fff", "font-family": "system-ui, sans-serif" });
    label.textContent = name;
    g.append(label);
    const title = svg("title");
    title.textContent = name + (place ? " · place " + place : "");
    g.append(title);
    dish.append(g);
  });
  $("dish-caption").textContent = info && info.winner
    ? "latest culture: " + info.winner + " at the centre, exiles fade by the round they fell"
    : "seven cultures, one dish";

  startTicker();
}

function momentLine(m) {
  switch (m.type) {
    case "betrayal": return m.player + " whispered to " + m.target + ", then voted " + (m.fatal ? "them out" : "against them");
    case "tie": return "tie between " + (m.between || []).join(" and ") + ", revote";
    case "coin": return "coin flip between " + (m.between || []).join(", ") + (m.picked ? ": " + m.picked : "");
    case "unanimous": return m.votes + "–0: everyone voted " + m.player;
    case "final": {
      const v = m.jury_votes || {};
      return m.player + " beat " + m.runner_up + " " + num(v[m.player]) + "–" + num(v[m.runner_up]);
    }
  }
  return m.type;
}

function allMoments() {
  const out = [];
  if (!DATA.stats || !DATA.stats.seasons) return out;
  for (const s of DATA.index) {
    const info = DATA.stats.seasons[s.id];
    if (!info) continue;
    for (const m of info.moments || []) out.push({ ...m, season: s.id, dry_run: !!info.dry_run });
  }
  return out;
}

function startTicker() {
  const list = allMoments();
  const box = $("ticker");
  if (!list.length) { box.replaceChildren(el("li", "", "the log is empty so far")); return; }
  let i = 0;
  const push = () => {
    const m = list[i % list.length];
    i++;
    const li = el("li");
    add(li, el("b", "", "R" + m.round + " "), el("span", "", momentLine(m)), el("span", "muted", "  · " + m.season));
    box.prepend(li);
    while (box.children.length > 4) box.lastChild.remove();
  };
  for (let k = 0; k < 3; k++) push();
  setInterval(push, 3200);
}

function renderStrip() {
  const st = DATA.stats || {};
  const real = st.real && st.real.totals && st.real.totals.seasons ? st.real.totals : null;
  const t = real || (st.demo && st.demo.totals) || {};
  const tag = real ? "" : " (demo)";
  const items = [
    [num(t.seasons), "seasons" + tag], [num(t.messages), "public messages"], [num(t.whispers), "whispers"],
    [num(t.betrayals), "broken promises"], [num(t.votes), "votes cast"], ["$" + num(t.usd).toFixed(2), "spent, est."],
  ];
  const box = $("strip");
  box.replaceChildren();
  for (const [v, label] of items) box.append(add(el("div"), el("b", "", v), el("span", "", label)));
}

/* ---------- replay ---------- */

async function loadSeason(id, seq, fromPicker) {
  pause();
  if (!SEASON_ID.test(id)) return fail("Bad season id.");
  $("season").value = id;
  if (fromPicker || !parseHash()) history.replaceState(null, "", "#s=" + id);
  feed.replaceChildren(el("li", "empty", "loading " + id + "…"));
  let text;
  try {
    const r = await fetch("seasons/" + id + "/log.jsonl", { cache: "no-cache" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    text = await r.text();
  } catch (err) {
    return fail("Could not load season " + id + ": " + err.message);
  }
  const events = [];
  for (const line of text.split("\n")) {
    if (!line.trim()) continue;
    try {
      const e = JSON.parse(line);
      if (e && typeof e === "object" && typeof e.kind === "string") events.push(e);
    } catch (_) { /* a broken line is skipped, never rendered raw */ }
  }
  state.id = id;
  setSeason(events, seq);
}

function setSeason(events, seq) {
  state.events = events;
  state.start = events.find((e) => e.kind === "season_start") || null;
  state.end = [...events].reverse().find((e) => e.kind === "season_end" || e.kind === "budget_stop") || null;
  state.steps = events.filter((e) => SHOWN.has(e.kind));
  state.roundStarts = [];
  state.steps.forEach((e, i) => { if (e.kind === "round_start") state.roundStarts.push(i); });
  renderBanners();
  const range = $("round");
  range.max = String(Math.max(0, state.roundStarts.length - 1));
  range.disabled = state.roundStarts.length < 2;
  $("playbtn").disabled = $("step").disabled = !state.steps.length;
  const e = state.end;
  $("stat").textContent = [state.start ? "seed " + state.start.seed : "",
    e ? e.calls + " calls · ~$" + num(e.usd_est_total).toFixed(4) : ""].filter(Boolean).join(" · ");

  const at = seq ? state.steps.findIndex((s) => s.seq >= seq) : -1;
  if (at >= 0) {
    renderTo(at + 1);
    const row = feed.querySelector('[data-seq="' + state.steps[at].seq + '"]');
    if (row) { row.classList.add("hl"); feed.scrollTop = row.offsetTop - feed.clientHeight / 3; }
  } else {
    renderTo(Math.min(state.steps.length, (state.roundStarts.length ? state.roundStarts[0] + 1 : 0) + 7));
  }
}

function renderBanners() {
  const box = $("banners");
  box.replaceChildren();
  if (!state.start) { box.append(el("div", "banner error", "This log has no season_start event.")); return; }
  if (state.start.dry_run === true) {
    box.append(add(el("div", "banner demo"), el("b", "", "Demo season: mock players. "),
      el("span", "", "No model was called. The lines are canned and picked by a seeded random number generator. Real seasons show up here once they run.")));
  }
  const stop = state.end && state.end.kind === "budget_stop" ? state.end : null;
  if (stop) {
    const why = stop.reason === "max_calls" ? "the cap on model calls" : "the estimated spending cap";
    box.append(add(el("div", "banner stop"), el("b", "", "This season stopped early. "),
      el("span", "", "It reached " + why + " after " + stop.calls + " calls (about $" + num(stop.usd_est_total).toFixed(4) +
        "), in round " + stop.round + ". There is no winner.")));
  }
}

function renderRoster() {
  const box = $("roster");
  box.replaceChildren();
  const roster = state.start && Array.isArray(state.start.roster) ? state.start.roster : [];
  const exiled = new Map(), finalists = new Set();
  let winner = null;
  for (const e of state.steps.slice(0, state.cursor)) {
    if (e.kind === "exile") exiled.set(e.player, e.round);
    if (e.kind === "round_start" && e.phase === "final") (e.alive || []).forEach((p) => finalists.add(p));
    if (e.kind === "winner") winner = e.player;
  }
  for (const p of roster) {
    const name = str(p.name);
    const li = color(el("li", "chip"), name);
    let status = "alive";
    if (winner === name) { status = "winner"; li.classList.add("win"); }
    else if (exiled.has(name)) { status = "exiled · round " + exiled.get(name) + " · juror"; li.classList.add("out"); }
    else if (finalists.has(name)) status = "finalist";
    add(li, add(el("div", "n"), el("span", "dot"), el("span", "", name)), el("div", "m", str(p.model)), el("div", "s", status));
    box.append(li);
  }
}

function row(cls, pub, back, backLabel) {
  const li = el("li", "row " + (cls || ""));
  const p = el("div", "pub");
  if (pub) p.append(pub);
  li.append(p);
  if (back) {
    const d = el("details", "back");
    add(d, el("summary", "", backLabel || "backstage"), add(el("div", "inner"), back));
    d.open = !state.mobile || !pub;
    li.append(d);
  } else {
    li.append(el("div", "back"));
  }
  if (!pub && back) li.classList.add("only-back");
  return li;
}

function full(node) {
  return add(el("li", "row full"), add(el("div", "pub"), node));
}

function thought(e) {
  const t = str(e.thought);
  return t ? el("div", "thought", t) : el("div", "quiet", "(no thought given)");
}

function flags(node, e) {
  if (e.truncated) node.append(el("span", "tag", "cut at 280"));
  if (e.fallback) node.append(el("span", "tag warn", "fallback"));
  return node;
}

function tallyCard(title, tally, ballots) {
  const card = el("div", "card");
  card.append(el("h4", "", title));
  const entries = Object.entries(tally && typeof tally === "object" ? tally : {})
    .filter(([, n]) => Number.isFinite(n)).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...entries.map(([, n]) => n));
  if (entries.length) {
    const bars = el("div", "bars");
    for (const [name, n] of entries) {
      const bar = color(el("div", "bar"), name);
      bar.style.width = (100 * n / max) + "%";
      add(bars, who(name), add(el("div"), bar), el("span", "c", n + (n === 1 ? " vote" : " votes")));
    }
    card.append(bars);
  } else {
    card.append(el("div", "quiet", "No valid votes."));
  }
  const list = el("ul", "ballots");
  for (const b of ballots) {
    const li = el("li");
    li.append(el("b", "", str(b.player)));
    li.append(b.abstain ? el("span", "r", " abstained") : el("span", "", " → " + str(b.target)));
    if (str(b.reason)) li.append(el("span", "r", " — " + str(b.reason)));
    list.append(li);
  }
  if (ballots.length) card.append(list);
  return card;
}

function ballotsFor(e, steps) {
  const i = steps.indexOf(e);
  const out = [];
  for (let j = i - 1; j >= 0; j--) {
    const v = steps[j];
    if (v.kind === "vote" && v.round === e.round && v.phase === e.phase) out.unshift(v);
    else if (v.kind === "reveal" || v.kind === "round_start" || v.kind === "revote") break;
  }
  return out;
}

// Shared with the practice table (play.js), which renders the same event shapes.
function renderEvent(e, steps, opts) {
  const o = opts || {};
  const node = renderEventInner(e, steps || state.steps, o);
  if (node && Number.isInteger(e.seq)) node.dataset.seq = String(e.seq);
  return node;
}

function renderEventInner(e, steps, o) {
  const backCls = o.botBack && o.botBack(e) ? " bot" : "";
  switch (e.kind) {
    case "round_start": {
      const d = el("div", "divider");
      const fin = e.phase === "final";
      add(d, el("h3", "", fin ? "final" : "round " + e.round), el("span", "sub", fin
        ? "finalists: " + (e.alive || []).join(", ") + " · jury: " + (e.jurors || []).join(", ")
        : (e.alive || []).length + " alive: " + (e.alive || []).join(", ")));
      return full(d);
    }
    case "say":
    case "closing": {
      const pub = color(el("div"), e.player);
      pub.append(flags(who(e.player, e.kind === "closing" ? "closing statement" : e.turn ? "pass " + e.turn : ""), e));
      pub.append(el("p", "msg", str(e.text)));
      const r = row(e.kind, pub, str(e.thought) || !o.plain ? thought(e) : null, "backstage · " + str(e.player) + " thinks");
      if (backCls) r.lastChild.classList.add("bot-back");
      return r;
    }
    case "whisper": {
      const card = el("div", "wh");
      const hd = el("div", "hd");
      if (e.skip) {
        add(hd, el("b", "", str(e.player)), el("span", "", "sends no whisper"));
        add(card, flags(hd, e), thought(e));
        const r = row("whisper", null, card, "whisper · " + str(e.player) + " skips");
        if (backCls) r.lastChild.classList.add("bot-back");
        return r;
      }
      add(hd, el("b", "", str(e.player)), el("span", "", "whispers to"), el("b", "", str(e.to)));
      add(card, flags(hd, e), el("div", "txt", str(e.text)), str(e.thought) || !o.plain ? thought(e) : null);
      if (o.publicWhisper && o.publicWhisper(e)) {
        return row("whisper", add(el("div", "wh"), hd, el("div", "txt", str(e.text))), null);
      }
      const r = row("whisper", null, card, "whisper · " + str(e.player) + " → " + str(e.to));
      if (backCls) r.lastChild.classList.add("bot-back");
      return r;
    }
    case "vote": {
      const pub = el("div", "quiet");
      add(pub, who(e.player), el("span", "", e.phase === "revote" ? " casts a sealed revote" : " casts a sealed vote"));
      const back = el("div", "ballot");
      back.append(e.abstain ? el("span", "t", "abstains") : el("span", "t", "→ " + str(e.target)));
      flags(back, e);
      if (str(e.reason)) back.append(el("div", "", "“" + str(e.reason) + "”"));
      const r = row("vote", pub, add(el("div"), back, thought(e)), "backstage · " + str(e.player) + "’s ballot");
      if (backCls) r.lastChild.classList.add("bot-back");
      return r;
    }
    case "reveal":
      return full(tallyCard("round " + e.round + (e.phase === "revote" ? " · revote revealed" : " · votes revealed"),
        e.tally, ballotsFor(e, steps)));
    case "revote":
      return full(el("div", "notice", "Tie between " + (e.between || []).join(" and ") + ". One revote: everyone alive votes, only for them."));
    case "tiebreak":
      return full(el("div", "notice", (e.reason === "all_abstain" ? "Every ballot was an abstain" : "Still tied") +
        ". Random pick between " + (e.between || []).join(", ") + " (seeded, logged)."));
    case "exile":
      return full(add(el("div", "exile"), color(el("b", "", str(e.player)), e.player),
        el("span", "", " is exiled with " + e.votes + (e.votes === 1 ? " vote" : " votes") + " and joins the jury.")));
    case "jury": {
      const pub = el("div");
      pub.append(flags(who(e.player, "juror"), e));
      pub.append(el("p", "msg", e.abstain ? "abstains" : "votes for " + str(e.winner) + (str(e.reason) ? " — “" + str(e.reason) + "”" : "")));
      const r = row("jury", pub, thought(e), "backstage · " + str(e.player) + " thinks");
      if (backCls) r.lastChild.classList.add("bot-back");
      return r;
    }
    case "winner": {
      const d = color(el("span", "dot"), e.player);
      d.style.width = d.style.height = "14px";
      const votes = Object.entries(e.jury_votes || {}).map(([k, n]) => k + " " + n).join(" · ");
      return full(add(el("div", "winner"), add(el("div", "big"), d, el("span", "", str(e.player) + " wins")), el("div", "quiet", "jury: " + votes)));
    }
    case "fallback":
      return row("gate", null, el("div", "gate", "gate: " + str(e.player) + " — " + str(e.reason) + " (" + str(e.phase) + ")"), "gate · fallback for " + str(e.player));
    case "budget_stop":
      return full(el("div", "exile", "Season stopped: " + (e.reason === "max_calls" ? "call cap" : "spending cap") + " reached after " + e.calls + " calls (~$" + num(e.usd_est_total).toFixed(4) + ")."));
    case "season_end":
      return full(el("div", "notice", "Season over · " + e.calls + " calls · ~$" + num(e.usd_est_total).toFixed(4) + " estimated."));
  }
  return null;
}

function nearBottom() { return feed.scrollHeight - feed.scrollTop - feed.clientHeight < 140; }

function renderTo(n) {
  n = Math.max(0, Math.min(n, state.steps.length));
  const frag = document.createDocumentFragment();
  for (let i = 0; i < n; i++) { const node = renderEvent(state.steps[i]); if (node) frag.append(node); }
  feed.replaceChildren(frag);
  state.cursor = n;
  if (n <= 1) feed.append(el("li", "empty", "Press play to replay the season, or step through it one move at a time."));
  feed.scrollTop = feed.scrollHeight;
  afterStep();
}

function stepOnce() {
  if (state.cursor >= state.steps.length) { pause(); return false; }
  const follow = nearBottom();
  const empty = feed.querySelector(".empty");
  if (empty) empty.remove();
  const node = renderEvent(state.steps[state.cursor]);
  state.cursor++;
  if (node) feed.append(node);
  if (follow) feed.scrollTop = feed.scrollHeight;
  afterStep();
  return true;
}

function afterStep() {
  renderRoster();
  let r = 0;
  state.roundStarts.forEach((idx, i) => { if (idx < state.cursor) r = i; });
  $("round").value = String(r);
  const start = state.steps[state.roundStarts[r]];
  $("roundlabel").textContent = start ? (start.phase === "final" ? "final" : "round " + start.round) : "—";
  const done = state.cursor >= state.steps.length;
  $("step").disabled = done;
  $("playbtn").textContent = state.playing ? "pause" : (done ? "replay" : "play");
}

function delay(e) {
  const base = e.kind === "say" || e.kind === "closing" ? 900 + Math.min(2600, str(e.text).length * 14)
    : e.kind === "reveal" || e.kind === "exile" || e.kind === "winner" ? 2200
    : e.kind === "round_start" ? 1400 : 650;
  return base / state.speed;
}

function tick() {
  state.timer = null;
  if (!state.playing || !stepOnce()) return;
  const next = state.steps[state.cursor];
  if (!next) { pause(); return; }
  state.timer = setTimeout(tick, delay(next));
}

function play() {
  if (!state.steps.length) return;
  if (state.cursor >= state.steps.length) renderTo(0);
  if (state.speed === 0) { renderTo(state.steps.length); return; }
  state.playing = true;
  afterStep();
  tick();
}

function pause() {
  state.playing = false;
  if (state.timer) clearTimeout(state.timer);
  state.timer = null;
  if (state.steps.length) afterStep();
}

function syncDetails() {
  for (const d of document.querySelectorAll("details.back")) {
    const pub = d.parentElement && d.parentElement.firstChild;
    d.open = !state.mobile || !(pub && pub.childNodes.length);
  }
}

function renderLinks() {
  const box = $("links");
  for (const [label, url] of [["X", LINKS.x], ["GitHub", LINKS.github]]) {
    if (typeof url === "string" && /^https:\/\//.test(url)) {
      const a = el("a", "", label);
      a.setAttribute("href", url);
      a.setAttribute("rel", "noopener noreferrer");
      box.append(a);
    } else {
      box.append(el("span", "muted", label));
    }
  }
  const src = $("source");
  if (/^https:\/\//.test(LINKS.github)) {
    const a = el("a", "", "source");
    a.setAttribute("href", LINKS.github);
    src.append(a);
  } else {
    src.append(el("span", "", "source"));
  }
}

$("playbtn").addEventListener("click", () => (state.playing ? pause() : play()));
$("step").addEventListener("click", () => { pause(); stepOnce(); });
for (const b of document.querySelectorAll("[data-speed]")) {
  b.addEventListener("click", () => {
    state.speed = Number(b.dataset.speed);
    for (const o of document.querySelectorAll("[data-speed]")) o.setAttribute("aria-pressed", String(o === b));
    if (state.speed === 0) { pause(); renderTo(state.steps.length); }
  });
}
$("round").addEventListener("input", (ev) => {
  const i = state.roundStarts[Number(ev.target.value)];  // read before pause() re-syncs the range
  pause();
  if (i !== undefined) renderTo(i + 1);
});

boot();
