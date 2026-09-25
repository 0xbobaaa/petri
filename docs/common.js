"use strict";
// Shared by every page. All text, model output included, goes in through
// textContent. Nothing on this site parses strings as markup.

const LINKS = { x: "", github: "https://github.com/0xbobaaa/petri" };
const PLAYERS = ["Claude", "GPT", "Gemini", "Grok", "DeepSeek", "Qwen", "Mistral", "Human"];
const SEASON_ID = /^[a-z0-9][a-z0-9-]{0,63}$/;
const MOBILE = window.matchMedia("(max-width: 620px)");

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

async function getJSON(url) {
  const r = await fetch(url, { cache: "no-cache" });
  if (!r.ok) throw new Error(url + " → HTTP " + r.status);
  return r.json();
}

function renderLinks() {
  const box = $("links");
  if (!box) return;
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
}

/* ---------- event rows (the practice table's feed) ---------- */

function row(cls, pub, back, backLabel) {
  const li = el("li", "row " + (cls || ""));
  const p = el("div", "pub");
  if (pub) p.append(pub);
  li.append(p);
  if (back) {
    const d = el("details", "back");
    add(d, el("summary", "", backLabel || "backstage"), add(el("div", "inner"), back));
    d.open = true;
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
  return t ? el("div", "thought", t) : el("div", "quiet", "—");
}

function flags(node, e) {
  if (e.truncated) node.append(el("span", "tag", "cut at 280"));
  if (e.fallback) node.append(el("span", "tag", "fallback"));
  return node;
}

function tallyCard(title, tally, ballots) {
  const card = el("div", "card");
  card.append(el("h4", "", title));
  const entries = Object.entries(tally && typeof tally === "object" ? tally : {})
    .filter(([, n]) => Number.isFinite(n)).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...entries.map(([, n]) => n));
  const bars = el("div", "bars");
  for (const [name, n] of entries) {
    const bar = color(el("div", "bar"), name);
    bar.style.width = (100 * n / max) + "%";
    add(bars, who(name), add(el("div"), bar), el("span", "c", String(n)));
  }
  card.append(bars);
  const list = el("ul", "ballots");
  for (const b of ballots) {
    list.append(el("li", "", str(b.player) + (b.abstain ? " abstained" : " → " + str(b.target)) +
      (str(b.reason) ? " — " + str(b.reason) : "")));
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

function renderEvent(e, steps, o) {
  o = o || {};
  const bot = o.botBack && o.botBack(e);
  const mark = (r) => { if (bot && r.lastChild) r.lastChild.classList.add("bot-back"); return r; };
  switch (e.kind) {
    case "round_start": {
      const fin = e.phase === "final";
      return full(add(el("div", "divider"), el("h3", "", fin ? "final" : "round " + e.round),
        el("span", "sub", fin ? "finalists: " + (e.alive || []).join(", ") : (e.alive || []).join(" · "))));
    }
    case "say":
    case "closing": {
      const pub = color(el("div"), e.player);
      add(pub, flags(who(e.player, e.kind === "closing" ? "closing" : ""), e), el("p", "msg", str(e.text)));
      return mark(row(e.kind, pub, str(e.thought) ? thought(e) : null));
    }
    case "whisper": {
      if (e.skip) return mark(row("whisper", null, add(el("div", "wh"), el("div", "hd", str(e.player) + " sends no whisper"), thought(e))));
      const card = add(el("div", "wh"), el("div", "hd", str(e.player) + " → " + str(e.to) + " (whisper)"), el("div", "txt", str(e.text)));
      if (o.publicWhisper && o.publicWhisper(e)) return row("whisper", card, null);
      if (str(e.thought)) card.append(thought(e));
      return mark(row("whisper", null, card));
    }
    case "vote": {
      const pub = add(el("div", "quiet"), who(e.player), el("span", "", " casts a sealed vote"));
      const back = add(el("div"), el("div", "", e.abstain ? "abstains" : "→ " + str(e.target)), str(e.thought) ? thought(e) : null);
      return mark(row("vote", pub, back));
    }
    case "reveal":
      return full(tallyCard("round " + e.round + (e.phase === "revote" ? " · revote" : " · votes"), e.tally, ballotsFor(e, steps)));
    case "revote":
      return full(el("div", "notice", "Tie: " + (e.between || []).join(" vs ") + ". Revote."));
    case "tiebreak":
      return full(el("div", "notice", "Still tied. Random pick between " + (e.between || []).join(", ") + "."));
    case "exile":
      return full(el("div", "exile", str(e.player) + " is exiled with " + e.votes + (e.votes === 1 ? " vote." : " votes.")));
    case "jury": {
      const pub = add(el("div"), who(e.player, "juror"), el("p", "msg", e.abstain ? "abstains" : "votes for " + str(e.winner)));
      return mark(row("jury", pub, str(e.thought) ? thought(e) : null));
    }
    case "winner": {
      const votes = Object.entries(e.jury_votes || {}).map(([k, n]) => k + " " + n).join(" · ");
      return full(add(el("div", "winner"), el("div", "big", str(e.player) + " wins"), el("div", "quiet", "jury: " + votes)));
    }
  }
  return null;
}

renderLinks();
