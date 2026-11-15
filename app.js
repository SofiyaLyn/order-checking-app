"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const ORDER = ["ready", "review", "rejected", "blocked", "hold"];
  const DEC = {
    ready: {label: "Ready", blurb: "Goes to a person for approval"},
    review: {label: "Review", blurb: "Operations asks the client"},
    rejected: {label: "Rejected", blurb: "Client gets a clear reason"},
    blocked: {label: "Blocked", blurb: "Security calls the client back"},
    hold: {label: "Hold", blurb: "Confirm it is not a resend"}
  };
  const STAGES = [
    {t: "Check the sender", d: "Is it really them, and may they act on this account?", ic: "shield"},
    {t: "Read the order", d: "Pull out account, side, instrument and size. Nothing is guessed.", ic: "doc"},
    {t: "Run the rule checks", d: "ISIN, restricted list, duplicates, cash, position, cut-off.", ic: "list"},
    {t: "Decide", d: "The system recommends. A person decides.", ic: "user"}
  ];
  const ICONS = {
    shield: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6z"/><path d="M9 12l2 2 4-4"/></svg>',
    doc: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4M10 12h5M10 16h5"/></svg>',
    list: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6h11M9 12h11M9 18h11"/><path d="M4 6l1 1 2-2M4 12l1 1 2-2M4 18l1 1 2-2"/></svg>',
    user: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4 21c1-4 4-6 8-6s7 2 8 6"/></svg>',
    mail: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="14" rx="3"/><path d="M3.5 7l8.5 6 8.5-6"/></svg>'
  };
  const seeded = window.ORDER_CHECK_DEMO || {cases: [], reference: {clients: []}};
  const state = {
    view: "demo", cases: seeded.cases || [], reference: seeded.reference || {clients: []},
    trial: null, uploads: [], files: [], sel: 0, runId: 0, playing: false, live: false, busy: false,
    processed: null, current: []
  };
  const metaToken = document.querySelector('meta[name="app-session"]');
  const token = metaToken ? metaToken.content : "";
  const fileMode = location.protocol === "file:";
  const reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  const stageOf = (l) => /authentication|authorised signer|may act|suspicious/i.test(l) ? 0 : /interpretation|missing|order schema|order direction/i.test(l) ? 1 : 2;
  const timeText = (c) => { const t = c.time || ""; return /^\d\d:\d\d/.test(t) ? t.slice(0, 5) : (t || "Unverified"); };
  const sizeText = (l) => {
    const p = [];
    if (l.qty !== null && l.qty !== undefined) p.push(Number(l.qty).toLocaleString("en-US") + " units");
    if (l.amount !== null && l.amount !== undefined) p.push((l.currency || "EUR") + " " + Number(l.amount).toLocaleString("en-US") + " (amount)");
    if (p.length) return p.join("; ");
    if (l.half) return "Half (needs a quantity)";
    if (l.all) return "All holdings (needs a quantity)";
    return null;
  };

  function message(text, error) { const n = $("msg"); n.textContent = text || ""; n.classList.toggle("err", !!error); }
  async function api(path, options = {}) {
    const headers = Object.assign({}, options.headers || {});
    if (options.method === "POST") { headers["Content-Type"] = "application/json"; headers["X-Order-Check-Token"] = token; }
    const r = await fetch(path, Object.assign({}, options, {headers, credentials: "same-origin"}));
    let data;
    try { data = await r.json(); } catch (e) { throw new Error("The checker returned an unreadable response. Please restart the local app."); }
    if (!r.ok) throw new Error(data.error || "The checker could not complete this request.");
    return data;
  }
  function setLive(live) {
    state.live = live;
    $("conn-dot").className = live ? "live" : "offline";
    $("conn-text").textContent = live ? "Local checker ready" : "Offline preview";
    const b = $("banner");
    b.hidden = live;
    if (!live) b.textContent = (fileMode || state.staticHost)
      ? "View-only preview: you can browse all the bundled results. To check new instructions, download the app from GitHub and double-click START_MAC.command or START_WINDOWS.bat."
      : "The local checker is unavailable. Start the app with its launcher, then reload this page.";
    updateControls();
  }
  function updateControls() {
    $("check").disabled = !state.live || state.busy;
    $("check-files").disabled = !state.live || state.busy || !state.files.length;
    $("play").disabled = state.playing || !state.cases.length;
    $("export").disabled = !state.current.length;
    $("template").setAttribute("aria-disabled", String(!state.live));
  }

  /* ---------- builders ---------- */
  function buildLegend() {
    $("legend").innerHTML = ORDER.map((k) => `<span><i class="dot ${k}"></i>${DEC[k].label} <b id="lg-${k}">0</b></span>`).join("");
    $("outs").innerHTML = ORDER.map((k) => `<div class="oc ${k}" id="oc-${k}"><b><i class="dot ${k}"></i>${DEC[k].label}</b><p>${DEC[k].blurb}</p></div>`).join("");
    const pipe = $("pipe");
    STAGES.forEach((s, i) => {
      const d = document.createElement("div");
      d.className = "stg"; d.id = "stg" + i;
      d.innerHTML = `<div class="node">${ICONS[s.ic]}<span class="num">${i + 1}</span></div><div><h4>${s.t}</h4><p>${s.d}</p><div class="res" id="res${i}"></div></div>`;
      pipe.appendChild(d);
    });
  }
  function updateTally() {
    const counts = {}; ORDER.forEach((k) => counts[k] = 0);
    state.cases.forEach((c, i) => { if (!state.processed || state.processed.has(i)) counts[c.decision] = (counts[c.decision] || 0) + 1; });
    const total = state.cases.length || 1, t = $("tally");
    t.replaceChildren();
    ORDER.forEach((k) => { const s = document.createElement("i"); s.className = "seg " + k; s.style.width = (counts[k] / total * 100) + "%"; t.appendChild(s); });
    ORDER.forEach((k) => { $("lg-" + k).textContent = counts[k]; });
    $("count").textContent = state.cases.length; $("stat-count").textContent = state.cases.length;
  }
  function listHtml(cases, offlineMark) {
    return cases.map((c, i) => {
      const done = !state.processed || offlineMark || state.processed.has(i);
      return `<button type="button" class="item${i === state.sel ? " sel" : ""}" data-i="${i}"><span class="n">${i + 1}</span><span class="s">${esc(c.subject || c.file || "Untitled")}</span><span class="t">${esc(timeText(c))}</span><span class="f">${esc(c.from || c.file || "")}</span><span class="tag ${done ? esc(c.decision) : "pending"}">${done ? esc((DEC[c.decision] || {label: c.decision}).label) : "…"}</span></button>`;
    }).join("");
  }
  function paintLists() {
    $("list").innerHTML = listHtml(state.cases, false);
    $("file-list").innerHTML = state.uploads.length ? listHtml(state.uploads, true) : "";
  }
  function renderReference() {
    const clients = state.reference.clients || [], opts = [];
    clients.forEach((c) => (c.signers || []).forEach((s) => opts.push(`<option value="${esc(s)}">${esc(s)} · ${esc(c.account)}</option>`)));
    if (!opts.length) opts.push('<option value="anna.mueller@mueller-fo.com">anna.mueller@mueller-fo.com · 100234</option>');
    const prev = $("sender").value;
    $("sender").innerHTML = opts.join("");
    if (prev) $("sender").value = prev;
  }

  /* ---------- render one case ---------- */
  function resetStage() {
    ORDER.forEach((k) => $("oc-" + k).classList.remove("lit"));
    STAGES.forEach((_, s) => { $("stg" + s).className = "stg"; $("res" + s).innerHTML = ""; });
    $("railfill").style.width = "0"; $("packet").classList.remove("on"); $("verdict").innerHTML = "";
  }
  function renderIdle(text) {
    state.runId++; resetStage(); state.current = [];
    $("mail").innerHTML = `<div class="ic">${ICONS.mail}</div><div><h3>Nothing checked yet</h3><div class="meta">${esc(text)}</div></div><span class="src">Waiting</span>`;
    $("order").innerHTML = '<div class="empty">The extracted order appears here.</div>'; $("extras").innerHTML = ""; $("checks").innerHTML = '<div class="empty">Each check appears here, grouped by step.</div>';
    updateControls();
  }
  function renderStatic(c, label) {
    resetStage();
    const evidence = c.auth_mode === "synthetic-demo" ? "" : '<span class="unver">Sender unverified</span>';
    $("mail").innerHTML = `<div class="ic">${ICONS.mail}</div><div><h3>${esc(c.subject || "Untitled instruction")}</h3><div class="meta">${esc(c.from || "Sender unavailable")} · ${esc(timeText(c))} · ${esc(label)}${evidence}</div><div class="body">${esc(c.original_body || "")}</div></div><span class="src">${esc(c.source || "Email")}</span>`;
    const miss = '<span class="missing">missing</span>';
    const rows = (c.lines && c.lines.length) ? c.lines.map((l) => `<tr><td>${l.account ? esc(l.account) : miss}</td><td>${l.side ? esc(l.side) : miss}</td><td>${l.isin ? "<code>" + esc(l.isin) + "</code>" : miss}</td><td>${sizeText(l) ? esc(sizeText(l)) : miss}</td></tr>`).join("")
      : `<tr><td colspan="4"><span class="missing">No usable order lines found</span></td></tr>`;
    $("order").innerHTML = `<table><thead><tr><th>Account</th><th>Side</th><th>Instrument</th><th>Size</th></tr></thead><tbody>${rows}</tbody></table>`;
    let ex = "";
    if (c.suggestion) ex += `<details><summary>Reviewer suggestion</summary><p>${esc(c.suggestion)}</p></details>`;
    if (c.reply) ex += `<details><summary>Draft message (never sent automatically)</summary><p>${esc(c.reply)}</p></details>`;
    ex += `<details><summary>Technical reference</summary><p>${esc(c.file || "")}${c.order_ref ? " · " + esc(c.order_ref) : ""}${c.source ? " · " + esc(c.source) : ""}</p></details>`;
    $("extras").innerHTML = ex;
    const groups = [[], [], []]; (c.checks || []).forEach((k) => groups[stageOf(k.label)].push(k));
    const mark = {PASS: "✓", WARN: "!", FAIL: "✕", SKIP: "–"};
    $("checks").innerHTML = [0, 1, 2].map((g) => `<div class="grp"><h5><span>${g + 1}</span>${STAGES[g].t}</h5>${groups[g].length ? groups[g].map((k) => `<div class="ck"><span class="ico ${esc(k.status)}">${mark[k.status] || "?"}</span><div>${esc(k.label)}${k.detail ? "<small>" + esc(k.detail) + "</small>" : ""}</div></div>`).join("") : '<div class="ck"><span class="ico SKIP">–</span><div>No checks in this step</div></div>'}</div>`).join("");
  }
  function stageResult(c, s) {
    const ks = (c.checks || []).filter((k) => stageOf(k.label) === s), n = {PASS: 0, WARN: 0, FAIL: 0, SKIP: 0};
    ks.forEach((k) => { n[k.status] = (n[k.status] || 0) + 1; });
    const partial = !n.FAIL && !n.WARN && n.SKIP > 0;
    const status = n.FAIL ? "fail" : (n.WARN || partial) ? "warn" : "pass";
    const empty = !ks.length;
    const head = n.FAIL ? n.FAIL + " failed" : n.WARN ? n.WARN + " to clarify" : partial ? "Not fully run" : empty ? "Read cleanly" : "All clear";
    const first = ks.find((k) => k.status === "FAIL") || ks.find((k) => k.status === "WARN") || (partial ? ks.find((k) => k.status === "SKIP") : null);
    return {status, html: `<div class="dots">${ks.map((k) => `<i class="${esc(k.status)}"></i>`).join("")}</div><b>${head}</b><small>${first ? esc(first.label) : empty ? "No issues found" : n.PASS + " check" + (n.PASS === 1 ? "" : "s") + " passed"}</small>`};
  }
  function movePacket(s, instant) {
    const pr = $("pipe").getBoundingClientRect(), r = $("stg" + s).querySelector(".node").getBoundingClientRect(), p = $("packet");
    if (instant) p.style.transition = "none";
    p.style.transform = `translate(${r.left - pr.left + r.width / 2}px,${r.top - pr.top + r.height / 2}px)`;
    if (instant) { void p.offsetHeight; p.style.transition = ""; }
  }
  async function run(c, label, speed = 1) {
    const id = ++state.runId;
    renderStatic(c, label);
    const wait = (ms) => sleep(reduce ? 20 : ms * speed), wide = matchMedia("(min-width:721px)").matches;
    if (wide) { movePacket(0, true); $("packet").classList.add("on"); }
    await wait(250); if (id !== state.runId) return;
    for (let s = 0; s < 4; s++) {
      STAGES.forEach((_, k) => { if (k !== s) $("stg" + k).classList.remove("active"); });
      $("stg" + s).classList.add("active");
      if (wide) { movePacket(s); $("railfill").style.width = (s / 3 * 75) + "%"; }
      await wait(650); if (id !== state.runId) return;
      const n = $("stg" + s); n.classList.remove("active");
      if (s < 3) { const r = stageResult(c, s); n.classList.add(r.status, "done"); $("res" + s).innerHTML = r.html; }
      else {
        n.classList.add(c.decision === "ready" ? "pass" : (c.decision === "review" || c.decision === "hold") ? "warn" : "fail", "done");
        $("res3").innerHTML = `<b>${esc((DEC[c.decision] || {label: c.decision}).label)}</b><small>Owner: ${esc(c.owner || "Operations")}</small>`;
      }
    }
    $("packet").classList.remove("on");
    const lit = $("oc-" + c.decision); if (lit) lit.classList.add("lit");
    $("verdict").innerHTML = `<div class="vk">Why</div><div><p>${esc(c.reason || "Review the check results.")}</p><dl><dt>Proposed owner</dt><dd>${esc(c.owner || "Operations")}</dd><dt>Next action</dt><dd>${esc(c.next_action || "Independent review")}</dd></dl></div>`;
  }

  /* ---------- navigation ---------- */
  function select(i) {
    const list = state.view === "files" ? state.uploads : state.cases;
    if (!list[i]) return;
    state.sel = i; state.current = state.view === "files" ? state.uploads : state.cases; updateControls(); paintLists();
    run(list[i], "email " + (i + 1) + " of " + list.length);
  }
  function switchView(v) {
    if (state.playing) return;
    state.view = v;
    document.querySelectorAll(".tab").forEach((t) => { const on = t.dataset.view === v; t.classList.toggle("on", on); t.setAttribute("aria-selected", String(on)); });
    ["demo", "trial", "files"].forEach((x) => { $("side-" + x).hidden = x !== v; });
    message("");
    if (v === "demo") { state.sel = Math.min(state.sel, Math.max(0, state.cases.length - 1)); select(state.sel); }
    else if (v === "trial") { if (state.trial) { state.current = [state.trial]; updateControls(); run(state.trial, "Your test instruction"); } else renderIdle("Fill in the form and press Check instruction."); }
    else { if (state.uploads.length) { state.sel = 0; select(0); } else renderIdle("Choose .eml files and press Check selected emails."); }
  }
  document.querySelectorAll(".tab").forEach((t, i, all) => {
    t.addEventListener("click", () => switchView(t.dataset.view));
    t.addEventListener("keydown", (e) => {
      let n; if (e.key === "ArrowRight") n = (i + 1) % all.length; else if (e.key === "ArrowLeft") n = (i + all.length - 1) % all.length;
      if (n !== undefined) { e.preventDefault(); all[n].focus(); switchView(all[n].dataset.view); }
    });
  });
  $("list").addEventListener("click", (e) => { const b = e.target.closest(".item"); if (b && !state.playing) select(+b.dataset.i); });
  $("file-list").addEventListener("click", (e) => { const b = e.target.closest(".item"); if (b) select(+b.dataset.i); });

  async function playAll() {
    if (state.playing || !state.cases.length) return;
    state.playing = true; state.processed = new Set(); paintLists(); updateTally();
    const btn = $("play"); btn.querySelector("span").textContent = "Running…"; updateControls();
    for (let i = 0; i < state.cases.length; i++) {
      state.sel = i; paintLists();
      const el = document.querySelector('#list .item[data-i="' + i + '"]'); if (el) el.scrollIntoView({block: "nearest"});
      await run(state.cases[i], "email " + (i + 1) + " of " + state.cases.length, .45);
      state.processed.add(i); paintLists(); updateTally();
      await sleep(reduce ? 20 : 350);
    }
    state.playing = false; state.processed = null; paintLists(); updateTally();
    btn.querySelector("span").textContent = "Run all again"; updateControls();
  }
  $("play").addEventListener("click", playAll);

  /* ---------- live features ---------- */
  const examples = {
    valid: {subject: "Order instruction", body: "Please buy 100 units of IE00WRLD0013 for account 100234."},
    ambiguous: {subject: "Selling", body: "Can you sell half of my US funds please?"},
    mixed: {subject: "Portfolio instructions", body: "Please buy 10 units of IE00WRLD0013 and sell 20 units of IE00ALLW0020 for account 100234."}
  };
  document.querySelectorAll("[data-example]").forEach((b) => b.addEventListener("click", () => {
    const ex = examples[b.dataset.example]; $("subject").value = ex.subject; $("body").value = ex.body; $("workbook").value = ""; $("authfail").checked = false;
    message("Example filled in. You can edit it before checking.");
  }));
  function validateFile(file, ext, max) {
    if (!file.name.toLowerCase().endsWith(ext)) throw new Error("Please select " + ext + " files only.");
    if (file.size > max) throw new Error(file.name + " exceeds the supported file size.");
  }
  const readBase64 = (file) => new Promise((resolve, reject) => { const r = new FileReader(); r.onload = () => resolve(String(r.result).split(",", 2)[1]); r.onerror = () => reject(new Error("Could not read " + file.name)); r.readAsDataURL(file); });
  $("workbook").addEventListener("change", () => {
    const f = $("workbook").files[0]; if (!f) return;
    try { validateFile(f, ".xlsx", 5 * 1024 * 1024); if ($("body").value === examples.valid.body) { $("body").value = "Please process the attached instruction."; message("The email text now refers to the attached workbook."); } }
    catch (e) { $("workbook").value = ""; message(e.message, true); }
  });
  $("trial-form").addEventListener("submit", async (e) => {
    e.preventDefault(); if (!state.live || state.busy) return;
    state.busy = true; updateControls(); message("Checking the synthetic instruction…");
    try {
      const payload = {sender: $("sender").value, subject: $("subject").value, body: $("body").value, received_at: $("received").value, simulate_auth_failure: $("authfail").checked};
      const f = $("workbook").files[0];
      if (f) { validateFile(f, ".xlsx", 5 * 1024 * 1024); payload.attachment = {name: f.name, data_base64: await readBase64(f)}; }
      const data = await api("/api/check", {method: "POST", body: JSON.stringify(payload)});
      state.trial = data.case; state.current = [data.case]; updateControls();
      message("Instruction checked. The result is a recommendation for Operations.");
      run(data.case, "Your test instruction");
    } catch (err) { message(err.message, true); } finally { state.busy = false; updateControls(); }
  });
  $("template").addEventListener("click", (e) => { if (!state.live) e.preventDefault(); });
  function updatePicked() {
    state.files = Array.from($("eml").files || []);
    try {
      if (state.files.length > 20) throw new Error("Select no more than 20 email files.");
      state.files.forEach((f) => validateFile(f, ".eml", 10 * 1024 * 1024));
      if (state.files.reduce((n, f) => n + f.size, 0) > 14 * 1024 * 1024) throw new Error("The selected files exceed 14 MB in total.");
      $("picked").innerHTML = state.files.map((f) => `<li>${esc(f.name)} · ${Math.max(1, Math.round(f.size / 1024))} KB</li>`).join("");
      message(state.files.length ? state.files.length + " email files selected." : "");
    } catch (err) { state.files = []; $("eml").value = ""; $("picked").innerHTML = ""; message(err.message, true); }
    updateControls();
  }
  $("eml").addEventListener("change", updatePicked);
  $("clear-files").addEventListener("click", () => { $("eml").value = ""; updatePicked(); });
  $("check-files").addEventListener("click", async () => {
    if (!state.live || state.busy || !state.files.length) return;
    state.busy = true; updateControls(); message("Reviewing local email files…");
    try {
      const files = await Promise.all(state.files.map(async (f) => ({name: f.name, data_base64: await readBase64(f)})));
      const data = await api("/api/files", {method: "POST", body: JSON.stringify({files})});
      state.uploads = data.cases || []; state.sel = 0;
      message(state.uploads.length + " local files reviewed. Sender evidence remains unverified.");
      select(0);
    } catch (err) { message(err.message, true); } finally { state.busy = false; updateControls(); }
  });
  $("export").addEventListener("click", () => {
    if (!state.current.length) return;
    const blob = new Blob([JSON.stringify({exported_at: new Date().toISOString(), scope: "Local review recommendations. No approval or execution.", cases: state.current}, null, 2)], {type: "application/json"});
    const url = URL.createObjectURL(blob), a = document.createElement("a");
    a.href = url; a.download = "order_check_results.json"; document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    message("Results downloaded as JSON.");
  });

  /* ---------- start ---------- */
  buildLegend(); renderReference(); paintLists(); updateTally(); setLive(false); select(0);
  if (!fileMode) {
    api("/api/health").then((d) => {
      if (d.status !== "ok") throw new Error("The local checker is not ready.");
      setLive(true);
      return api("/api/samples");
    }).then((data) => {
      state.cases = data.cases || state.cases; state.reference = data.reference || state.reference;
      renderReference(); updateTally(); if (state.view === "demo") select(0);
    }).catch(() => { state.staticHost = true; setLive(false); });
  }
})();
