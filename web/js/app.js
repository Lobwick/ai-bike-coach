// Tableau de bord ai-bike-coach (lecture seule). Ossature, tokens et graphiques repris du tableau de bord
// d'origine ; les vues sont celles du vélo (route, cyclo-cross, perte de poids).
//
// Sécurité : aucun `innerHTML`. Les gabarits `h` ÉCHAPPENT toute valeur interpolée (texte d'un fichier Markdown
// compris), sauf si elle est enveloppée par `raw()` — réservé au HTML qu'on construit soi-même. Le résultat est
// transformé en nœuds par `DOMParser` (aucun script exécutable).
import * as F from "./format.js";
import { attachCursor, timeChart } from "./chart.js";
import { navItems } from "./nav.js";

const $ = (s) => document.querySelector(s);

class Raw { constructor(s) { this.s = s; } }
const raw = (s) => new Raw(s);
const str = (v) => (v instanceof Raw ? v.s : Array.isArray(v) ? v.map(str).join("") : F.esc(v));
const h = (strings, ...vals) => new Raw(strings.reduce((a, s, i) => a + s + (i < vals.length ? str(vals[i]) : ""), ""));
function mount(host, content) {
  const doc = new DOMParser().parseFromString(`<!doctype html><body>${str(content)}`, "text/html");
  host.replaceChildren(...doc.body.childNodes);
}

const api = (u) => fetch(new URL(u.replace(/^\//, ""), location.origin + location.pathname.replace(/[^/]*$/, "")).href).then((r) => { if (!r.ok) throw new Error(`${u} ${r.status}`); return r.json(); });
const cap = (s) => s.replace(/^./, (c) => c.toUpperCase());
const dash = "—";
const nz = (v, d = 0) => (v == null ? dash : F.num(v, d));

let STATE = { summary: null };

function head(title, sub) {
  return h`<div class="view-head"><h1>${title}</h1>${sub ? h`<p class="view-sub">${sub}</p>` : ""}</div>`;
}
function emptyBox(title, text, code) {
  return h`<div class="empty"><h3>${title}</h3><p>${text}</p>${code ? h`<pre class="empty__code"><code>${code}</code></pre>` : ""}</div>`;
}
function chip(kind, label) { return h`<span class="chip chip--${kind}"><span class="chip__dot"></span>${label}</span>`; }

/* ------------------------------------------------------------------ en-tête : objectif et compte à rebours */

function renderObjective(s) {
  const box = $("#objective");
  const r = s.next_race;
  if (!r) {
    mount(box, h`<span class="objective__none">${s.objective || "Aucun objectif actif"} — <code>planning/active_objective.md</code></span>`);
    return;
  }
  const left = F.daysBetween(s.today, r.date);
  const when = left === 0 ? "J" : left > 0 ? `J-${left}` : `J+${-left}`;
  const detail = [F.dateLong(r.date), r.organizer].filter(Boolean).join(" · ");
  mount(box, h`<span class="objective__count ${left < 0 ? "is-past" : ""}">${when}</span>
    <span class="objective__text"><strong>${r.title || r.venue}</strong><span>${detail}</span></span>`);
}

/* ------------------------------------------------------------------ aujourd'hui */

const BAD_SIDE = { hrv_rmssd_ms: "low", sleep_min: "low", spo2_pct: "low", resting_hr_bpm: "high", respiratory_rate_brpm: "high" };

function rangeBar(m) {
  const b = m.baseline;
  if (!b || m.value == null) return "";
  const span = Math.max(b.high - b.low, 1);
  const lo = Math.min(m.value, b.low) - span * 0.8, hi = Math.max(m.value, b.high) + span * 0.8;
  const px = (v) => (((v - lo) / (hi - lo)) * 200).toFixed(1);
  const out = m.value < b.low ? "low" : m.value > b.high ? "high" : null;
  const cls = out && out === BAD_SIDE[m.key] ? "range range--warn" : "range";
  const label = `${m.label} ${m.value} ${m.unit}, bande personnelle ${b.low} à ${b.high}`;
  return raw(`<svg class="${cls}" viewBox="0 0 200 14" role="img" aria-label="${F.esc(label)}"><rect class="range__track" x="0" y="5" width="200" height="4" rx="2"/><rect class="range__band" x="${px(b.low)}" y="3" width="${(px(b.high) - px(b.low)).toFixed(1)}" height="8" rx="4"/><circle class="range__dot" cx="${px(m.value)}" cy="7" r="5"/></svg>`);
}

function metricValue(m) {
  if (m.value == null) return dash;
  return m.key === "sleep_min" ? F.duration(m.value * 60) : `${F.num(m.value, m.digits || 0)} ${m.unit}`;
}
function metricCtx(m) {
  if (m.value == null) return m.last ? `indisponible aujourd'hui — dernière mesure le ${F.dayShort(m.last.date)} (${m.last.value} ${m.unit})` : "indisponible — mesure absente, jamais interprétée comme normale";
  const b = m.baseline;
  if (!b) return "base personnelle provisoire (moins de 7 jours d'historique)";
  const pos = m.value < b.low ? "sous" : m.value > b.high ? "au-dessus de" : "dans";
  return `${pos} ta bande ${b.low}–${b.high} · moyenne ${b.n} j : ${b.mean}`;
}

async function viewToday() {
  const [t, s] = await Promise.all([api("/api/today"), api("/api/summary")]);
  const ver = t.verdict;
  const V = { green: "Maintenir", amber: "Alléger", red: "Repos" };
  const verdict = ver && ver.is_today
    ? h`<div class="verdict verdict--${ver.value}"><div class="verdict__word">${V[ver.value]}</div><p class="verdict__why">${ver.reason || ""}</p></div>`
    : h`<div class="verdict verdict--none"><div class="verdict__word">Pas de verdict aujourd'hui</div><p class="verdict__why">${ver ? h`Dernier verdict le ${F.dateLong(ver.date)} : <strong>${V[ver.value]}</strong>${ver.reason ? " — " + ver.reason : ""}` : "Aucun bilan matinal enregistré : il vient du /daily-sync ou de /today."}</p></div>`;

  const rows = t.metrics.map((m) => h`<tr><th scope="row">${m.label}</th><td class="triad__value">${metricValue(m)}</td><td class="triad__bar">${rangeBar(m)}</td><td class="triad__ctx">${metricCtx(m)}</td></tr>`);

  const plan = t.today_sessions.length
    ? h`<ul class="plan">${t.today_sessions.map((x) => h`<li><span class="plan__title">${x.title}</span><span class="plan__meta">${F.duration(x.duration_s)}${x.planned_load != null ? ` · charge ≈ ${Math.round(x.planned_load)}` : ""}</span>${x.status === "cancelled" ? chip("status-cancelled", "Annulée") : x.status === "done" ? chip("status-done", "Faite") : x.status === "missed" ? chip("status-missed", "Manquée") : x.status === "moved" ? chip("status-moved", "Déplacée") : ""}${x.race ? chip("verdict-amber", "Course") : x.fixed ? chip("status-planned", "Club imposée") : chip("status-planned", "Prévue")}</li>`)}</ul>`
    : h`<p class="muted">Rien de planifié aujourd'hui.</p>`;
  const next = t.upcoming.length
    ? h`<section class="band"><h2>À venir</h2><ul class="week week--upcoming">${t.upcoming.map((x) => h`<li class="day"><div class="day__head"><span class="day__name">${F.weekday(x.date)}</span><span class="day__date">${F.dayShort(x.date)}</span></div><div class="session"><span class="session__title">${x.title}</span><span class="session__meta">${F.duration(x.duration_s)}${x.planned_load != null ? ` · ≈ ${Math.round(x.planned_load)}` : ""}</span>${x.race ? chip("verdict-amber", "Course") : x.fixed ? chip("status-planned", "Club imposée") : ""}</div></li>`)}</ul></section>` : "";

  const L = t.load, st = L.state;
  const form = L.reliable && st
    ? h`<dl class="facts"><div><dt>Condition</dt><dd>${nz(st.condition)}</dd></div><div><dt>Fatigue</dt><dd>${nz(st.fatigue)}</dd></div><div><dt>Forme</dt><dd class="${st.form >= 0 ? "pos" : "neg"}">${st.form > 0 ? "+" : ""}${nz(st.form)}</dd></div>${L.ramp_per_week != null ? h`<div><dt>Rampe / semaine</dt><dd>${L.ramp_per_week > 0 ? "+" : ""}${nz(L.ramp_per_week, 1)}</dd></div>` : ""}</dl><p class="note"><a href="#/forme">Courbe de forme</a></p>`
    : h`<p class="muted">Historique de charge de ${L.history_days} jour(s) : la forme demande 42 jours. <a href="#/forme">Charge planifiée</a></p>`;

  const g = t.glucose;
  let gl = "";
  if (g.enabled) {
    const d = g.day, a = g.last_session;
    gl = h`<section class="band"><h2>Glycémie</h2>
      ${d ? h`<dl class="facts"><div><dt>Temps dans la cible (${F.dayShort(d.date)})</dt><dd>${nz(d.tir_pct)} %</dd></div><div><dt>Temps sous 70</dt><dd>${nz(d.time_below_pct, 1)} %</dd></div><div><dt>Moyenne</dt><dd>${nz(d.glucose_avg_mgdl)} mg/dL</dd></div>${d.nocturnal_low ? h`<div><dt>Nuit</dt><dd class="neg">hypoglycémie</dd></div>` : ""}</dl>` : h`<p class="muted">Aucun bilan glycémique enregistré.</p>`}
      ${a ? h`<p class="note">Dernière séance suivie (${F.dayShort(a.date)}) : départ ${nz(a.glucose_start_mgdl)} mg/dL, minimum ${nz(a.glucose_min_mgdl)}, ${a.hypo_events ? "hypoglycémie dans la fenêtre" : "pas d'hypoglycémie"}.</p>` : ""}
      <p class="note">Lecture des données déjà enregistrées par les agents. Aucune dose ni réglage d'override n'est suggéré ici.</p></section>`;
  }
  mount($("#main"), h`${head(cap(F.dayLong(t.date)))}${verdict}
    <section class="band"><h2>Santé</h2><table class="triad"><caption>Bilan du matin, comparé à ta base personnelle des 28 derniers jours</caption><tbody>${rows}</tbody></table></section>
    <div class="band band--split"><div><h2>Au programme</h2>${plan}</div><div><h2>Forme</h2>${form}</div></div>${next}${gl}`);
}

/* ------------------------------------------------------------------ forme & charge */

let RANGE = 180;
async function viewForm() {
  const d = await api("/api/load");
  const main = $("#main");
  if (!d.reliable) {
    const w = d.weekly_planned;
    mount(main, h`${head("Forme & charge", "Charge par séance : puissance déclarée, sinon série de FC, sinon FC moyenne, sinon effort perçu. Sans 42 jours d'historique, la forme n'est pas calculée.")}
      <section class="band"><h2>Charge planifiée par semaine</h2><p class="note">${d.note}</p><div id="chart" class="chart-host"></div><p class="readout" id="readout"></p></section>`);
    if (!w.length) return;
    const dates = w.map((x) => x.week_start), vals = w.map((x) => x.planned_load);
    const ch = timeChart(dates, [{ type: "bars", values: vals, cls: "bar" }], [], { height: 220, label: "Charge planifiée par semaine", y: { zero: true } });
    mount($("#chart"), raw(ch.svg));
    attachCursor($("#chart"), ch, (i) => mount($("#readout"), h`<strong>Semaine du ${F.dayLong(dates[i])}</strong> · charge planifiée ≈ ${Math.round(vals[i])} (estimation)`));
    return;
  }
  const keep = (a) => a.slice(-RANGE);
  const past = keep(d.series), proj = d.projection;
  const dates = past.map((r) => r.date).concat(proj.map((r) => r.date));
  const padNull = (n) => new Array(n).fill(null);
  const col = (k) => past.map((r) => r[k]).concat(proj.map((r) => r[k]));
  const projOnly = (k) => padNull(Math.max(past.length - 1, 0)).concat(past.length ? [past[past.length - 1][k]] : [], proj.map((r) => r[k]));
  const layers = [{ type: "area", values: col("form"), cls: "area--form", base: 0 },
    { type: "line", values: past.map((r) => r.fatigue).concat(padNull(proj.length)), cls: "line line--fatigue" },
    { type: "line", values: past.map((r) => r.condition).concat(padNull(proj.length)), cls: "line line--fitness" }];
  if (proj.length) layers.push({ type: "line", values: projOnly("fatigue"), cls: "line line--fatigue line--projected" }, { type: "line", values: projOnly("condition"), cls: "line line--fitness line--projected" });
  const marks = d.races?.map((r) => ({ type: "vline", date: r, cls: "mark mark--race" })) || [];
  const seg = (n, label) => h`<a class="seg ${RANGE === n ? "is-on" : ""}" href="#/forme" data-range="${n}">${label}</a>`;
  mount(main, h`${head("Forme & charge", "Charge par séance : puissance déclarée, sinon série de FC, sinon FC moyenne, sinon effort perçu.")}
    <div class="toolbar">${seg(90, "3 mois")}${seg(180, "6 mois")}${seg(365, "1 an")}</div>
    <section class="band"><h2>Courbe de forme</h2>
      <div class="legend"><span class="legend__item"><i class="key key--fitness"></i>Condition (42 j)</span><span class="legend__item"><i class="key key--fatigue"></i>Fatigue (7 j)</span><span class="legend__item"><i class="key key--form"></i>Forme</span>${proj.length ? h`<span class="legend__item"><i class="key key--projected"></i>Projection du plan (estimation)</span>` : ""}</div>
      <div id="chart" class="chart-host"></div><p class="readout" id="readout"></p></section>`);
  main.querySelectorAll("[data-range]").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); RANGE = Number(a.dataset.range); viewForm(); }));
  const ch = timeChart(dates, layers, marks, { height: 280, label: "Condition, fatigue et forme", y: { zero: true } });
  mount($("#chart"), raw(ch.svg));
  const all = past.concat(proj);
  attachCursor($("#chart"), ch, (i) => {
    const r = all[i]; const p = i >= past.length;
    mount($("#readout"), h`<strong>${F.dayLong(r.date)}</strong>${p ? " (projection)" : ""} · charge ${nz(r.load)} · condition ${nz(r.condition, 1)} · fatigue ${nz(r.fatigue, 1)} · forme ${r.form > 0 ? "+" : ""}${nz(r.form, 1)}`);
  }, Math.max(past.length - 1, 0));
}

/* ------------------------------------------------------------------ santé */

async function viewHealth() {
  const d = await api("/api/health");
  const days = d.days;
  if (!days.length) { mount($("#main"), h`${head("Santé")}${emptyBox("Aucun bilan santé", "Les bilans arrivent avec la synchronisation Open Wearables (HRV, FC de repos, sommeil) et la lecture de la glycémie.", "/daily-sync")}`); return; }
  const V = { green: ["verdict-green", "Maintenir"], amber: ["verdict-amber", "Alléger"], red: ["verdict-red", "Repos"] };
  const tr = days.slice().reverse().map((x) => h`<tr><th scope="row" class="nowrap">${F.dayShort(x.date)}</th><td>${x.verdict ? chip(...V[x.verdict]) : dash}</td><td class="num">${nz(x.resting_hr_bpm)}</td><td class="num">${nz(x.hrv_rmssd_ms)}</td><td class="num">${x.sleep_min ? F.duration(x.sleep_min * 60) : dash}</td><td class="num">${nz(x.respiratory_rate_brpm, 1)}</td><td class="num">${nz(x.spo2_pct, 1)}</td><td class="num">${nz(x.tir_pct)}</td><td class="num">${nz(x.time_below_pct, 1)}</td><td>${x.nocturnal_low ? chip("verdict-red", "oui") : x.nocturnal_low === false ? "non" : dash}</td><td class="num">${nz(x.weight_kg, 1)}</td></tr>`);
  mount($("#main"), h`${head("Santé", "Bilan matinal et glycémie. Une mesure absente reste « — » : jamais lue comme normale.")}
    <section class="band"><h2>HRV et FC de repos</h2><div id="chart" class="chart-host"></div><p class="readout" id="readout"></p></section>
    <div class="table-wrap"><table class="data data--compact"><thead><tr><th>Date</th><th>Verdict</th><th class="num">FC repos</th><th class="num">HRV ms</th><th class="num">Sommeil</th><th class="num">Resp.</th><th class="num">SpO₂</th><th class="num">TIR %</th><th class="num">&lt; 70 %</th><th>Hypo nuit</th><th class="num">Poids</th></tr></thead><tbody>${tr}</tbody></table></div>`);
  const dates = days.map((x) => x.date);
  if (days.filter((x) => x.hrv_rmssd_ms || x.resting_hr_bpm).length >= 3) {
    const ch = timeChart(dates, [{ type: "line", values: days.map((x) => x.hrv_rmssd_ms ?? null), cls: "line line--hrv" }, { type: "dots", values: days.map((x) => x.hrv_rmssd_ms ?? null), cls: "dot dot--hrv" },
      { type: "line", values: days.map((x) => x.resting_hr_bpm ?? null), cls: "line line--rhr", axis: "y2" }, { type: "dots", values: days.map((x) => x.resting_hr_bpm ?? null), cls: "dot dot--rhr", axis: "y2" }],
      [], { height: 220, y2: {}, label: "HRV et FC de repos", yFormat: (v) => `${v} ms`, y2Format: (v) => `${v}` });
    mount($("#chart"), raw(ch.svg));
    attachCursor($("#chart"), ch, (i) => { const x = days[i]; mount($("#readout"), h`<strong>${F.dayLong(x.date)}</strong> · HRV ${nz(x.hrv_rmssd_ms)} ms · FC de repos ${nz(x.resting_hr_bpm)} bpm`); });
  } else mount($("#chart"), h`<p class="muted">Pas assez de mesures (3 jours minimum) pour tracer les courbes.</p>`);
}

/* ------------------------------------------------------------------ semaine */

async function viewWeek() {
  const [p, s] = await Promise.all([api("/api/plan"), api("/api/summary")]);
  if (!p.weeks.length) { mount($("#main"), h`${head("Semaine")}${emptyBox("Aucune semaine planifiée", "Demande au coach de construire ta semaine.", "")}`); return; }
  const blocks = p.weeks.map((w) => {
    const days = [...Array(7).keys()].map((k) => F.addDays(w.week_start, k));
    const cells = days.map((d) => {
      const ss = w.sessions.filter((x) => x.date === d);
      return h`<li class="day ${d === s.today ? "day--today" : ""}"><div class="day__head"><span class="day__name">${F.weekday(d)}</span><span class="day__date">${F.dayShort(d)}</span></div>${ss.map((x) => h`<div class="session"><span class="session__title">${x.title}</span><span class="session__meta">${F.duration(x.duration_s)}${x.planned_load != null ? ` · ≈ ${Math.round(x.planned_load)}` : ""}</span>${x.race ? chip("verdict-amber", "Course") : x.fixed ? chip("status-planned", "Club imposée") : x.template ? chip("status-planned", x.garmin_pushed ? "Poussée" : "À pousser") : ""}</div>`)}</li>`;
    });
    const race = w.sessions.find((x) => x.race);
    const alts = race?.alternatives?.length ? h`<p class="note">Alternatives pour la course : ${race.alternatives.map((a) => `${F.weekday(a.date)} ${F.dayShort(a.date)} ${a.place}`).join(" · ")}.</p>` : "";
    const warns = w.guardrails.filter((g) => g.severity !== "info").map((g) => h`<p class="note">${chip(g.severity === "block" ? "verdict-red" : "verdict-amber", g.rule)} ${g.message}</p>`);
    return h`<section class="band"><h2>Semaine du ${F.dateLong(w.week_start)} <span class="muted">· ${w.focus || ""} · charge ≈ ${Math.round(w.planned_load)}</span></h2><ul class="week">${cells}</ul>${alts}${warns}</section>`;
  });
  mount($("#main"), h`${head("Semaine", "Plan en cours. La charge est une estimation (durée × intensité²), pas une mesure.")}${blocks}`);
}

/* ------------------------------------------------------------------ séances */

async function viewActivities() {
  const d = await api("/api/activities");
  if (!d.activities.length) { mount($("#main"), h`${head("Séances")}${emptyBox("Aucune séance enregistrée", "Les séances arrivent avec la synchronisation Open Wearables : demande au coach de rapatrier tes dernières semaines, ou attends le /daily-sync.", "/daily-sync")}`); return; }
  const tr = d.activities.map((a) => h`<tr><th scope="row" class="nowrap">${F.dayShort(a.date)}</th><td>${F.SPORT[a.discipline] || a.discipline}${a.race ? " " : ""}${a.race ? chip("verdict-amber", "Course") : ""}</td><td class="num">${a.duration_s ? F.duration(a.duration_s) : dash}</td><td class="num">${a.distance_m ? F.num(a.distance_m / 1000, 1) + " km" : dash}</td><td class="num">${a.elevation_gain_m ? F.num(a.elevation_gain_m) + " m" : dash}</td><td class="num">${nz(a.avg_hr_bpm)}</td><td class="num">${a.load != null ? `${nz(a.load)} (${a.load_method || "?"})` : dash}</td><td class="num">${a.easy_share_pct != null ? a.easy_share_pct + " %" : dash}</td><td class="num">${a.glucose_start_mgdl ? `${a.glucose_start_mgdl} / ${nz(a.glucose_min_mgdl)}` : dash}</td><td>${a.hypo_events ? chip("verdict-red", "hypo") : a.hypo_events === 0 ? "non" : dash}</td></tr>`);
  mount($("#main"), h`${head("Séances", "La méthode de charge est toujours indiquée : puissance, série de FC, FC moyenne ou effort perçu.")}<div class="table-wrap"><table class="data"><thead><tr><th>Date</th><th>Discipline</th><th class="num">Durée</th><th class="num">Distance</th><th class="num">D+</th><th class="num">FC moy.</th><th class="num">Charge</th><th class="num">Endurance</th><th class="num">Gly. départ / min</th><th>Hypo</th></tr></thead><tbody>${tr}</tbody></table></div>`);
}

/* ------------------------------------------------------------------ calendrier */

let ONLY_PICKED = false;
async function viewCalendar() {
  const d = await api("/api/calendar");
  const list = d.races.filter((r) => !ONLY_PICKED || r.picked);
  const months = [...new Set(list.map((r) => r.date.slice(0, 7)))];
  const body = months.map((m) => {
    const rs = list.filter((r) => r.date.startsWith(m));
    const name = new Intl.DateTimeFormat("fr-FR", { month: "long", year: "numeric" }).format(F.parseDate(`${m}-15`));
    return h`<tbody><tr class="month"><th colspan="5"><span class="month__name">${name}</span><span class="month__totals">${rs.length} manche(s)</span></th></tr>${rs.map((r) => h`<tr class="${r.picked ? "is-picked" : ""}"><th scope="row" class="nowrap">${F.weekday(r.date)} ${F.dayShort(r.date)}</th><td>${r.place}</td><td>${r.organizer}</td><td>${r.picked ? chip("verdict-green", "Retenue") : ""}</td><td>${/CHAMPIONNAT|NATIONAL/i.test(r.place) ? chip("verdict-amber", "Championnat") : ""}</td></tr>`)}</tbody>`;
  });
  mount($("#main"), h`${head("Calendrier", "Cyclo-cross UFOLEP 2026-2027 (Nord) — source cyclismeufolep5962.fr, à vérifier avant de s'inscrire.")}
    <div class="toolbar"><a class="seg ${ONLY_PICKED ? "" : "is-on"}" href="#/calendrier" data-picked="0">Toutes</a><a class="seg ${ONLY_PICKED ? "is-on" : ""}" href="#/calendrier" data-picked="1">Retenues</a></div>
    ${d.note ? h`<p class="note">${d.note}</p>` : ""}
    ${list.length ? h`<div class="table-wrap"><table class="data"><thead><tr><th>Date</th><th>Lieu</th><th>Organisateur</th><th></th><th></th></tr></thead>${body}</table></div>` : emptyBox("Aucune course", "Le calendrier est absent ou aucune course n'est retenue.", "")}`);
  $("#main").querySelectorAll("[data-picked]").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); ONLY_PICKED = a.dataset.picked === "1"; viewCalendar(); }));
}

/* ------------------------------------------------------------------ décisions */

async function viewDecisions() {
  const d = await api("/api/decisions");
  if (!d.decisions.length) { mount($("#main"), h`${head("Décisions")}${emptyBox("Aucune décision tracée", "Un changement de séance causé par un garde-fou, un bilan matinal ou ta demande laisse une trace ici.", "")}`); return; }
  const O = { applied: "outcome-applied", proposed: "outcome-proposed", rejected_by_athlete: "outcome-rejected_by_athlete", superseded: "outcome-superseded" };
  const sum = (o) => (o ? o.plan || Object.entries(o).map(([k, v]) => `${k} : ${typeof v === "object" ? JSON.stringify(v) : v}`).join(" · ") : "");
  const li = d.decisions.map((x) => h`<li><span><strong>${x.title}</strong> ${chip(O[x.outcome] || "status-planned", F.DECISION_OUTCOME[x.outcome] || x.outcome)} ${x.trigger ? chip("status-planned", F.TRIGGER[x.trigger] || x.trigger) : ""}</span><span class="list__meta">${F.dateLong(x.date)}${x.rule_ids ? " · règles " + x.rule_ids.join(", ") : ""}</span>${x.before ? h`<span class="list__meta">Avant : ${sum(x.before)}</span>` : ""}${x.after ? h`<span class="list__meta">Après : ${sum(x.after)}</span>` : ""}</li>`);
  mount($("#main"), h`${head("Décisions", "Journal des changements : ce qui a été modifié, pourquoi, et où en est la proposition.")}<ul class="list">${li}</ul>`);
}

/* ------------------------------------------------------------------ poids */

async function viewWeight() {
  const d = await api("/api/weight");
  const last = d.points[d.points.length - 1];
  const tr = d.trend;
  const lock = d.locked ? h`<div class="verdict verdict--none"><div class="verdict__word">Aucun déficit planifié</div><p class="verdict__why">Verrou médical actif : un déficit change les besoins en insuline et le risque d'hypoglycémie. Il se lève quand tu confirmes l'accord de ton équipe de diabétologie (<code>medical_clearance_confirmed</code>).</p></div>` : "";
  const facts = h`<dl class="facts"><div><dt>Dernière pesée</dt><dd>${last ? `${F.num(last.weight_kg, 1)} kg` : dash}</dd></div><div><dt>Tendance</dt><dd>${tr?.trend_kg_per_week != null ? `${tr.trend_kg_per_week > 0 ? "+" : ""}${F.num(tr.trend_kg_per_week, 2)} kg/sem.` : dash}</dd></div><div><dt>Poids du profil</dt><dd>${d.profile_kg ? `${d.profile_kg} kg` : dash}</dd></div><div><dt>Cible</dt><dd>${d.target_kg ? `${d.target_kg} kg` : "non définie"}</dd></div></dl>`;
  mount($("#main"), h`${head("Poids", "On raisonne sur la tendance (moyenne exponentielle), jamais sur une pesée isolée.")}${lock}<section class="band"><h2>Pesées</h2>${facts}<div id="chart" class="chart-host"></div><p class="readout" id="readout"></p>${tr?.warning ? h`<p class="note">${tr.warning}</p>` : ""}${!last ? h`<p class="muted">Aucune pesée enregistrée.</p>` : ""}</section>`);
  if (d.points.length >= 3 && tr?.series) {
    const dates = tr.series.map((x) => x.date);
    const ch = timeChart(dates, [{ type: "line", values: tr.series.map((x) => x.trend_kg), cls: "line line--weight-avg" }, { type: "dots", values: tr.series.map((x) => x.weight_kg), cls: "dot dot--weight" }],
      d.target_kg ? [{ type: "hline", value: d.target_kg, cls: "mark mark--target", label: "cible" }] : [], { height: 220, label: "Poids et tendance", yFormat: (v) => `${v} kg` });
    mount($("#chart"), raw(ch.svg));
    attachCursor($("#chart"), ch, (i) => { const x = tr.series[i]; mount($("#readout"), h`<strong>${F.dayLong(x.date)}</strong> · ${F.num(x.weight_kg, 1)} kg · tendance ${F.num(x.trend_kg, 2)} kg`); });
  }
}

/* ------------------------------------------------------------------ cadre : navigation, thème, routeur */

const VIEWS = { "": viewToday, forme: viewForm, sante: viewHealth, semaine: viewWeek, seances: viewActivities, calendrier: viewCalendar, decisions: viewDecisions, poids: viewWeight };

function renderNav(route) {
  mount($("#nav"), raw(navItems(STATE.summary).map(([r, label]) => `<a href="#/${r}" ${r === route ? 'aria-current="page"' : ""}>${F.esc(label)}</a>`).join("")));
}

async function go() {
  const route = (location.hash.replace(/^#\/?/, "") || "").split("/")[0];
  const view = VIEWS[route] || viewToday;
  renderNav(VIEWS[route] ? route : "");
  const main = $("#main");
  main.setAttribute("aria-busy", "true");
  try { await view(); } catch (e) { mount(main, emptyBox("Données indisponibles", `La page n'a pas pu lire ${e.message}. Le serveur local tourne-t-il toujours ?`, "./scripts/dashboard.sh")); }
  main.removeAttribute("aria-busy");
  main.focus({ preventScroll: true });
}

function setupTheme() {
  try { const t = localStorage.getItem("theme"); if (t) document.documentElement.dataset.theme = t; } catch (e) { /* stockage indisponible */ }
  $("#theme").addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme === "dark" || (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
    const next = dark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch (e) { /* stockage indisponible */ }
  });
}

// Rechargement dynamique : la page sonde l'empreinte des fichiers (30 s, seulement onglet visible) et relit la vue quand
// elle change — modifier le plan depuis le mobile apparaît sans rien relancer.
let VERSION = null;
async function watch() {
  if (document.hidden) return;
  try {
    const v = (await api("/api/version")).version;
    if (VERSION && v !== VERSION) { STATE.summary = await api("/api/summary"); renderObjective(STATE.summary); go(); }
    VERSION = v;
  } catch (e) { /* serveur momentanément indisponible : on réessaie au prochain tour */ }
}

(async function main() {
  setupTheme();
  setInterval(watch, 30000);
  document.addEventListener("visibilitychange", watch);
  watch();
  try { STATE.summary = await api("/api/summary"); renderObjective(STATE.summary); } catch (e) { STATE.summary = { disciplines: [] }; }
  window.addEventListener("hashchange", go);
  go();
})();
