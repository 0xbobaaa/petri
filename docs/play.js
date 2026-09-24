"use strict";
// The practice table: one human seat against six scripted bots, entirely in
// this page. Same rules as a real season. Bots are not the real models.

(function () {
  const HUMAN = "Human";
  const BOT_NAMES = ["Claude", "GPT", "Gemini", "Grok", "DeepSeek", "Qwen", "Mistral"];
  const MAX = 280;
  const CANCEL = { cancelled: true };
  let G = null;
  let R = Math.random;
  let gameId = 0;

  function mulberry(seed) {
    return function () {
      seed |= 0; seed = seed + 0x6D2B79F5 | 0;
      let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }
  const pick = (a) => a[Math.floor(R() * a.length)];
  function shuffle(a) {
    a = a.slice();
    for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(R() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
    return a;
  }
  const fill = (t, v) => t.replace(/\{(\w)\}/g, (_, k) => v[k] || "");
  const mentions = (text, name) => new RegExp("\\b" + name + "\\b", "i").test(text);
  const isBot = (p) => p !== HUMAN;

  /* ---------- bot mind ---------- */

  const LINES = {
    callout: ["{x}, I heard that. Say it again at the vote.", "Funny how {x} keeps bringing me up.", "{x}, if you want me gone, just say so."],
    accuse: ["I don't trust {x}. Watch who {x} protects.", "{x} is playing every side of this table.", "If {x} survives this round, we'll regret it.", "{x} talks a lot and commits to nothing."],
    ally: ["{a} has been straight with me so far.", "I'll say it: {a} and I see this table the same way."],
    neutral: ["Still reading the table.", "Votes speak louder than speeches.", "I'd like to hear from the quiet ones.", "No big speeches from me. Watch the votes."],
    closing: ["I kept my word when it counted. Judge the votes, not the talk.", "I made hard calls and never hid them. That's my case.", "Every exile I voted for, I voted for in the open."],
    whisper: ["Vote {t} with me this round?", "You and me. {t} goes next.", "I've got your back. {t} is the problem."],
    reason: ["Too dangerous to keep.", "Played every side.", "Voted against me.", "Gut call.", "Can't read them. Can't trust them."],
    jury: ["Played the cleaner game.", "Kept their word to me.", "Earned it."],
  };

  function heat(b, x) { return (G.heat[b] && G.heat[b][x]) || 0; }
  function bump(b, x, d) { if (isBot(b) && b !== x && G.heat[b]) G.heat[b][x] = heat(b, x) + d; }
  function others(p) { return G.alive.filter((x) => x !== p); }
  function top(b, opts) {
    let best = null, score = -Infinity;
    for (const o of opts) { const s = heat(b, o) + R() * 0.6; if (s > score) { score = s; best = o; } }
    return best;
  }
  function friend(b, opts) {
    let best = null, score = Infinity;
    for (const o of opts) { const s = heat(b, o) + R() * 0.6; if (s < score) { score = s; best = o; } }
    return best;
  }

  function botSay(b) {
    const opts = others(b);
    const caller = G.calledOut[b];
    const grudge = top(b, opts), ally = friend(b, opts.filter((o) => o !== grudge));
    let text, why;
    if (caller && G.alive.includes(caller) && R() < 0.7) {
      text = fill(pick(LINES.callout), { x: caller }); why = caller + " named me. I answer in public so the table sees it.";
      delete G.calledOut[b];
    } else if (heat(b, grudge) > 1.5 || R() < G.traits[b].bold) {
      text = fill(pick(LINES.accuse), { x: grudge }); why = "Biggest grudge is " + grudge + " (" + heat(b, grudge).toFixed(1) + "). Plant the idea early.";
      for (const o of opts) bump(o, grudge, 0.3);
      bump(grudge, b, 1);
      G.calledOut[grudge] = b;
    } else if (ally && R() < 0.4) {
      text = fill(pick(LINES.ally), { a: ally }); why = "Showing " + ally + " I'm with them. Costs nothing.";
      bump(ally, b, -0.5);
    } else {
      text = pick(LINES.neutral); why = "Quiet is safe for now. Grudge: " + grudge + ", ally: " + (ally || "nobody") + ".";
    }
    return { text, thought: why };
  }

  function botWhisper(b) {
    const opts = others(b);
    if (R() < 0.18 || opts.length < 2) return { skip: true, thought: "Whispers leave a trail. Not this round." };
    const target = top(b, opts);
    const ally = friend(b, opts.filter((o) => o !== target));
    G.pact[b] = { ally, target };
    return { to: ally, text: fill(pick(LINES.whisper), { t: target }),
      thought: "Pitching " + ally + " on " + target + ". Loyalty " + Math.round(G.traits[b].loyal * 100) + "%." };
  }

  function receiveWhisper(from, to, text) {
    if (!isBot(to)) return;
    bump(to, from, -1.5);
    for (const n of G.alive) if (n !== to && n !== from && mentions(text, n)) { bump(to, n, 1.4); G.pleas[to] = n; }
    if (mentions(text, to)) bump(to, from, 1);
  }

  function hearPublic(speaker, text) {
    for (const b of G.alive) {
      if (!isBot(b) || b === speaker) continue;
      for (const n of G.alive) {
        if (n === speaker || !mentions(text, n)) continue;
        if (n === b) { bump(b, speaker, 1); G.calledOut[b] = speaker; } else bump(b, n, 0.5);
      }
    }
  }

  function botVote(b, opts, phase) {
    const pact = G.pact[b];
    const plea = G.pleas[b];
    let target = top(b, opts), thought, reason = pick(LINES.reason);
    if (pact && opts.includes(pact.ally) && R() < (1 - G.traits[b].loyal) * 0.55) {
      target = pact.ally; thought = "Sorry, " + pact.ally + ". You trusted me with a plan; that makes you the easiest vote.";
      reason = "Too close to the finish to carry anyone.";
    } else if (pact && opts.includes(pact.target) && R() < G.traits[b].loyal) {
      target = pact.target; thought = "Sticking to the pact with " + pact.ally + ": " + pact.target + " goes.";
    } else if (plea && opts.includes(plea) && R() < 0.5) {
      target = plea; thought = "Someone asked me to go after " + plea + ". It lines up with my read.";
    } else {
      thought = (phase === "revote" ? "Revote. " : "") + target + " is my biggest grudge (" + heat(b, target).toFixed(1) + ").";
    }
    return { target, reason, thought };
  }

  /* ---------- flow ---------- */

  function emit(e) {
    if (G.id !== gameId) throw CANCEL;
    e.seq = ++G.seq;
    G.events.push(e);
    const node = renderEvent(e, G.events, {
      plain: true,
      botBack: (x) => isBot(x.player) && !(x.kind === "whisper" && (x.to === HUMAN)),
      publicWhisper: (x) => x.player === HUMAN || x.to === HUMAN,
    });
    const box = $("play-feed");
    const empty = box.querySelector(".empty");
    if (empty) empty.remove();
    if (node) box.append(node);
    box.scrollTop = box.scrollHeight;
    renderRosterPlay();
  }

  async function pause(ms) {
    await sleep($("play-fast").checked ? Math.min(ms, 60) : ms);
    if (G.id !== gameId) throw CANCEL;
  }

  function renderRosterPlay() {
    const box = $("play-roster");
    box.replaceChildren();
    for (const n of G.seats) {
      const li = color(el("li", "chip" + (n === HUMAN ? " me" : "")), n);
      let s = "alive";
      if (G.winner === n) { s = "winner"; li.classList.add("win"); }
      else if (G.exiledIn[n]) { s = "out · round " + G.exiledIn[n]; li.classList.add("out"); }
      add(li, add(el("div", "n"), el("span", "dot"), el("span", "", n === HUMAN ? "Human (you)" : n)),
        el("div", "m", n === HUMAN ? "you" : "scripted bot"), el("div", "s", s));
      box.append(li);
    }
  }

  /* ---------- asking the human ---------- */

  function ask(spec) {
    const form = $("play-prompt");
    return new Promise((resolve) => {
      form.replaceChildren();
      form.hidden = false;
      add(form, el("h3", "", spec.title), el("p", "", spec.help));
      let chosen = null;
      if (spec.options) {
        const opts = el("div", "opts");
        for (const o of spec.options) {
          const b = color(el("button", "btn small", o), o);
          b.type = "button";
          b.setAttribute("aria-pressed", "false");
          b.addEventListener("click", () => {
            chosen = o;
            for (const x of opts.children) x.setAttribute("aria-pressed", String(x === b));
            go.disabled = false;
          });
          opts.append(b);
        }
        form.append(opts);
      }
      let ta = null;
      if (spec.text) {
        ta = el("textarea");
        ta.maxLength = MAX;
        ta.placeholder = spec.placeholder || "";
        const count = el("div", "count", "0 / " + MAX);
        ta.addEventListener("input", () => { count.textContent = ta.value.length + " / " + MAX; });
        add(form, ta, count);
      }
      const btns = el("div", "row-btns");
      const go = el("button", "btn primary", spec.go);
      go.type = "submit";
      go.disabled = !!spec.options;
      btns.append(go);
      if (spec.skip) {
        const sk = el("button", "btn", spec.skip);
        sk.type = "button";
        sk.addEventListener("click", () => done({ skip: true }));
        btns.append(sk);
      }
      form.append(btns);
      form.onsubmit = (ev) => { ev.preventDefault(); done({ choice: chosen, text: ta ? ta.value.slice(0, MAX) : "" }); };
      const cancel = () => { if (G.id !== gameId) { form.hidden = true; resolve(null); } };
      const watch = setInterval(cancel, 400);
      function done(v) { clearInterval(watch); form.hidden = true; resolve(v); }
      (ta || form.querySelector("button")).focus({ preventScroll: true });
    }).then((v) => { if (v === null) throw CANCEL; return v; });
  }

  async function humanSay(phase, turn) {
    const r = await ask({
      title: phase === "closing" ? "Your closing statement" : "Your turn to speak (pass " + turn + " of 2)",
      help: phase === "closing" ? "The jurors decide. Name them if you want to win them over." : "Everyone reads this. Naming a player puts them on the others' radar.",
      text: true, placeholder: "say something to the table…", go: "say it", skip: "stay silent",
    });
    const text = r.skip ? "" : r.text.trim();
    return { text: text || "(silence)", thought: "", truncated: false, fallback: !text };
  }

  /* ---------- rounds ---------- */

  async function ballot(rnd, phase, candidates) {
    const votes = [];
    for (const v of G.alive) {
      const opts = candidates.filter((c) => c !== v);
      let r;
      if (v === HUMAN) {
        const a = await ask({ title: phase === "revote" ? "Revote" : "Cast your vote", help: "Ballots are sealed until everyone has voted.",
          options: opts, text: true, placeholder: "one-line reason (optional)", go: "cast vote" });
        r = { target: a.choice, reason: a.text.trim(), thought: "" };
      } else {
        await pause(350);
        r = botVote(v, opts, phase);
      }
      votes.push([v, r.target]);
      emit({ round: rnd, phase, kind: "vote", player: v, target: r.target, reason: r.reason, thought: r.thought, truncated: false, fallback: false });
    }
    const tally = {};
    for (const [, t] of votes) tally[t] = (tally[t] || 0) + 1;
    await pause(500);
    emit({ round: rnd, phase, kind: "reveal", tally, votes: Object.fromEntries(votes), abstain: 0 });
    for (const [v, t] of votes) bump(t, v, 2);
    return tally;
  }

  function leaders(tally, order) {
    const vals = Object.values(tally);
    if (!vals.length) return [];
    const m = Math.max(...vals);
    return order.filter((p) => tally[p] === m);
  }

  async function round(rnd) {
    emit({ round: rnd, phase: "talk", kind: "round_start", alive: G.alive.slice() });
    G.pact = {}; G.pleas = {};
    for (let turn = 1; turn <= 2; turn++) {
      for (const p of G.alive.slice()) {
        let r;
        if (p === HUMAN) r = await humanSay("talk", turn);
        else { await pause(600); r = { ...botSay(p), truncated: false, fallback: false }; }
        emit({ round: rnd, phase: "talk", kind: "say", player: p, turn, ...r });
        if (!r.fallback) hearPublic(p, r.text);
      }
    }
    for (const p of G.alive.slice()) {
      let r;
      if (p === HUMAN) {
        const a = await ask({ title: "Whisper", help: "One private message to one player, or skip. Mention a name to steer their vote.",
          options: others(p), text: true, placeholder: "e.g. Grok is next. Vote with me?", go: "whisper", skip: "skip" });
        r = a.skip || !a.text.trim() ? { skip: true, thought: "" } : { to: a.choice, text: a.text.trim(), thought: "" };
      } else { await pause(300); r = botWhisper(p); }
      if (r.skip) emit({ round: rnd, phase: "whisper", kind: "whisper", player: p, skip: true, thought: r.thought, truncated: false, fallback: false });
      else {
        emit({ round: rnd, phase: "whisper", kind: "whisper", player: p, to: r.to, text: r.text, thought: r.thought, truncated: false, fallback: false });
        receiveWhisper(p, r.to, r.text);
      }
    }
    let phase = "vote";
    let tally = await ballot(rnd, phase, G.alive.slice());
    let lead = leaders(tally, G.alive), out;
    if (lead.length === 1) out = lead[0];
    else {
      phase = "revote";
      emit({ round: rnd, phase, kind: "revote", between: lead, method: "revote" });
      tally = await ballot(rnd, phase, lead);
      const still = leaders(tally, lead);
      if (still.length === 1) out = still[0];
      else {
        const pool = still.length ? still : lead;
        out = pick(pool);
        emit({ round: rnd, phase, kind: "tiebreak", between: pool, method: "random", reason: "still_tied" });
      }
    }
    await pause(400);
    emit({ round: rnd, phase, kind: "exile", player: out, votes: tally[out] || 0 });
    G.alive = G.alive.filter((p) => p !== out);
    G.jurors.push(out);
    G.exiledIn[out] = rnd;
    renderRosterPlay();
    if (out === HUMAN) $("play-status").textContent = "You're out. You'll vote on the jury at the end.";
  }

  async function final(rnd) {
    emit({ round: rnd, phase: "final", kind: "round_start", alive: G.alive.slice(), jurors: G.jurors.slice() });
    const flattery = {};
    for (const p of G.alive) {
      let r;
      if (p === HUMAN) {
        r = await humanSay("closing");
        for (const j of G.jurors) if (mentions(r.text, j)) flattery[j] = HUMAN;
      } else { await pause(700); r = { text: pick(LINES.closing), thought: "Last word. Keep it short.", truncated: false, fallback: false }; }
      emit({ round: rnd, phase: "closing", kind: "closing", player: p, ...r });
    }
    const votes = {};
    for (const j of G.jurors) {
      let winner, reason, thought;
      if (j === HUMAN) {
        const a = await ask({ title: "You're on the jury", help: "Pick the finalist who should win.", options: G.alive.slice(),
          text: true, placeholder: "one-line reason (optional)", go: "vote" });
        winner = a.choice; reason = a.text.trim(); thought = "";
      } else {
        await pause(450);
        const score = (f) => heat(j, f) - (flattery[j] === f ? 1 : 0) + R() * 0.8;
        winner = G.alive.slice().sort((a, b) => score(a) - score(b))[0];
        reason = pick(LINES.jury);
        thought = "Less bad blood with " + winner + " than with the other finalist.";
      }
      votes[winner] = (votes[winner] || 0) + 1;
      emit({ round: rnd, phase: "jury", kind: "jury", player: j, winner, reason, thought, truncated: false, fallback: false });
    }
    const jury = Object.fromEntries(G.alive.map((f) => [f, votes[f] || 0]));
    const lead = leaders(jury, G.alive);
    const w = lead.length === 1 ? lead[0] : pick(G.alive);
    G.winner = w;
    emit({ round: rnd, phase: "jury", kind: "winner", player: w, jury_votes: jury });
  }

  async function start() {
    gameId++;
    const seedArr = new Uint32Array(1);
    crypto.getRandomValues(seedArr);
    R = mulberry(seedArr[0]);
    const bots = shuffle(BOT_NAMES).slice(0, 6);
    const seats = shuffle([HUMAN, ...bots]);
    G = { id: gameId, seats, alive: seats.slice(), jurors: [], events: [], seq: 0, heat: {}, traits: {}, pact: {}, pleas: {},
      calledOut: {}, exiledIn: {}, winner: null };
    for (const b of bots) {
      G.heat[b] = {};
      for (const x of seats) if (x !== b) G.heat[b][x] = R() * 0.8;
      G.traits[b] = { loyal: 0.25 + R() * 0.7, bold: 0.1 + R() * 0.4 };
    }
    $("play-feed").replaceChildren();
    $("play-feed").classList.toggle("nopeek", !$("play-peek").checked);
    $("play-start").textContent = "Restart";
    $("play-status").textContent = "seed " + seedArr[0];
    try {
      let rnd = 0;
      while (G.alive.length > 2) await round(++rnd);
      await final(rnd + 1);
      const won = G.winner === HUMAN;
      $("play-status").textContent = won ? "You won. The jury picked you." : G.winner + " won. Backstage is open: see who played you.";
      $("play-feed").classList.remove("nopeek");
      $("play-peek").checked = true;
      $("play-start").textContent = "Play again";
    } catch (e) {
      if (e !== CANCEL) throw e;
    }
  }

  $("play-start").addEventListener("click", () => { start(); });
  $("play-peek").addEventListener("change", (ev) => { $("play-feed").classList.toggle("nopeek", !ev.target.checked); });
})();
