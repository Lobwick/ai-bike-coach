"use strict";
// Aucune injection de HTML : tout passe par textContent / createElement (les fichiers Markdown ne sont pas dignes de confiance).
const $ = (id) => document.getElementById(id);
const NS = "http://www.w3.org/2000/svg";
const JOURS = ["dim", "lun", "mar", "mer", "jeu", "ven", "sam"];

function el(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") e.className = v;
    else if (k === "style") e.style.cssText = v;   // CSSOM : autorisé par la CSP (pas de style inline)
    else e.setAttribute(k, v);
  }
  for (const k of kids) if (k != null) e.append(k.nodeType ? k : document.createTextNode(String(k)));
  return e;
}
function svg(tag, attrs, text) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v);
  if (text != null) e.textContent = text;
  return e;
}
const fmtDate = (iso) => { const d = new Date(iso + "T12:00:00"); return `${JOURS[d.getDay()]} ${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}`; };
const fmtDur = (s) => { if (!s) return "—"; const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60); return h ? `${h} h ${String(m).padStart(2, "0")}` : `${m} min`; };
const num = (v, d = 0) => (v == null ? "—" : Number(v).toFixed(d));
const get = (u) => fetch(u).then((r) => { if (!r.ok) throw new Error(u + " " + r.status); return r.json(); });
const empty = (t) => el("p", { class: "empty" }, t);

function banner(text, kind) { return el("div", { class: "banner " + (kind || "") }, text); }

function table(cols, rows, rowClass) {
  const t = el("table"), thead = el("thead"), hr = el("tr");
  cols.forEach((c) => hr.append(el("th", { class: c.n ? "n" : "" }, c.h)));
  thead.append(hr); t.append(thead);
  const tb = el("tbody");
  rows.forEach((r) => {
    const tr = el("tr", { class: rowClass ? rowClass(r) : "" });
    cols.forEach((c) => { const v = c.f(r); tr.append(el("td", { class: c.n ? "n" : "" }, v)); });
    tb.append(tr);
  });
  t.append(tb);
  return el("div", { class: "tablewrap" }, t);
}

function kpi(label, value, sub) {
  return el("div", { class: "kpi" }, el("div", { class: "l" }, label), el("div", { class: "v" }, value), el("div", { class: "s" }, sub || ""));
}

function renderSummary(s) {
  $("objective").textContent = s.objective || "Aucun objectif actif";
  $("asof").textContent = "au " + s.today;
  const k = $("kpis"); k.replaceChildren();
  const st = s.load.state, p = s.profile;
  const rel = s.load.reliable;
  k.append(kpi("Forme", rel && st ? num(st.form) : "—", rel ? "condition − fatigue" : `historique ${s.load.history_days} j (< 42)`));
  k.append(kpi("Condition", rel && st ? num(st.condition) : "—", "moyenne 42 j"));
  k.append(kpi("Fatigue", rel && st ? num(st.fatigue) : "—", "moyenne 7 j"));
  k.append(kpi("FTP", p.ftp_w ? p.ftp_w + " W" : "—", p.w_per_kg ? p.w_per_kg + " W/kg" : "profil"));
  k.append(kpi("FC de repos", p.hr_rest_bpm ? p.hr_rest_bpm + " bpm" : "—", s.resting_hr_recent ? `récent : ${s.resting_hr_recent}` : "base du profil"));
  k.append(kpi("Poids", s.weight_latest ? num(s.weight_latest.kg, 1) + " kg" : (p.weight_kg ? p.weight_kg + " kg" : "—"),
    s.weight_latest ? `pesée du ${s.weight_latest.date}` : "profil"));
  const a = $("alerts"); a.replaceChildren();
  if (!rel) a.append(banner(`Historique de charge de ${s.load.history_days} jour(s) : forme et garde-fous R1/R2/R4 non évalués (42 jours requis). Demande au coach de rapatrier tes séances depuis Open Wearables.`, "info"));
  if (s.weight_loss_locked) a.append(banner("Perte de poids : verrou médical actif, aucun déficit planifié tant que l'accord de l'équipe soignante n'est pas confirmé.", "info"));
  const nr = $("next-race"); nr.replaceChildren();
  if (s.next_race) {
    const r = s.next_race;
    const days = Math.round((new Date(r.date + "T12:00:00") - new Date(s.today + "T12:00:00")) / 86400000);
    nr.append(el("div", { class: "race-hero" }, el("span", { class: "big" }, `${fmtDate(r.date)} — ${r.venue || r.title}`),
      el("span", { class: "badge race" }, days <= 0 ? "aujourd'hui" : `dans ${days} j`)));
    if (r.organizer) nr.append(el("p", { class: "muted" }, r.organizer));
    if (r.alternatives && r.alternatives.length)
      nr.append(el("p", { class: "small muted" }, "Alternatives : " + r.alternatives.map((x) => `${fmtDate(x.date)} ${x.place}`).join(" · ")));
  } else nr.append(empty("Aucune course planifiée."));
}

function renderLoad(d) {
  const box = $("load-chart"); box.replaceChildren();
  $("load-note").textContent = d.note || "";
  $("load-title").textContent = d.reliable ? "Condition, fatigue et forme" : "Charge planifiée par semaine";
  const leg = $("load-legend"); leg.replaceChildren();
  const past = d.series || [], proj = d.projection || [];
  if (!d.reliable || past.length + proj.length < 3) {
    // pas de courbes honnêtes : barres de charge planifiée par semaine
    const w = d.weekly_planned || [];
    if (!w.length) { box.append(empty("Aucune donnée.")); return; }
    const W = 640, H = 200, pad = 36, max = Math.max(...w.map((x) => x.planned_load), 1);
    const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img" });
    const bw = (W - pad * 2) / w.length;
    w.forEach((x, i) => {
      const h = (x.planned_load / max) * (H - 60);
      s.append(svg("rect", { x: pad + i * bw + 8, y: H - 30 - h, width: bw - 16, height: h, rx: 4, fill: "var(--c-cond)", opacity: 0.85 }));
      s.append(svg("text", { x: pad + i * bw + bw / 2, y: H - 34 - h, "text-anchor": "middle", "font-size": 12, fill: "var(--ink)" }, Math.round(x.planned_load)));
      s.append(svg("text", { x: pad + i * bw + bw / 2, y: H - 12, "text-anchor": "middle", "font-size": 11, fill: "var(--muted)" }, fmtDate(x.week_start)));
    });
    box.append(s);
    leg.append(el("span", { style: "--c:var(--c-cond)" }, "Charge planifiée par semaine (estimation)"));
    return;
  }
  const all = past.concat(proj);
  const W = 720, H = 260, L = 40, R = 10, T = 12, B = 26;
  const vals = all.flatMap((r) => [r.condition, r.fatigue, r.form]);
  const lo = Math.min(...vals, 0), hi = Math.max(...vals, 1);
  const x = (i) => L + (i / Math.max(all.length - 1, 1)) * (W - L - R);
  const y = (v) => T + (1 - (v - lo) / (hi - lo || 1)) * (H - T - B);
  const s = svg("svg", { viewBox: `0 0 ${W} ${H}` });
  const zero = y(0);
  s.append(svg("line", { x1: L, x2: W - R, y1: zero, y2: zero, stroke: "var(--line)" }));
  s.append(svg("text", { x: 4, y: zero + 4, "font-size": 11, fill: "var(--muted)" }, "0"));
  const split = past.length;
  [["condition", "--c-cond", "Condition"], ["fatigue", "--c-fat", "Fatigue"], ["form", "--c-form", "Forme"]].forEach(([k, c, label]) => {
    const pts = all.map((r, i) => `${x(i).toFixed(1)},${y(r[k]).toFixed(1)}`);
    s.append(svg("polyline", { points: pts.slice(0, split).join(" "), fill: "none", stroke: `var(${c})`, "stroke-width": 2 }));
    if (proj.length) s.append(svg("polyline", { points: pts.slice(Math.max(split - 1, 0)).join(" "), fill: "none", stroke: `var(${c})`, "stroke-width": 2, "stroke-dasharray": "5 4" }));
    leg.append(el("span", { style: `--c:var(${c})` }, label));
  });
  [0, Math.floor(all.length / 2), all.length - 1].forEach((i) => s.append(svg("text", { x: x(i), y: H - 8, "font-size": 11, fill: "var(--muted)", "text-anchor": i === 0 ? "start" : i === all.length - 1 ? "end" : "middle" }, fmtDate(all[i].date))));
  box.append(s);
  if (proj.length) leg.append(el("span", { style: "--c:var(--muted)" }, "pointillés = projection du plan (estimation)"));
}

const SESSION_BADGE = { race: "race", threshold: "key", vo2max: "key", anaerobic: "key" };
function renderPlan(d) {
  const box = $("plan"); box.replaceChildren();
  if (!d.weeks.length) { box.append(empty("Aucune semaine planifiée.")); return; }
  d.weeks.forEach((w) => {
    const wk = el("div", { class: "week" });
    wk.append(el("h3", {}, `Semaine du ${fmtDate(w.week_start)} — ${w.focus || ""}`, " ", el("span", { class: "badge" }, `charge ≈ ${Math.round(w.planned_load)}`)));
    w.guardrails.filter((g) => g.severity !== "info").forEach((g) => wk.append(banner(`${g.rule} (${g.severity}) : ${g.message}`, g.severity === "block" ? "bad" : "")));
    wk.append(table([
      { h: "Jour", f: (s) => fmtDate(s.date) },
      { h: "Séance", f: (s) => s.title },
      { h: "Type", f: (s) => el("span", { class: "badge " + (s.race ? "race" : SESSION_BADGE[s.intensity] || "") }, s.race ? "course" : s.fixed ? "club (imposée)" : s.intensity || "") },
      { h: "Durée", n: 1, f: (s) => fmtDur(s.duration_s) },
      { h: "Charge", n: 1, f: (s) => (s.planned_load != null ? Math.round(s.planned_load) : "—") },
      { h: "Garmin", f: (s) => (s.template ? (s.garmin_pushed ? el("span", { class: "badge ok" }, "poussée") : el("span", { class: "badge" }, "prête")) : "—") },
    ], w.sessions.slice().sort((a, b) => a.date.localeCompare(b.date)), (s) => (s.race ? "picked" : "")));
    box.append(wk);
  });
}

function renderCalendar(d) {
  const box = $("calendar"); box.replaceChildren();
  if (d.note) box.append(el("p", { class: "muted small" }, d.note));
  if (!d.races.length) { box.append(empty("Aucune course à venir.")); return; }
  box.append(table([
    { h: "Date", f: (r) => fmtDate(r.date) },
    { h: "Lieu", f: (r) => r.place },
    { h: "Organisateur", f: (r) => r.organizer },
    { h: "", f: (r) => (r.picked ? el("span", { class: "badge race" }, "retenue") : /CHAMPIONNAT|NATIONAL/i.test(r.place) ? el("span", { class: "badge key" }, "championnat") : "") },
  ], d.races, (r) => (r.picked ? "picked" : "")));
}

function renderActivities(d) {
  const box = $("activities"); box.replaceChildren();
  if (!d.activities.length) { box.append(empty("Aucune séance enregistrée : les séances arrivent avec la synchronisation Open Wearables (/daily-sync).")); return; }
  box.append(table([
    { h: "Date", f: (a) => fmtDate(a.date) },
    { h: "Disc.", f: (a) => a.discipline },
    { h: "Durée", n: 1, f: (a) => fmtDur(a.duration_s) },
    { h: "Dist. km", n: 1, f: (a) => (a.distance_m ? num(a.distance_m / 1000, 1) : "—") },
    { h: "D+ m", n: 1, f: (a) => num(a.elevation_gain_m) },
    { h: "FC moy.", n: 1, f: (a) => num(a.avg_hr_bpm) },
    { h: "Charge", n: 1, f: (a) => (a.load != null ? `${num(a.load)} (${a.load_method || "?"})` : "—") },
    { h: "Gly. départ/min", n: 1, f: (a) => (a.glucose_start_mgdl ? `${a.glucose_start_mgdl}/${a.glucose_min_mgdl ?? "—"}` : "—") },
    { h: "Hypo", n: 1, f: (a) => (a.hypo_events ? el("span", { class: "badge bad" }, "oui") : a.hypo_events === 0 ? "non" : "—") },
  ], d.activities));
}

function renderHealth(d) {
  const box = $("health"); box.replaceChildren();
  if (!d.days.length) { box.append(empty("Aucun bilan santé enregistré.")); return; }
  const V = { green: ["ok", "vert"], amber: ["key", "orange"], red: ["bad", "rouge"] };
  box.append(table([
    { h: "Date", f: (h) => fmtDate(h.date) },
    { h: "Verdict", f: (h) => (h.verdict ? el("span", { class: "badge " + V[h.verdict][0] }, V[h.verdict][1]) : "—") },
    { h: "FC repos", n: 1, f: (h) => num(h.resting_hr_bpm) },
    { h: "HRV ms", n: 1, f: (h) => num(h.hrv_rmssd_ms) },
    { h: "Sommeil", n: 1, f: (h) => (h.sleep_min ? fmtDur(h.sleep_min * 60) : "—") },
    { h: "TIR %", n: 1, f: (h) => num(h.tir_pct) },
    { h: "< 70 %", n: 1, f: (h) => num(h.time_below_pct, 1) },
    { h: "Hypo nuit", f: (h) => (h.nocturnal_low ? el("span", { class: "badge bad" }, "oui") : h.nocturnal_low === false ? "non" : "—") },
    { h: "Poids", n: 1, f: (h) => num(h.weight_kg, 1) },
  ], d.days.slice().reverse()));
}

async function main() {
  const jobs = [["/api/summary", renderSummary], ["/api/load", renderLoad], ["/api/plan", renderPlan],
    ["/api/calendar", renderCalendar], ["/api/activities", renderActivities], ["/api/health", renderHealth]];
  const failed = [];
  await Promise.all(jobs.map(async ([u, f]) => { try { f(await get(u)); } catch (e) { failed.push(u); } }));
  $("foot").textContent = failed.length ? "erreurs : " + failed.join(", ") : "à jour " + new Date().toLocaleTimeString("fr-FR");
}
main();
