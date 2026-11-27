/* FinTreX Analyst — single-page front end (no build step, no CDN).
   Every number on screen comes from the server: tool envelopes, the validated explanation, the frozen snapshot or the
   frozen evaluation reports. This file only formats and arranges them. */
"use strict";

// ------------------------------------------------------------------ constants
const ICON = {
  arrow: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>',
  replay: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v5h5"/></svg>',
};
const ACTION_C = {
  HOLD: "--mute", WATCH: "--info", INVESTIGATE: "--warn", POTENTIAL_CATCH_UP_CANDIDATE: "--pos",
  TECHNICAL_REVERSAL_CANDIDATE: "--pos", FUNDAMENTAL_IMPROVEMENT_CANDIDATE: "--pos", REJECT_SIGNAL: "--violet",
  ANALYSIS_UNSAFE: "--neg",
};
const GATE_C = { PASS: "--pos", PASS_WITH_WARNINGS: "--info", INVESTIGATE: "--warn", ANALYSIS_UNSAFE: "--neg", HARD_BLOCK: "--neg" };
const GATE_LABEL = { PASS: "Geçti", PASS_WITH_WARNINGS: "Uyarılarla geçti", INVESTIGATE: "İnceleme gerekli", ANALYSIS_UNSAFE: "Güvensiz", HARD_BLOCK: "Sert blok" };
const VERDICT = { ACCEPT: "Kabul", MODIFY: "Değiştir", REJECT: "Reddet", PENDING: "Bekliyor" };
const STATE_DESC = {
  START: "Analiz kaydı açılıyor; politika ve veri sürümü kilitleniyor.",
  SELECT_UNIVERSE: "Hisseler 30 hisselik sabit evrende doğrulanıyor.",
  LOAD_MARKET_DATA: "Fiyat ve endeks serileri yalnızca analiz tarihine kadar okunuyor.",
  CHECK_DATA_QUALITY: "Eksik gün, sıçrama, düzeltme ve sızıntı kontrolü. Atlanamaz.",
  CALCULATE_TECHNICALS: "Bollinger, RSI, KAMA, Supertrend, Ichimoku, destek ve direnç.",
  RUN_SECTOR_RELATIVE_ANALYSIS: "Hisse, sektördeki diğer üyelerin medyanıyla karşılaştırılıyor.",
  RUN_PATTERN_AND_REVERSAL_ANALYSIS: "Olaylar ve ileri getiriler; eksik ileri pencereler istatistiğe alınmıyor.",
  LOAD_FUNDAMENTALS: "Yalnızca o tarihte KAP'ta yayımlanmış bilançolar okunuyor.",
  LOAD_MACRO_CONTEXT: "Kur, TCMB ve Fed faizi, TÜFE: yayım tarihine göre.",
  LOAD_NEWS_AND_SPEECH_CONTEXT: "Zaman damgalı haber ve konuşma bağlamı. Kanıt değil, bağlam.",
  BUILD_EVIDENCE: "Gözlenen bağlam ile açıklamada kullanılabilecek kanıtlar ayrılıyor.",
  PREVIEW_STRATEGIES: "Kural tabanlı strateji varyantları ön izleniyor.",
  RUN_BACKTEST: "Sinyal t kapanışında, işlem t+1 açılışında; maliyet ve XU100 kıyası. Atlanamaz.",
  RISK_GATE: "Örneklem, sızıntı ve veri kalitesi izinli eylemleri belirliyor. Atlanamaz.",
  GENERATE_EXPLANATION: "Yerel model yazıyor; denetleyici her sayıyı kanıtla karşılaştırıyor.",
  HUMAN_REVIEW: "Karar kaydediliyor. Son söz insan incelemesinde.",
  LOG_AND_CLOSE: "Tüm adımlar replay için episodik belleğe yazılıyor.",
};
const CHECK_TR = {
  schema: "JSON şeması", action_allowed: "Eylem risk kapısına uygun", candidate_cites_backtest: "Aday etiketi backtest'e atıflı",
  citations_exist: "Atıf yapılan kanıtlar mevcut", has_citation: "En az bir kanıt atfı", numbers: "Her sayı kanıtta var",
  dates: "Her tarih kanıtta var", forbidden: "Yasaklı ifade yok", refusal: "Tavsiye talebinde ret",
};
const EVENT_TR = {
  BB_LOWER_REVERSAL: "Alt Bollinger dönüşü", BB_LOWER_TOUCH: "Alt Bollinger dokunuşu", BB_UPPER_TOUCH: "Üst Bollinger dokunuşu",
  BB_UPPER_REVERSAL: "Üst Bollinger dönüşü", BB_MIDDLE_TEST_FROM_ABOVE: "Orta banda yukarıdan test",
  BB_MIDDLE_TEST_FROM_BELOW: "Orta banda aşağıdan test", RSI_LOCAL_TROUGH: "RSI yerel dibi", RSI_TROUGH_VOLUME: "RSI dibi + hacim",
  RSI_LOCAL_PEAK: "RSI yerel tepesi", RSI_BULLISH_DIVERGENCE: "RSI pozitif uyumsuzluk", RSI_BEARISH_DIVERGENCE: "RSI negatif uyumsuzluk",
  SUPERTREND_BULLISH_FLIP: "Supertrend yukarı", SUPERTREND_BEARISH_FLIP: "Supertrend aşağı", KAMA_BULLISH_TURN: "KAMA yukarı dönüşü",
  KAMA_BEARISH_TURN: "KAMA aşağı dönüşü", ICHIMOKU_BULLISH_BREAKOUT: "Ichimoku bulut üstü kırılım",
  ICHIMOKU_BEARISH_BREAKDOWN: "Ichimoku bulut altı kırılım", SUPPORT_TOUCH: "Destek dokunuşu", RESISTANCE_TOUCH: "Direnç dokunuşu",
  TREND_REVERSAL_EVENT: "Trend dönüş olayı", STRONG_REVERSAL_EVENT: "Güçlü birleşik dönüş",
};
const VARIANT_TR = {
  A_TECH: "Teknik", B_TECH_SECTOR: "Teknik + sektör", C_TECH_SECTOR_FUND: "Teknik + sektör + temel",
  D_FULL_STRUCTURED: "Tüm yapısal veri", E_FULL_CONTEXTUAL: "Yapısal + bağlam",
};
const ABLATION = [
  ["A", "Yalın LLM", "Araç yok, kanıt yok"],
  ["B", "+ MCP araçları", "Model araç çağırır"],
  ["C", "+ Stateful harness", "17 adım, izin haritası"],
  ["D", "+ Kanıt seti + kapı", "Denetleyici + kapı eşlemesi"],
  ["E", "+ Bellek + insan", "İz kaydı + replay"],
];
const REF_RE = /\s?\(?\b(E\d{1,3}(?:,\s*E\d{1,3})*)\)?/g;

// ------------------------------------------------------------------ state
const S = {
  meta: null, status: null, settings: loadSettings(), run: null,
  chartTicker: null, chartMode: "price", variant: null, verdict: "ACCEPT",
  history: null, open: null, system: null, tape: {},
};
let runSeq = 0;
let ticker = null;
let observer = null;

function loadSettings() {
  const d = { as_of: null, explainer: "llm", planner: "llm" };
  try { return { ...d, ...JSON.parse(localStorage.getItem("fintrex.settings") || "{}") }; } catch { return d; }
}
function saveSettings() { try { localStorage.setItem("fintrex.settings", JSON.stringify(S.settings)); } catch { /* private mode */ } }

// ------------------------------------------------------------------ helpers
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const trNum = (x, d = 2) => Number(x).toLocaleString("tr-TR", { minimumFractionDigits: d, maximumFractionDigits: d });
const pad2 = (n) => String(n).padStart(2, "0");
function pct(x, d = 2, signed = false) {
  if (x === null || x === undefined || Number.isNaN(x)) return "–";
  const v = x * 100;
  return (v < 0 ? "-" : signed && v > 0 ? "+" : "") + "%" + trNum(Math.abs(v), d);
}
function fmtDate(iso) { if (!iso) return "–"; const [y, m, d] = String(iso).slice(0, 10).split("-"); return `${d}.${m}.${y}`; }
function fmtDateTime(iso) {
  if (!iso) return "–";
  const dt = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + "Z");
  return Number.isNaN(dt.getTime()) ? iso : dt.toLocaleString("tr-TR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}
function toast(msg, err = false) {
  const t = $("#toast");
  t.textContent = msg; t.className = "show" + (err ? " err" : "");
  clearTimeout(toast.h); toast.h = setTimeout(() => (t.className = ""), 3600);
}
async function api(path, body) {
  const opts = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch(path, opts);
  let data = null;
  try { data = await r.json(); } catch { /* not JSON */ }
  if (!r.ok) throw new Error((data && data.error) || `HTTP ${r.status}`);
  return data;
}
const modelReady = () => !!(S.status && S.status.online && S.status.installed);
const tickerInfo = (t) => (S.meta?.tickers || []).find((x) => x.ticker === t) || { ticker: t, name: t, sector: "" };
const isLlm = (e) => !!e && !String(e).startsWith("template");
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const label = (text, cls = "") => `<span class="label ${cls}">${text}</span>`;
const refs = (html) => html.replace(REF_RE, (m, ids) => ids.split(/,\s*/).map((id) => `<button class="ref" data-ev="${id}">${id.slice(1)}</button>`).join(""));

function reveal(root = document) {
  if (!observer) {
    observer = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (!e.isIntersecting) continue;
        e.target.classList.add("in");
        observer.unobserve(e.target);
        $$("[data-count]", e.target).forEach(countUp);
      }
    }, { threshold: 0.12 });
  }
  $$(".rv:not(.in)", root).forEach((el) => observer.observe(el));
}
function countUp(el) {
  if (el.dataset.done) return;
  el.dataset.done = "1";
  const to = Number(el.dataset.count), pre = el.dataset.pre || "", suf = el.dataset.suf || "";
  const t0 = performance.now(), dur = 1400;
  const step = (t) => {
    const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3);
    el.innerHTML = pre + trNum(to * e, 0) + suf;
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

function footer() {
  return `<footer class="foot wrap">
    <div class="foot-row">${label("Eğitsel araştırma aracı — yatırım tavsiyesi değildir")}${label("Model, veri ve hesaplar bu bilgisayarda")}${label("CSE-481 · Akdeniz Üniversitesi · 2026")}</div>
    <div class="giant" aria-hidden="true">FinTre<i>X</i></div>
  </footer>`;
}

// ------------------------------------------------------------------ boot & routing
async function boot() {
  try { S.meta = await api("/api/meta"); } catch (e) {
    $("#view").innerHTML = `<div class="wrap"><p class="empty">Sunucuya bağlanılamadı: ${esc(e.message)}</p></div>`;
    return;
  }
  if (!S.settings.as_of) S.settings.as_of = S.meta.as_of_default;
  await refreshStatus();
  setInterval(refreshStatus, 20000);
  window.addEventListener("hashchange", route);
  document.addEventListener("click", onClick);
  document.addEventListener("mouseover", onHover);
  document.addEventListener("mouseout", onHover);
  route();
}

async function refreshStatus() {
  try { S.status = await api("/api/status"); } catch { S.status = null; }
  const el = $("#status");
  if (!S.status) el.innerHTML = '<span class="pulse off"></span><span class="txt">SUNUCU YOK</span>';
  else if (modelReady()) {
    el.innerHTML = `<span class="pulse on"></span><span class="txt">${esc(S.status.model)} — YEREL</span>`;
    el.title = "Ollama bu bilgisayarda çalışıyor. Model kimliği " + String(S.status.digest || "").slice(0, 12);
  } else {
    el.innerHTML = '<span class="pulse off"></span><span class="txt">MODEL KAPALI — ŞABLON</span>';
    el.title = S.status.online ? `Ollama açık ama ${S.status.model} kurulu değil` : "Ollama çalışmıyor: açıklamalar kural tabanlı şablonla üretilir";
  }
}

function route() {
  const h = location.hash.replace(/^#\/?/, "");
  if (h === "yeni") { S.run = null; runSeq++; history.replaceState(null, "", "#/"); }
  const qi = h.indexOf("?");
  if (qi >= 0 && !h.startsWith("kayit") && !h.startsWith("yontem")) {
    const params = new URLSearchParams(h.slice(qi + 1));
    history.replaceState(null, "", "#/");
    for (const k of ["explainer", "planner"]) if (params.get(k)) S.settings[k] = params.get(k);
    if (params.get("as_of")) S.settings.as_of = params.get("as_of");
    const g = S.meta.golden.find((x) => x.id === params.get("golden"));
    if (g) return ask(g.question, g.request, params.get("bolum"));
    if (params.get("q")) return ask(params.get("q"), null, params.get("bolum"));
  }
  const name = h.startsWith("kayit") ? "history" : h.startsWith("yontem") ? "how" : "analyze";
  $$(".nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === name));
  stopTick();
  if (name === "history") renderHistory();
  else if (name === "how") renderHow();
  else if (S.run) renderAnalysis();
  else renderHome();
  window.scrollTo({ top: 0, behavior: "instant" });
}

// ------------------------------------------------------------------ composer
function askOpts() {
  const ready = modelReady();
  const pl = ready ? S.settings.planner : "scenario";
  const ex = ready ? S.settings.explainer : "template";
  const dis = ready ? "" : "disabled";
  return `<div class="ask-opts">
    <label class="opt">${label("Analiz tarihi")}<input type="date" id="asof" value="${esc(S.settings.as_of)}" min="2024-03-01" max="${esc(S.meta.data_last_day || "")}"></label>
    <span class="opt">${label("Planlama")}<span class="toggle" data-setting="planner"><button type="button" class="${pl === "llm" ? "on" : ""}" data-v="llm" ${dis}>Model</button><button type="button" class="${pl === "scenario" ? "on" : ""}" data-v="scenario">Kural</button></span></span>
    <span class="opt">${label("Açıklama")}<span class="toggle" data-setting="explainer"><button type="button" class="${ex === "llm" ? "on" : ""}" data-v="llm" ${dis}>Model</button><button type="button" class="${ex === "template" ? "on" : ""}" data-v="template">Şablon</button></span></span>
    ${ready ? "" : '<span class="note-warn">Ollama kapalı — kural ve şablon modu</span>'}
  </div>`;
}
function bindComposer() {
  const form = $("#ask"), q = $("#q");
  if (!form) return;
  const grow = () => { q.style.height = "auto"; q.style.height = q.scrollHeight + "px"; };
  q.addEventListener("input", grow);
  q.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); } });
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = q.value.trim();
    if (text.length < 3) { toast("Önce bir soru yazın."); q.focus(); return; }
    ask(text, null);
  });
  $("#asof")?.addEventListener("change", (e) => { S.settings.as_of = e.target.value; saveSettings(); loadTape(); });
}

// ------------------------------------------------------------------ home
function renderHome() {
  const qrow = (id, title, text, tag, data) => `
    <button class="qrow" ${data}>
      <span class="qid">${esc(id)}</span>
      <span class="qtext">${esc(title)}${text ? `<small>${esc(text)}</small>` : ""}</span>
      <span class="qtag">${esc(tag)}</span>
      <span class="qarrow">${ICON.arrow}</span>
    </button>`;
  const golden = S.meta.golden.map((g) => qrow(`(${g.id})`, g.title, g.question, g.scenario_label, `data-golden="${esc(g.id)}"`)).join("");
  const free = S.meta.examples.map((e, i) => qrow(`(S${i + 1})`, e.question, "", e.tag, `data-example="${esc(e.question)}"`)).join("");
  $("#view").innerHTML = `
    <section class="hero wrap">
      <div class="hero-meta">${label("BIST 30 — Point-in-time")}${label("Yerel yapay zekâ — bulut yok")}${label("v1.0 — 2026")}</div>
      <h1><span class="line-mask"><span>Kanıtı olmayan</span></span><span class="line-mask"><span><em>sayı</em> yok.</span></span></h1>
      <div class="hero-grid">
        <p class="lead rv">FinTreX Analyst, Borsa İstanbul sorularını <b>yerel bir dil modeli</b> ve <b>deterministik araçlarla</b> cevaplar.
          Model soruyu anlar ve plan yapar; hesapları kod yapar, yalnızca o tarihte bilinen veriyle. Açıklamadaki her sayının bir kaynağı vardır. Son kararı siz verirsiniz.</p>
        <div class="principles rv">
          <div>${label("01")}<b>Model önerir.</b><span>Soru anlama ve araç planı</span></div>
          <div>${label("02")}<b>Kod doğrular.</b><span>15 araç, risk kapısı, denetleyici</span></div>
          <div>${label("03")}<b>İnsan onaylar.</b><span>Kabul, değişiklik, ret ve replay</span></div>
        </div>
      </div>
      <form class="ask rv" id="ask">
        ${label("Sorunuz", "ink")}
        <div class="ask-row" style="margin-top:12px">
          <textarea id="q" rows="1" placeholder="Aselsan'da alt Bollinger'a değince fiyat toparlanıyor mu?"></textarea>
          <button class="go" type="submit" aria-label="Analiz et">${ICON.arrow}</button>
        </div>
        ${askOpts()}
      </form>
    </section>
    <div class="tape" id="tape" aria-label="Analiz tarihindeki kapanış fiyatları"><div class="tape-track" id="tape-track"></div></div>
    <section class="section wrap">
      <div class="section-head rv"><h2>Referans <em>soruları</em></h2><p>Ders şartnamesindeki beş senaryo, 10.09.2026 tarihli. Tıklayınca doğrudan çalışır; soru anlama adımı atlanır.</p></div>
      <div class="qlist rv">${golden}</div>
    </section>
    <section class="section wrap">
      <div class="section-head rv"><h2>Serbest <em>Türkçe</em></h2><p>Model önce soruyu senaryoya, hisselere ve parametrelere çevirir. Kod her hisseyi sorudaki adla doğrular; dayanağı olmayan soru analiz edilmez.</p></div>
      <div class="qlist rv">${free}</div>
    </section>
    ${footer()}`;
  bindComposer();
  loadTape();
  reveal();
}

async function loadTape() {
  const track = $("#tape-track");
  if (!track) return;
  const key = S.settings.as_of;
  try { if (!S.tape[key]) S.tape[key] = (await api("/api/tape?as_of=" + encodeURIComponent(key))).rows; } catch { return; }
  const rows = S.tape[key];
  if (!rows.length) { $("#tape").classList.add("hidden"); return; }
  $("#tape").classList.remove("hidden");
  const item = (r) => `<span class="tape-item"><b>${esc(r.ticker)}</b><span>${esc(tickerInfo(r.ticker).name)}</span>${trNum(r.close, 2)}<i>●</i></span>`;
  const lead = `<span class="tape-item"><b>KAPANIŞ</b><span>${fmtDate(key)} itibarıyla</span></span>`;
  const once = lead + rows.map(item).join("");
  track.innerHTML = once + once;
}

// ------------------------------------------------------------------ analysis: run
async function ask(question, request, focus) {
  const seq = ++runSeq;
  S.run = { seq, question, phase: request ? "running" : "understanding", understood: null, job: null, result: null, t0: Date.now(), focus };
  S.chartTicker = null; S.variant = null; S.verdict = "ACCEPT";
  $$(".nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === "analyze"));
  if (location.hash.replace(/^#\/?/, "") !== "") history.replaceState(null, "", "#/");
  renderAnalysis();
  window.scrollTo({ top: 0, behavior: "instant" });
  try {
    let req = request;
    if (!req) {
      const u = await api("/api/understand", { question, as_of: S.settings.as_of, mode: modelReady() ? "llm" : "rules" });
      if (seq !== runSeq) return;
      S.run.understood = u;
      if (!u.ok) { S.run.phase = "declined"; renderAnalysis(); return; }
      req = u.request;
    } else {
      req = { ...req, as_of_date: S.settings.as_of };
      const g = S.meta.golden.find((x) => x.question === question);
      S.run.understood = { ok: true, method: "golden", notes: [], request: req, scenario_label: g?.scenario_label, tickers: req.tickers.map(tickerInfo) };
    }
    S.run.phase = "running";
    renderAnalysis();
    const ready = modelReady();
    const { job_id } = await api("/api/analyze", { request: req, explainer: ready ? S.settings.explainer : "template", planner: ready ? S.settings.planner : "scenario" });
    poll(job_id, seq);
  } catch (e) {
    if (seq !== runSeq) return;
    S.run.phase = "error"; S.run.error = e.message; renderAnalysis();
  }
}

async function poll(id, seq) {
  if (seq !== runSeq) return;
  let j;
  try { j = await api("/api/jobs/" + id); } catch { setTimeout(() => poll(id, seq), 1200); return; }
  if (seq !== runSeq) return;
  S.run.job = j;
  if (j.status === "running") { updateRun(); setTimeout(() => poll(id, seq), 400); }
  else if (j.status === "done") { S.run.result = j.result; S.run.phase = "done"; renderAnalysis(); }
  else { S.run.phase = "error"; S.run.error = j.error; renderAnalysis(); }
}

function stopTick() { if (ticker) { clearInterval(ticker); ticker = null; } }
function startTick() {
  stopTick();
  ticker = setInterval(() => {
    const el = $("#elapsed");
    if (!el || !S.run) return stopTick();
    el.textContent = trNum((Date.now() - S.run.t0) / 1000, 1) + " sn";
  }, 100);
}

// ------------------------------------------------------------------ analysis: page
function renderAnalysis() {
  stopTick();
  const r = S.run, u = r.understood, res = r.result;
  const crumbs = [];
  if (u && u.ok) {
    crumbs.push(label(esc(u.scenario_label || ""), "ink"));
    (u.tickers || []).forEach((t) => crumbs.push(label(`${esc(t.ticker)} — ${esc(t.name)}`)));
  }
  crumbs.push(label("as_of " + fmtDate(S.settings.as_of)));
  if (u?.method) crumbs.push(label(u.method === "llm" ? "Soruyu yerel model anladı" : u.method === "golden" ? "Referans soru" : "Soruyu kurallar anladı"));
  if (res) crumbs.push(label(trNum(res.seconds, 1) + " sn"));
  const notes = (u?.notes || []).map((n) => `<span class="label sig">↳ ${esc(n)}</span>`).join("");
  let body;
  if (r.phase === "understanding" || r.phase === "running") body = runView();
  else if (r.phase === "declined") body = `<section class="stop wrap"><h2>Bu soru <em>analiz edilmedi.</em></h2><p>${esc(u.message || "Soru 30 hisselik evrende bir analize çevrilemedi.")} Sistem dayanağı olmayan bir soru için sayı üretmek yerine durur.</p></section>`;
  else if (r.phase === "error") body = `<section class="stop wrap"><h2>Analiz <em>tamamlanamadı.</em></h2><p>${esc(r.error)}</p></section>`;
  else body = resultView(res);
  $("#view").innerHTML = `
    <div class="wrap">
      <form class="mini-ask" id="ask"><textarea id="q" rows="1" placeholder="Yeni bir soru sorun…"></textarea><button class="go" type="submit" aria-label="Analiz et">${ICON.arrow}</button></form>
      <header class="a-head">
        <div class="crumbs">${crumbs.join("")}</div>
        <h1><q>${esc(r.question)}</q></h1>
        ${notes ? `<div class="notes">${notes}</div>` : ""}
      </header>
    </div>
    ${body}
    ${r.phase === "done" ? footer() : ""}`;
  bindComposer();
  if (r.phase === "understanding" || r.phase === "running") { updateRun(); startTick(); }
  if (r.phase === "done") afterResult();
  reveal();
}

function steps() {
  const r = S.run;
  if (r.result) return r.result.states;
  if (r.job) return r.job.steps;
  return S.meta.states.map((s) => ({ ...s, status: "pending", calls: [] }));
}

function logHtml() {
  const r = S.run;
  const by = Object.fromEntries(steps().map((s) => [s.state, s]));
  const mandatory = new Set(S.meta.mandatory);
  const ST = { DONE: ["[ OK ]", "ok"], skipped: ["[ —— ]", "skip"], FAILED: ["[FAIL]", "fail"], running: ["[ ●● ]", "run"], pending: ["[ ·· ]", "wait"] };
  let n = 0;
  const row = (s, num) => {
    const [txt, cls] = ST[s.status] || ST.pending;
    const groups = [];
    for (const c of s.calls || []) {
      const kind = !c.valid ? "bad" : c.origin === "model" ? "model" : "";
      const g = groups.find((x) => x.tool === c.tool && x.kind === kind);
      if (g) g.n += 1; else groups.push({ tool: c.tool, kind, n: 1, err: c.error });
    }
    const tools = groups.map((g) => `<span class="${g.kind}" title="${esc(g.kind === "model" ? "model önerdi" : g.kind === "bad" ? g.err || "reddedildi" : "harness")}">${esc(g.tool)}${g.n > 1 ? ` ×${g.n}` : ""}</span>`).join("");
    return `<div class="log-row ${s.status === "pending" ? "pending" : ""}">
      <span class="n">${num}</span><span class="st ${cls}">${txt}</span>
      <span class="nm">${esc(s.label)}${mandatory.has(s.state) ? "<em>ZORUNLU</em>" : ""}${s.status === "skipped" ? `<span class="why">${esc(s.reason || "senaryoyla ilgisiz")}</span>` : ""}${tools ? `<span class="tools">${tools}</span>` : ""}</span>
    </div>`;
  };
  return S.meta.phases.map((p) => {
    let rows = "";
    if (p.id === "prep" && r.understood?.method !== "golden" && !(r.phase === "running" && !r.understood)) {
      const st = r.phase === "understanding" ? "running" : r.understood ? (r.understood.ok ? "DONE" : "FAILED") : "pending";
      rows += row({ state: "_INTENT", label: "Soru anlama", status: st, calls: r.understood?.method === "llm" ? [{ tool: "bist-analist", origin: "model", valid: true }] : [] }, "00");
    }
    rows += S.meta.states.filter((s) => s.phase === p.id).map((s) => row(by[s.state] || { ...s, status: "pending" }, pad2(++n))).join("");
    return `<div class="log-phase">${esc(p.label)}</div>${rows}`;
  }).join("");
}

function runView() {
  return `<section class="run wrap">
    <div class="run-now"><div class="counter" id="counter">00<sup>/17</sup></div><h2 id="run-title">Soru anlaşılıyor</h2><p id="run-desc"></p>
      <div class="label elapsed">Geçen süre — <span id="elapsed">0,0 sn</span></div><div class="bar"><i id="run-bar" style="width:0"></i></div></div>
    <div class="log" id="log"></div>
  </section>`;
}

function updateRun() {
  const r = S.run;
  if (!r || !$("#log")) return;
  $("#log").innerHTML = logHtml();
  const done = steps().filter((s) => ["DONE", "skipped", "FAILED"].includes(s.status)).length;
  let title = "Soru anlaşılıyor";
  let desc = modelReady() ? "Yerel model soruyu senaryo, hisse ve parametrelere çeviriyor; kod her hisseyi sorudaki adla doğruluyor." : "Anahtar kelime kurallarıyla senaryo ve hisseler belirleniyor.";
  if (r.phase === "running") {
    const cur = r.job?.current;
    const st = S.meta.states.find((s) => s.state === cur);
    title = st ? st.label : "İş akışı başlıyor";
    desc = STATE_DESC[cur] || "Harness adımları sırayla çalıştırıyor.";
  }
  $("#counter").innerHTML = `${pad2(done)}<sup>/17</sup>`;
  $("#run-title").textContent = title;
  $("#run-desc").textContent = desc;
  $("#run-bar").style.width = Math.round((done / 17) * 100) + "%";
}

// ------------------------------------------------------------------ analysis: result
function resultView(res) {
  const first = res.attempts[0];
  let audit, auditSub;
  if (res.fallback) { audit = "Güvenli şablon"; auditSub = "Model çıktısı denetimden geçemedi; deterministik şablon gösterildi."; }
  else if (!isLlm(res.explainer)) { audit = "Şablon"; auditSub = "Kural tabanlı açıklayıcı, denetimden geçti."; }
  else if (first && first.ok) { audit = "İlk denemede"; auditSub = "Şema, eylem, sayı, tarih ve yasaklı ifade denetimlerinin hepsi geçti."; }
  else { audit = `${res.attempts.length}. denemede`; auditSub = "İlk deneme hata geri bildirimiyle düzeltildi."; }
  const words = String(res.action_label || res.action).split(" ");
  const head = words.length > 1 ? `${esc(words.slice(0, -1).join(" "))} <em>${esc(words.at(-1))}.</em>` : `<em>${esc(words[0])}.</em>`;
  const sections = [
    ["aciklama", "Açıklama", "Doğrulanmış metin. Üst simge kaynağa götürür."],
    ["kanit", "Kanıt seti", "Modelin kullanabildiği tek bilgi."],
    ["fiyat", "Fiyat", "Analiz tarihine kadar."],
    ...(res.backtest ? [["backtest", "Backtest", "t+1 işlem, maliyetli."]] : []),
    ["akis", "İş akışı", "17 adımın tam kaydı."],
    ["denetim", "Denetim", "Çıktı denetleyicisi."],
    ["onay", "Karar ve onay", "İnsan incelemesi ve replay."],
  ];
  const inner = {
    aciklama: explanationBlock(res), kanit: evidenceBlock(res), fiyat: priceBlock(res), backtest: res.backtest ? backtestBlock(res) : "",
    akis: `<div class="log">${logHtml()}</div>`, denetim: auditBlock(res), onay: recordBlock(res),
  };
  const sec = (i, [id, title, sub]) => `<section class="sec" id="s-${id}"><div class="sec-label"><div class="num">${pad2(i + 1)}</div><div><h3>${title}</h3><p>${sub}</p></div></div><div class="rv sec-body">${inner[id]}</div></section>`;
  return `
    <div class="wrap">
      <section class="verdict">
        <div>${label("Analitik durum")}<h2>${head}</h2>
          <div class="code"><span class="dot" style="--c:var(${ACTION_C[res.action] || "--ink"})"></span>${esc(res.action)}</div><p class="desc">${esc(res.action_desc || "")}</p></div>
        <div class="facts">
          <div class="fact">${label("Risk kapısı")}<div><b><span class="dot" style="--c:var(${GATE_C[res.gate] || "--ink"})"></span>${esc(res.gate_label)}</b><small>${esc(res.gate_desc)}${res.gate_reasons.length ? ` ${res.gate_reasons.length} bulgu.` : ""}</small></div></div>
          <div class="fact">${label("Çıktı denetimi")}<div><b>${esc(audit)}</b><small>${esc(auditSub)}</small></div></div>
          <div class="fact">${label("Araç çağrısı")}<div><b>${res.n_calls} çağrı · ${res.n_invalid} geçersiz</b><small>${isLlm(res.explainer) ? "Planı ve metni yerel model önerdi." : "Senaryo kuralı ve şablon."}</small></div></div>
        </div>
      </section>
      <nav class="toc">${sections.map(([id, t], i) => `<a href="#" data-jump="s-${id}">${pad2(i + 1)} ${t}</a>`).join("")}</nav>
      ${sections.map((s, i) => sec(i, s)).join("")}
    </div>`;
}

function explanationBlock(res) {
  const paras = String(res.text || "").split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);
  let out = "", tail = "";
  for (const p of paras) {
    if (p === S.meta.disclaimer) { tail = `<div class="disclaimer">${label("Not")}<span>${esc(p)}</span></div>`; continue; }
    out += p === S.meta.refusal_template ? `<div class="refusal">${label("Tavsiye talebi reddedildi")}${refs(esc(p))}</div>` : `<p>${refs(esc(p))}</p>`;
  }
  const cited = new Set(res.cited || []);
  const notes = res.committed.filter((c) => cited.has(c.id)).map((c) => `<div class="note" id="note-${esc(c.id)}"><b>${esc(c.id.slice(1))}</b>${esc(c.claim_tr)}<span class="tool">${esc(c.tool)} · ${esc(String(c.call_id || "").slice(0, 10))}</span></div>`).join("");
  const drop = /^[A-Za-zÇĞİÖŞÜçğıöşü]/.test(paras[0] || "") && paras[0] !== S.meta.refusal_template ? " dropcap" : "";
  return `<div class="article"><div class="prose${drop}">${out}${tail}</div><aside class="notes">${notes || '<div class="note">Atıf yok.</div>'}</aside></div>`;
}

function evidenceBlock(res) {
  const cited = new Set(res.cited || []);
  const rows = res.committed.map((c) => {
    const kv = Object.entries(c.display || {}).filter(([, v]) => String(v).length < 34).slice(0, 8).map(([k, v]) => `<span>${esc(k)} <b>${esc(v)}</b></span>`).join("");
    return `<div class="ev" id="ev-${esc(c.id)}"><div class="id">${esc(c.id)}${cited.has(c.id) ? "<small>metinde</small>" : ""}</div>
      <div><p>${esc(c.claim_tr)}</p>${kv ? `<div class="kv">${kv}</div>` : ""}</div>
      <div class="src">${esc(c.tool)}<br>${esc(c.kind || "")} · ${esc(String(c.call_id || "").slice(0, 12))}</div></div>`;
  }).join("");
  // same (level, code) findings are grouped: 36 TMS 29 notes read as one line "× 36", details on demand
  const groups = [];
  for (const g of res.gate_reasons) {
    const hit = groups.find((x) => x.level === g.level && x.code === g.code);
    if (hit) hit.details.push(g.detail); else groups.push({ level: g.level, code: g.code, details: [g.detail] });
  }
  const finding = (g) => {
    const head = `<span><span class="dot" style="--c:var(${GATE_C[g.level] || "--ink"})"></span>${esc(GATE_LABEL[g.level] || g.level)}</span><code>${esc(g.code)}${g.details.length > 1 ? ` <b class="sig">×${g.details.length}</b>` : ""}</code>`;
    if (g.details.length === 1) return `<div class="finding">${head}<span style="color:var(--mute)">${esc(g.details[0])}</span></div>`;
    return `<details class="finding-group"><summary class="finding">${head}<span style="color:var(--mute)">${esc(g.details[0])} <span class="sig">+${g.details.length - 1} benzer</span></span></summary>
      <div class="finding-more">${g.details.slice(1).map((d) => `<div>${esc(d)}</div>`).join("")}</div></details>`;
  };
  const findings = groups.length ? `<div class="findings">${label(`Risk kapısı bulguları — ${res.gate_reasons.length} bulgu, ${groups.length} tür`, "ink")}
    <div style="margin-top:10px;border-top:1px solid var(--ink)">${groups.map(finding).join("")}</div></div>` : "";
  const observed = res.observed.length ? `<details class="more"><summary>Gözlenen bağlam — ${res.observed.length} aday, açıklamada kullanılamaz</summary>
    <div class="obs">${res.observed.slice(0, 160).map((o) => `<div><span class="mono" style="color:var(--ink)">${esc(o.id)}</span> ${esc(o.claim_tr)}</div>`).join("")}</div></details>` : "";
  return `<div class="ev-list">${rows}</div>${findings}${observed}`;
}

function benchOf(res) { return Object.keys(res.prices).find((t) => !res.request.tickers.includes(t)); }
function priceBlock(res) {
  const bench = benchOf(res);
  const tickers = Object.keys(res.prices).filter((t) => t !== bench);
  if (!tickers.length) return '<p class="small-note">Bu analiz için fiyat serisi yok.</p>';
  if (!S.chartTicker || !tickers.includes(S.chartTicker)) S.chartTicker = tickers[0];
  return `<div class="row" style="justify-content:space-between">
      <div class="pills">${tickers.map((t) => `<button class="pill ${t === S.chartTicker ? "on" : ""}" data-ticker="${esc(t)}">${esc(t)}</button>`).join("")}</div>
      <div class="toggle" data-chart-mode><button class="${S.chartMode === "price" ? "on" : ""}" data-v="price">Fiyat</button>${bench ? `<button class="${S.chartMode === "rel" ? "on" : ""}" data-v="rel">${esc(bench)} kıyası</button>` : ""}</div>
    </div>
    <div id="chart-price" class="chart"></div>
    <div class="legend" id="legend-price"></div>
    <p class="small-note">Düzeltilmiş fiyatlar analiz tarihine (${fmtDate(res.request.as_of_date)}) çapalıdır; bu tarihten sonraki hiçbir veri okunmaz.</p>`;
}

function backtestBlock(res) {
  const bt = res.backtest;
  const names = Object.keys(bt.variants);
  if (!S.variant || !names.includes(S.variant)) S.variant = names[0];
  const v = bt.variants[S.variant], m = v.metrics || {}, tr = v.trades || {};
  const sign = (x) => (x > 0 ? "pos" : x < 0 ? "neg" : "");
  const fig = (t, val, cls = "", sub = "") => `<div class="fig">${label(t)}<div class="v ${cls}">${val}</div>${sub ? `<small>${sub}</small>` : ""}</div>`;
  const span = (b) => (b ? `${fmtDate(b.start)}–${fmtDate(b.end)}` : "");
  const costL = { tx_cost_bps: "işlem maliyeti", slippage_bps: "kayma" };
  const costs = bt.costs ? Object.entries(bt.costs).map(([k, val]) => `${costL[k] || k} ${val} baz puan`).join(", ") : "";
  return `<div class="row" style="justify-content:space-between;margin-bottom:18px">
      <div class="pills">${names.map((n) => `<button class="pill ${n === S.variant ? "on" : ""}" data-variant="${esc(n)}">${esc(VARIANT_TR[n] || n)}</button>`).join("")}</div>
      ${label(`${fmtDate(m.start)} — ${fmtDate(m.end)}`)}
    </div>
    <div class="figs">
      ${fig("Kümülatif getiri", pct(m.cumulative, 1, true), sign(m.cumulative), "nominal")}
      ${fig("Reel getiri", pct(v.real_cumulative, 1, true), sign(v.real_cumulative), "TÜFE'ye göre")}
      ${fig("XU100 farkı", pct(v.vs_xu100, 1, true), sign(v.vs_xu100), "aynı dönem")}
      ${fig("En büyük düşüş", pct(m.max_drawdown, 1), "neg", "tepe–dip")}
      ${fig("Sharpe", trNum(m.sharpe_rf0 ?? 0, 2), "", `politika faizine göre ${trNum(m.sharpe_policy ?? 0, 2)}`)}
      ${fig("Kapanan işlem", String(tr.n_closed ?? 0), "", `kazanan oranı ${pct(tr.win_rate, 0)}`)}
      ${fig("Örneklem içi", v.in_sample ? pct(v.in_sample.cumulative, 1, true) : "–", sign(v.in_sample?.cumulative), span(v.in_sample))}
      ${fig("Örneklem dışı", v.out_of_sample ? pct(v.out_of_sample.cumulative, 1, true) : "–", sign(v.out_of_sample?.cumulative), span(v.out_of_sample))}
    </div>
    <div id="chart-equity" class="chart"></div>
    <div class="legend"><span><i style="--c:var(--signal)"></i>Strateji</span><span><i style="--c:var(--ink)"></i>XU100</span><span><i class="dash" style="--c:var(--mute)"></i>Eşit ağırlıklı al-tut</span></div>
    <p class="small-note">Sinyal t kapanışında, işlem t+1 açılışında; ${esc(costs)}. BUY/SELL yalnızca eğitsel backtest pozisyonudur, hiçbir emir üretilmez.</p>`;
}

function auditBlock(res) {
  if (!res.attempts.length) return '<p class="small-note">Bu analizde model çağrısı yok.</p>';
  const teacher = res.teacher_action ? `<p class="small-note" style="margin:0 0 18px">Kural tabanlı referans eylem <b class="mono">${esc(res.teacher_action)}</b> — ${res.teacher_action === res.action ? "seçilen eylemle aynı." : "seçilen eylemden farklı."}</p>` : "";
  return teacher + res.attempts.map((a, i) => `<div class="attempt">
      <div class="row" style="justify-content:space-between;margin-bottom:12px">${label(`Deneme ${i + 1} — ${a.ok ? "geçti" : "kaldı"}`, "ink")}${label([a.model, a.seconds ? trNum(a.seconds, 1) + " sn" : ""].filter(Boolean).join(" · "))}</div>
      <div class="checks">${Object.entries(a.checks || {}).map(([k, ok]) => `<div class="check ${ok ? "ok" : "no"}"><span class="m">${ok ? "[ OK ]" : "[FAIL]"}</span>${esc(CHECK_TR[k] || k)}</div>`).join("")}</div>
      ${(a.errors || []).length ? `<ul style="color:var(--neg);font-size:14px">${a.errors.map((e) => `<li>${esc(e)}</li>`).join("")}</ul>` : ""}
      <details class="more"><summary>Modelin ham JSON çıktısı</summary><pre class="raw">${esc(prettyJson(a.raw))}</pre></details>
    </div>`).join("");
}
function prettyJson(s) { try { return JSON.stringify(JSON.parse(s), null, 2); } catch { return s; } }

function recordBlock(res) {
  return `<div class="row" style="margin-bottom:20px">${label("Karar " + esc(res.decision_id), "ink")}${label("Analiz " + esc(res.analysis_id))}</div>
    <div class="row" style="margin-bottom:24px">
      <button class="btn" data-replay="${esc(res.decision_id)}" data-llm="0">${ICON.replay} Araçları yeniden çalıştır</button>
      ${modelReady() && isLlm(res.explainer) ? `<button class="btn" data-replay="${esc(res.decision_id)}" data-llm="1">${ICON.replay} Model dahil replay</button>` : ""}
    </div>
    <div id="replay-slot"></div>
    ${reviewForm(res.decision_id)}`;
}

function reviewForm(did) {
  const v = S.verdict;
  const opts = S.meta.actions.map((a) => `<option value="${esc(a.id)}">${esc(a.label)} — ${esc(a.id)}</option>`).join("");
  let reviewer = "";
  try { reviewer = localStorage.getItem("fintrex.reviewer") || ""; } catch { /* ignore */ }
  return `${label("İnsan incelemesi", "ink")}
    <div class="review" style="margin-top:12px">
      <button class="vbtn ${v === "ACCEPT" ? "on" : ""}" data-verdict="ACCEPT"><b>Kabul</b><span>Sonuç ve kanıtlar tutarlı.</span></button>
      <button class="vbtn ${v === "MODIFY" ? "on" : ""}" data-verdict="MODIFY"><b>Değiştir</b><span>Başka bir analitik durum.</span></button>
      <button class="vbtn ${v === "REJECT" ? "on" : ""}" data-verdict="REJECT"><b>Reddet</b><span>Sonuç kabul edilemez.</span></button>
    </div>
    <label class="field ${v === "MODIFY" ? "" : "hidden"}" id="mod-field">${label("Yeni analitik durum")}<select id="mod">${opts}</select></label>
    <label class="field">${label("Gerekçe — zorunlu")}<textarea id="reason" rows="2" placeholder="Kanıtlar tutarlı; örneklem küçük olduğu için izlemek yeterli."></textarea></label>
    <div class="row" style="margin-top:20px;align-items:flex-end">
      <label class="field" style="margin:0;flex:1;max-width:320px">${label("İnceleyen")}<input id="reviewer" value="${esc(reviewer)}" placeholder="Ad"></label>
      <button class="btn solid" data-save-review="${esc(did)}">İncelemeyi kaydet ${ICON.arrow}</button>
    </div>
    <div class="rlog" id="rlog"></div>`;
}

function afterResult() {
  const res = S.run.result;
  drawPrice(res);
  if (res.backtest) drawEquity(res);
  loadReviews(res.decision_id);
  if (S.run.focus) {
    const el = document.getElementById("s-" + S.run.focus);
    S.run.focus = null;
    if (el) { el.querySelector(".rv")?.classList.add("in"); el.scrollIntoView({ behavior: "instant", block: "start" }); }
  }
}

// ------------------------------------------------------------------ charts
function plotBase(extra = {}) {
  const grid = "rgba(17,17,16,.08)";
  return {
    margin: { l: 52, r: 12, t: 10, b: 34 }, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: css("--mono") || "monospace", size: 11, color: css("--mute") }, separators: ",.",
    hovermode: "x unified", hoverlabel: { bgcolor: "#111110", bordercolor: "#111110", font: { color: "#efede6", family: css("--mono") } },
    xaxis: { gridcolor: grid, griddash: "dot", linecolor: "#111110", tickformat: "%m.%Y", hoverformat: "%d.%m.%Y", showspikes: false },
    yaxis: { gridcolor: grid, griddash: "dot", zeroline: false },
    showlegend: false, ...extra,
  };
}
const PCFG = { displayModeBar: false, responsive: true };

function drawPrice(res) {
  const el = $("#chart-price");
  if (!el || !window.Plotly) return;
  const t = S.chartTicker, p = res.prices[t], bench = benchOf(res), asof = res.request.as_of_date;
  const ink = css("--ink"), sig = css("--signal");
  const shapes = [{ type: "line", x0: asof, x1: asof, yref: "paper", y0: 0, y1: 1, line: { color: sig, width: 1, dash: "dot" } }];
  const annotations = [{ x: asof, yref: "paper", y: 1, text: "AS_OF", showarrow: false, xanchor: "right", yanchor: "top", font: { color: sig, size: 10 } }];
  const yax = { gridcolor: "rgba(17,17,16,.08)", griddash: "dot", zeroline: false };
  let data, layout, legend;
  if (S.chartMode === "rel" && bench) {
    const b = res.prices[bench];
    const bi = Object.fromEntries(b.dates.map((d, i) => [d, b.close[i]]));
    const pi = Object.fromEntries(p.dates.map((d, i) => [d, p.close[i]]));
    const common = p.dates.filter((d) => d in bi);
    const p0 = pi[common[0]], b0 = bi[common[0]];
    data = [
      { x: common, y: common.map((d) => (pi[d] / p0) * 100), name: t, type: "scatter", mode: "lines", line: { color: sig, width: 2 } },
      { x: common, y: common.map((d) => (bi[d] / b0) * 100), name: bench, type: "scatter", mode: "lines", line: { color: ink, width: 1.3 } },
    ];
    layout = plotBase({ shapes, annotations, yaxis: { ...yax, title: { text: "başlangıç = 100", font: { size: 10 } } } });
    legend = `<span><i style="--c:var(--signal)"></i>${esc(t)}</span><span><i style="--c:var(--ink)"></i>${esc(bench)}</span>`;
  } else {
    data = [
      { x: p.dates, y: p.close, name: t, type: "scatter", mode: "lines", line: { color: ink, width: 1.5 } },
      { x: p.dates, y: p.volume, name: "Hacim", type: "bar", yaxis: "y2", marker: { color: "rgba(17,17,16,.16)" }, hovertemplate: "%{y:,.0f}<extra>Hacim</extra>" },
    ];
    const ev = (res.recent_events || []).filter((e) => !e.ticker || e.ticker === t);
    if (ev.length) {
      data.push({
        x: ev.map((e) => e.event_date), y: ev.map((e) => e.close), name: "Olay", type: "scatter", mode: "markers",
        marker: { size: 10, symbol: ev.map((e) => (e.direction === "bearish" ? "triangle-down" : "triangle-up")), color: ev.map((e) => (e.direction === "bearish" ? ink : sig)), line: { color: css("--paper"), width: 1.2 } },
        text: ev.map((e) => EVENT_TR[e.event_type] || e.event_type), hovertemplate: "%{text}<extra></extra>",
      });
    }
    const vals = p.close.filter((x) => x != null);
    layout = plotBase({ shapes, annotations,
      yaxis: { ...yax, domain: [0.22, 1], range: [Math.min(...vals) * 0.94, Math.max(...vals) * 1.04] },
      yaxis2: { domain: [0, 0.16], showgrid: false, showticklabels: false } });
    legend = `<span><i style="--c:var(--ink)"></i>${esc(t)} kapanış (TL)</span><span><i style="--c:rgba(17,17,16,.25)"></i>Hacim</span>${ev.length ? '<span style="color:var(--signal)">▲ son dönüş olayları</span>' : ""}`;
  }
  Plotly.newPlot(el, data, layout, PCFG);
  $("#legend-price").innerHTML = legend;
}

function drawEquity(res) {
  const el = $("#chart-equity");
  if (!el || !window.Plotly) return;
  const eq = res.backtest.variants[S.variant].equity || [];
  if (!eq.length) { el.outerHTML = '<p class="small-note">Bu varyant için getiri eğrisi yok.</p>'; return; }
  const x = eq.map((r) => r.date);
  const line = (k, name, color, width, dash) => ({ x, y: eq.map((r) => (r[k] ?? null) * 100), name, type: "scatter", mode: "lines", line: { color, width, dash }, hovertemplate: "%%{y:.1f}<extra>" + name + "</extra>" });
  Plotly.newPlot(el, [
    line("buy_and_hold", "Eşit ağırlıklı al-tut", css("--mute"), 1.2, "dot"),
    line("xu100", "XU100", css("--ink"), 1.3),
    line("strategy", "Strateji", css("--signal"), 2.2),
  ], plotBase({ yaxis: { gridcolor: "rgba(17,17,16,.08)", griddash: "dot", zeroline: true, zerolinecolor: "rgba(17,17,16,.35)", tickprefix: "%" } }), PCFG);
}

// ------------------------------------------------------------------ review / replay
async function loadReviews(did) {
  if (!did) return;
  try { renderReviews((await api("/api/decision/" + encodeURIComponent(did))).reviews); } catch { /* empty */ }
}
function renderReviews(list) {
  const el = $("#rlog");
  if (!el) return;
  el.innerHTML = (list || []).map((r) => `<div><span class="label ink">${esc(VERDICT[r.verdict] || r.verdict)}${r.modified_action ? " → " + esc(r.modified_action) : ""}</span> &nbsp;${label(esc(r.reviewer) + " · " + fmtDateTime(r.created_at))}<div style="margin-top:6px;font-family:var(--serif);font-size:20px">${esc(r.reason)}</div></div>`).join("");
}
async function saveReview(did) {
  const reason = $("#reason").value.trim();
  if (!reason) { toast("Gerekçe zorunlu.", true); $("#reason").focus(); return; }
  const reviewer = $("#reviewer").value.trim() || "inceleyen";
  try { localStorage.setItem("fintrex.reviewer", reviewer); } catch { /* ignore */ }
  try {
    const out = await api("/api/review", { decision_id: did, verdict: S.verdict, reason, reviewer, modified_action: S.verdict === "MODIFY" ? $("#mod").value : null });
    $("#reason").value = "";
    renderReviews(out.reviews);
    S.history = null;
    toast("İnceleme karar kaydına eklendi.");
  } catch (e) { toast(e.message, true); }
}
async function doReplay(did, withLlm) {
  const slot = $("#replay-slot");
  $$("[data-replay]").forEach((b) => (b.disabled = true));
  slot.innerHTML = `<div class="loading"><span class="spinner"></span>${withLlm ? "Araçlar ve yerel model aynı girdiyle yeniden çalışıyor" : "Tüm araç çağrıları aynı girdiyle yeniden çalışıyor"}</div>`;
  try {
    const r = await api("/api/replay", { decision_id: did, llm: withLlm });
    const cell = (ok, v, t) => `<div class="rp"><div class="v ${ok === null ? "na" : ok ? "ok" : "no"}">${v}</div><small>${t}</small></div>`;
    slot.innerHTML = `<div class="replay">
        ${cell(r.data_version_match, r.data_version_match ? "Aynı" : "Farklı", "Veri sürümü — donmuş snapshot hash'i")}
        ${cell(r.tools_match, `${r.n_match}/${r.n_calls}`, "Araç çıktısı birebir aynı — sha256")}
        ${cell(r.llm_compared ? r.llm_match : null, r.llm_compared ? (r.llm_match ? "Bayt bayt" : "Farklı") : "—", r.llm_compared ? "Model çıktısı — temperature 0, seed 42, soğuk çağrı" : "Model karşılaştırılmadı")}
      </div>
      <details class="more"><summary>Çağrı bazında hash'ler — ${trNum(r.seconds, 1)} sn</summary>
        <div style="overflow:auto;max-height:340px"><table class="t"><thead><tr><th>#</th><th>Adım</th><th>Araç</th><th>Kayıtlı</th><th>Yeniden</th><th></th></tr></thead><tbody>
        ${r.calls.map((c) => `<tr><td>${c.seq}</td><td>${esc(c.state)}</td><td>${esc(c.tool)}</td><td>${esc(String(c.stored_hash).slice(0, 12))}</td><td>${esc(String(c.replay_hash).slice(0, 12))}</td><td style="color:var(${c.match ? "--pos" : "--neg"})">${c.match ? "aynı" : "farklı"}</td></tr>`).join("")}
        </tbody></table></div></details>
      ${r.llm_diff ? `<pre class="raw">${esc(r.llm_diff)}</pre>` : ""}`;
  } catch (e) { slot.innerHTML = `<p style="color:var(--neg)">${esc(e.message)}</p>`; }
  finally { $$("[data-replay]").forEach((b) => (b.disabled = false)); }
}

// ------------------------------------------------------------------ history
async function renderHistory() {
  $("#view").innerHTML = `<div class="wrap">
    <header class="page-title"><div><h1>Karar <em>kaydı</em></h1><p>Her analiz; araç girdileri ve çıktıları, model kimliği, denetim sonucu ve insan kararıyla episodik belleğe yazılır. Bir satır seçin.</p></div>
      <button class="btn" id="refresh">${ICON.replay} Yenile</button></header>
    <div id="hlist"><div class="loading"><span class="spinner"></span>Yükleniyor</div></div></div>${footer()}`;
  $("#refresh").addEventListener("click", () => { S.history = null; renderHistory(); });
  try { if (!S.history) S.history = (await api("/api/history")).rows; } catch (e) { $("#hlist").innerHTML = `<p class="empty">${esc(e.message)}</p>`; return; }
  if (!S.history.length) { $("#hlist").innerHTML = '<p class="empty">Henüz kayıtlı analiz yok. <a href="#/yeni">İlk soruyu sorun.</a></p>'; return; }
  $("#hlist").innerHTML = S.history.map((r) => `
    <div class="hrow ${S.open === r.decision_id ? "open" : ""}" data-decision="${esc(r.decision_id || "")}">
      <span>${label(fmtDateTime(r.created_at), "ink")}<br>${label("as_of " + fmtDate(r.as_of))}</span>
      <span class="q">${esc(r.question || "")}<small>${esc(r.scenario_label || "")} — ${esc((r.tickers || []).join(", "))} — ${isLlm(r.explainer) ? "yerel model" : "şablon"}</small></span>
      <span>${r.action ? `<span class="label" style="color:var(${ACTION_C[r.action] || "--ink"})">● ${esc(r.action)}</span>` : label(r.status || "—")}</span>
      <span>${r.gate ? label(GATE_LABEL[r.gate] || r.gate) : ""}</span>
      <span>${label(r.review ? VERDICT[r.review] || r.review : "bekliyor", r.review ? "ink" : "")}</span>
    </div>${S.open === r.decision_id ? '<div class="hdetail" id="hdetail"></div>' : ""}`).join("");
  if (S.open) showDecision(S.open);
}

async function showDecision(did) {
  const box = $("#hdetail");
  if (!box) return;
  box.innerHTML = '<div class="loading"><span class="spinner"></span>Yükleniyor</div>';
  let d;
  try { d = await api("/api/decision/" + encodeURIComponent(did)); } catch (e) { box.innerHTML = `<p>${esc(e.message)}</p>`; return; }
  const paras = String(d.decision.text_tr || "").split(/\n\s*\n/).filter(Boolean).map((p) => (p.trim() === S.meta.disclaimer
    ? `<div class="disclaimer">${label("Not")}<span>${esc(p)}</span></div>` : `<p>${refs(esc(p))}</p>`)).join("");
  const ev = (d.evidence || []).map((e) => `<div class="ev" id="ev-${esc(e.evidence_id)}"><div class="id">${esc(e.evidence_id)}</div><div><p>${esc(e.claim_tr)}</p></div><div class="src">${esc(e.tool)}</div></div>`).join("");
  S.verdict = "ACCEPT";
  box.innerHTML = `<div class="article" style="padding-top:18px"><div class="prose">${paras}</div>
      <div>${label("Karar " + esc(did), "ink")}<div class="row" style="margin:16px 0 20px">
        <button class="btn" data-replay="${esc(did)}" data-llm="0">${ICON.replay} Araçları yeniden çalıştır</button>
        ${modelReady() && isLlm(d.analysis.explainer) ? `<button class="btn" data-replay="${esc(did)}" data-llm="1">${ICON.replay} Model dahil</button>` : ""}</div>
        <div id="replay-slot"></div></div></div>
    <details class="more"><summary>Kanıt seti — ${(d.evidence || []).length}</summary><div class="ev-list">${ev}</div></details>
    <div style="margin-top:30px">${reviewForm(did)}</div>`;
  renderReviews(d.reviews);
}

// ------------------------------------------------------------------ method
async function renderHow() {
  $("#view").innerHTML = `<div class="wrap">
    <section class="statement">
      <div class="hero-meta">${label("Yöntem")}${label("Ajan tabanlı finansal analiz altyapısı")}</div>
      <h1 style="margin-top:40px"><span class="line-mask"><span>Model önerir.</span></span><span class="line-mask"><span>Kod <em>doğrular.</em></span></span><span class="line-mask"><span>İnsan onaylar.</span></span></h1>
      <p class="lead rv">FinTreX Analyst bir sohbet botu değil; yerel bir dil modelinin etrafına kurulmuş, her adımı kayıtlı ve tekrar üretilebilir bir analiz hattı. Model hiçbir sayıyı kendisi üretmez: sayılar deterministik araçlardan gelir, denetleyici her birini kanıtla karşılaştırır.</p>
    </section>
    <section class="flow rv">
      ${[
        ["01", "Soruyu anlar", "Serbest Türkçe soru; senaryo, hisse, parametre.", "llm", "Yerel LLM"],
        ["02", "Planı önerir", "İzin haritası dışındaki her çağrı reddedilir.", "llm", "Yerel LLM"],
        ["03", "15 araç hesaplar", "Tarih kilitli; her araç geleceğe bakış testli.", "code", "Kod"],
        ["04", "Kanıt ve backtest", "Kanıt seti, t+1 işlem, XU100 kıyası.", "code", "Kod"],
        ["05", "Kapı ve denetim", "Kapı eylemleri sınırlar; denetleyici her sayıyı arar.", "code", "Kod"],
        ["06", "İnsan karar verir", "Kabul, değişiklik veya ret; replay ile tekrar.", "human", "İnsan"],
      ].map(([n, b, s, w, wl]) => `<div><span class="n">${n}</span><b>${b}</b><span>${s}</span><span class="who ${w}">${wl.toUpperCase()}</span></div>`).join("")}
    </section>
    <div id="how-body"><div class="loading"><span class="spinner"></span>Ölçümler yükleniyor</div></div>
  </div>${footer()}`;
  reveal();
  try { if (!S.system) S.system = await api("/api/system"); } catch (e) { $("#how-body").innerHTML = `<p class="empty">${esc(e.message)}</p>`; return; }
  const sys = S.system, ft = sys.bakeoff["bist-analist"], base = sys.bakeoff["qwen3.5:4b"], e2e = sys.e2e, g = sys.golden;
  const intent = sys.intent["bist-analist (ince ayarlı)"], intentBase = sys.intent["qwen3.5:4b (taban)"];
  const big = (val, pre, suf, title, sub) => `<div class="bignum"><div class="v" data-count="${val}" data-pre="${esc(pre)}" data-suf="${esc(suf)}">${pre}0${suf}</div><b>${title}</b><span>${sub}</span></div>`;
  const nums = [
    g ? big(g.passed, "", `<small>/${g.n}</small>`, "Referans soru geçti", `${g.first_attempt}/${g.n} ilk denemede; eylem öğretmenle ${g.teacher}/${g.n} aynı`) : "",
    ft ? big(ft.first_attempt_pass * 100, "<small>%</small>", "", "İlk denemede denetimden geçen", `taban model ${pct(base?.first_attempt_pass, 0)} — ${ft.n} soru`) : "",
    intent ? big(intent.correct * 100, "<small>%</small>", "", "Serbest soruyu doğru anlama", `${intent.n} yeni soru; taban model ${pct(intentBase?.correct, 0)}`) : "",
    e2e ? big(e2e.runs_with_invented_numbers * 100, "<small>%</small>", "", "Uydurma sayı, uçtan uca", `${e2e.analysed} analiz; hatalı araç çağrısı ${pct(e2e.runs_with_invalid_calls, 0)}`) : "",
  ].join("");
  const rows = ft && base ? [
    ["İlk denemede denetimden geçti", ft.first_attempt_pass, base.first_attempt_pass],
    ["Şablona düşmeden tamamlandı", ft.final_without_fallback, base.final_without_fallback],
    ["Uydurma sayı içeren cevap", ft.questions_with_invented_numbers, base.questions_with_invented_numbers],
    ["Yasaklı ifade içeren cevap", ft.questions_with_forbidden_phrases, base.questions_with_forbidden_phrases],
    ["Kural tabanlı öğretmenle aynı eylem", ft.teacher_agreement, base.teacher_agreement],
  ].map(([w, a, b]) => `<div class="cmp-row"><span class="what">${w}</span><div class="track"><i class="a" style="width:${Math.max(a * 100, 0.8)}%"></i><i class="b" style="width:${Math.max(b * 100, 0.8)}%"></i></div><div class="vals">${pct(a, 0)}<span>${pct(b, 0)}</span></div></div>`).join("") : "";
  const ab = sys.ablation;
  const abl = ABLATION.map(([k, n, d]) => {
    const a = ab["bist-analist"]?.[k]?.any_rule_violation, b = ab["qwen3.5:4b"]?.[k]?.any_rule_violation;
    const bar = (v, c) => `<div style="--c:${c};height:${Math.max((v ?? 0) * 100, 0.7)}%"><span>${pct(v, 0)}</span></div>`;
    return `<div><div class="lv">${k}</div><div class="nm">${n}</div><div class="ds">${d}</div><div class="bars">${bar(a, "var(--signal)")}${bar(b, "rgba(17,17,16,.35)")}</div></div>`;
  }).join("");
  const guar = [
    ["Her sayı kanıtlı", "Açıklamadaki her sayı ve tarih kanıt setindeki bir değerle birebir eşleşmeli; eşleşmezse cevap reddedilir."],
    ["Geleceğe bakış yok", "Her veri okuması analiz tarihine kilitli; her araç için zehirli gelecek satırı testi var."],
    ["Tavsiye yok", "Al-sat, hedef fiyat, kesin yükselir yasak. Tavsiye istenirse sistem reddeder ve tarihsel bağlamı gösterir."],
    ["Sonlu eylem uzayı", "Model sekiz analitik durumdan birini seçer; risk kapısı hangilerinin serbest olduğunu belirler."],
    ["Tamamen yerel", "Model Ollama ile bu bilgisayarda çalışır; bulut API çağrısı mimari testle yasaklı."],
    ["Tekrar üretilebilir", "Temperature 0, seed 42, soğuk çağrı: aynı karar bayt bayt yeniden üretilir."],
    ["Donmuş veri", "Fiyat, KAP bilançoları, makro ve haber metadatası sha256 manifestli snapshot'lardan okunur."],
    ["Son söz insanda", "Her karar kabul, değişiklik veya ret ve gerekçesiyle kayda geçer."],
  ].map(([b, s], i) => `<div><span class="n">${pad2(i + 1)}</span><b>${b}</b><span>${s}</span></div>`).join("");
  $("#how-body").innerHTML = `
    <section class="bignums rv">${nums}</section>
    <section class="sec"><div class="sec-label"><div class="num">01</div><div><h3>İnce ayarın etkisi</h3><p>Aynı 20 soru, aynı kanıt paketleri. Tek fark model.</p></div></div>
      <div class="rv"><p class="lead" style="margin-bottom:26px">Qwen3.5-4B, kendi araç çıktılarımızdan üretilen ~10.600 örnekle QLoRA ile eğitildi. <span class="sig">Turuncu</span> ince ayarlı model, gri taban model.</p><div class="cmp">${rows}</div></div></section>
    <section class="sec"><div class="sec-label"><div class="num">02</div><div><h3>Katmanların etkisi</h3><p>Herhangi bir kural ihlali içeren cevap oranı, A'dan E'ye.</p></div></div>
      <div class="rv"><p class="lead" style="margin-bottom:26px">Güvenliği model tek başına sağlamaz; harness sağlar. Tam altyapıda (D ve E) iki modelde de ihlal <b>%0</b>.</p><div class="abl">${abl}</div>
      <div class="legend"><span><i style="--c:var(--signal)"></i>bist-analist</span><span><i style="--c:rgba(17,17,16,.35)"></i>qwen3.5:4b (taban)</span></div></div></section>
    <section class="sec"><div class="sec-label"><div class="num">03</div><div><h3>Garantiler</h3><p>Kodla zorlanan, testle sabitlenen kurallar.</p></div></div><div class="guar rv">${guar}</div></section>
    <section class="sec"><div class="sec-label"><div class="num">04</div><div><h3>Yığın</h3><p>Hepsi bu bilgisayarda.</p></div></div>
      <div class="rv"><p class="lead">Qwen3.5-4B + QLoRA (GGUF Q8_0) · Ollama · MCP, 15 araç · 17 adımlı stateful harness · SQLite: fiyat, KAP, makro, haber · Starlette</p>
      <div class="row" style="margin-top:28px"><a class="btn solid" href="#/yeni">Bir soru sorun ${ICON.arrow}</a></div></div></section>`;
  reveal();
}

// ------------------------------------------------------------------ interactions
function hotRef(id, on) {
  $$(`.ref[data-ev="${id}"]`).forEach((b) => b.classList.toggle("hot", on));
  document.getElementById("note-" + id)?.classList.toggle("hot", on);
}
function onHover(e) {
  const ref = e.target.closest?.(".ref");
  if (ref) hotRef(ref.dataset.ev, e.type === "mouseover");
}
function flashEv(id) {
  const note = document.getElementById("note-" + id);
  if (note && window.matchMedia("(min-width: 1101px)").matches) {
    note.scrollIntoView({ behavior: "smooth", block: "nearest" });
    hotRef(id, true); setTimeout(() => hotRef(id, false), 1600);
    return;
  }
  const ev = document.getElementById("ev-" + id);
  if (!ev) return;
  ev.closest("details")?.setAttribute("open", "");
  ev.closest(".rv")?.classList.add("in");
  ev.scrollIntoView({ behavior: "smooth", block: "center" });
  ev.classList.add("flash"); setTimeout(() => ev.classList.remove("flash"), 1600);
}

function onClick(e) {
  const t = e.target.closest("button, a[data-jump], .hrow");
  if (!t) return;
  if (t.dataset.jump) { e.preventDefault(); document.getElementById(t.dataset.jump)?.scrollIntoView({ behavior: "smooth", block: "start" }); return; }
  if (t.dataset.golden) { const g = S.meta.golden.find((x) => x.id === t.dataset.golden); if (g) ask(g.question, g.request); return; }
  if (t.dataset.example) { ask(t.dataset.example, null); return; }
  if (t.dataset.ev) { flashEv(t.dataset.ev); return; }
  if (t.dataset.ticker) { S.chartTicker = t.dataset.ticker; $$("[data-ticker]").forEach((b) => b.classList.toggle("on", b === t)); drawPrice(S.run.result); return; }
  if (t.dataset.variant) {
    S.variant = t.dataset.variant;
    const body = $("#s-backtest .sec-body");
    if (body) { body.innerHTML = backtestBlock(S.run.result); drawEquity(S.run.result); }
    return;
  }
  if (t.dataset.verdict) {
    S.verdict = t.dataset.verdict;
    $$(".vbtn").forEach((b) => b.classList.toggle("on", b.dataset.verdict === S.verdict));
    $("#mod-field")?.classList.toggle("hidden", S.verdict !== "MODIFY");
    return;
  }
  if (t.dataset.saveReview) { saveReview(t.dataset.saveReview); return; }
  if (t.dataset.replay) { doReplay(t.dataset.replay, t.dataset.llm === "1"); return; }
  if (t.classList.contains("hrow")) {
    const did = t.dataset.decision;
    if (!did) return;
    S.open = S.open === did ? null : did;
    renderHistory();
    return;
  }
  const tg = t.closest(".toggle");
  if (tg && t.dataset.v && !t.disabled) {
    $$("button", tg).forEach((b) => b.classList.toggle("on", b === t));
    if (tg.dataset.setting) { S.settings[tg.dataset.setting] = t.dataset.v; saveSettings(); }
    if (tg.hasAttribute("data-chart-mode")) { S.chartMode = t.dataset.v; drawPrice(S.run.result); }
  }
}

boot();
