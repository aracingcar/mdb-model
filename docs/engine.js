// Browser twin of the Python hydrology: rainfall-runoff (GR4J), routing (Muskingum), river flows and the ecology scores.
// Runs in a Web Worker (see the bottom) and in Node for the parity test. Methods are chosen by `algorithm`; their
// parameters come from the Python modules (2_rainfall_runoff, 3_routing) through the page's META.
'use strict';

const ML_PER_M3S_DAY = 86.4;

// ---------- rainfall-runoff ----------
const RAINFALL_RUNOFF = {
  // GR4J (Perrin, Michel & Andreassian 2003), as in 2_rainfall_runoff/gr4j.py. Returns runoff depth in mm/day.
  gr4j(precip, pet, [x1, x2, x3, x4]) {
    const n1 = Math.ceil(x4), n2 = Math.ceil(2 * x4);
    const sh1 = t => t <= 0 ? 0 : t < x4 ? (t / x4) ** 2.5 : 1;
    const sh2 = t => t <= 0 ? 0 : t < x4 ? 0.5 * (t / x4) ** 2.5 : t < 2 * x4 ? 1 - 0.5 * (2 - t / x4) ** 2.5 : 1;
    const uh1 = Array.from({ length: n1 }, (_, i) => sh1(i + 1) - sh1(i));
    const uh2 = Array.from({ length: n2 }, (_, i) => sh2(i + 1) - sh2(i));
    const q9 = new Float64Array(n1), q1 = new Float64Array(n2);
    let s = 0.3 * x1, r = 0.5 * x3;
    const out = new Float64Array(precip.length);
    for (let t = 0; t < precip.length; t++) {
      const p = precip[t], e = pet[t];
      const pn = Math.max(p - e, 0), en = Math.max(e - p, 0);
      let ps = 0, es = 0;
      if (pn > 0) { const th = Math.tanh(pn / x1); ps = x1 * (1 - (s / x1) ** 2) * th / (1 + (s / x1) * th); }
      if (en > 0) { const th = Math.tanh(en / x1); es = s * (2 - s / x1) * th / (1 + (1 - s / x1) * th); }
      s += ps - es;
      const perc = s * (1 - (1 + (s / (4 / 9 * x1)) ** 4) ** -0.25);
      s -= perc;
      const pr = pn - ps + perc;
      q9.copyWithin(0, 1); q9[n1 - 1] = 0;
      q1.copyWithin(0, 1); q1[n2 - 1] = 0;
      for (let i = 0; i < n1; i++) q9[i] += 0.9 * pr * uh1[i];
      for (let i = 0; i < n2; i++) q1[i] += 0.1 * pr * uh2[i];
      const f = x2 * (r / x3) ** 3.5;
      r = Math.max(r + q9[0] + f, 0);
      const qr = r * (1 - (1 + (r / x3) ** 4) ** -0.25);
      r -= qr;
      out[t] = qr + Math.max(q1[0] + f, 0);
    }
    return out;
  },
};

// ---------- routing ----------
const ROUTING = {
  // Muskingum down the basin network with a calibrated lowland loss, as in 3_routing/muskingum.py.
  muskingum(runoffM3s, basins, p) {
    const names = basins.map(b => b.id), idx = Object.fromEntries(names.map((n, i) => [n, i]));
    const nDays = runoffM3s[0].length;
    const delivery = n => p.delivery[n] ?? 1;
    const lateral = basins.map((b, i) => runoffM3s[i].map(v => v * delivery(b.id)));
    const children = basins.map(() => []);
    basins.forEach((b, i) => { if (b.next) children[idx[b.next]].push(i); });
    const k = basins.map(b => Math.min(2.4, Math.max(0.7, 1.5 * Math.sqrt(b.area) / p.velocity_km_day)));
    // parents after children
    const order = [], seen = new Array(basins.length).fill(false);
    const visit = i => { if (seen[i]) return; seen[i] = true; children[i].forEach(visit); order.push(i); };
    basins.forEach((_, i) => visit(i));

    const route = loss => {
      const out = new Array(basins.length);
      for (const i of order) {
        const inflow = Float64Array.from(lateral[i]);
        for (const c of children[i]) { const o = out[c]; for (let t = 0; t < nDays; t++) inflow[t] += o[t]; }
        const x = p.x, kk = k[i], dt = 1;
        if (!(2 * kk * x <= dt && dt <= 2 * kk * (1 - x))) throw new Error('Muskingum stability requires 2*K*X <= dt <= 2*K*(1-X)');
        const d = 2 * kk * (1 - x) + dt;
        const b0 = (dt - 2 * kk * x) / d, b1 = (dt + 2 * kk * x) / d, a1 = -(2 * kk * (1 - x) - dt) / d;
        const keep = 1 - (basins[i].id !== 'LOWLAND' && basins[i].region >= p.loss_from ? loss : 0);
        // direct form II transposed, started at steady state (scipy lfilter_zi)
        let z = (b1 - a1 * b0) / (1 + a1) * inflow[0];
        const y = new Float64Array(nDays);
        for (let t = 0; t < nDays; t++) { const v = b0 * inflow[t] + z; z = b1 * inflow[t] - a1 * v; y[t] = v * keep; }
        out[i] = y;
      }
      return out;
    };

    const outletIdx = basins.findIndex(b => b.next === '');
    const mean = a => { let s = 0; for (let t = 0; t < a.length; t++) s += a[t]; return s / a.length; };
    let lo = 0, hi = 0.99;
    for (let it = 0; it < 25; it++) {
      const mid = (lo + hi) / 2;
      if (mean(route(mid)[outletIdx]) > p.target_outlet_m3s) lo = mid; else hi = mid;
    }
    const loss = (lo + hi) / 2;
    const basinFlow = route(loss).map(a => a.map(v => v * ML_PER_M3S_DAY));
    const lateralMLd = lateral.map(a => a.map(v => v * ML_PER_M3S_DAY));
    return { basinFlow, lateralMLd, loss };
  },
};

// ---------- ecology (4_ecology) ----------
const wyOf = day => +day.slice(0, 4) + (+day.slice(5, 7) >= 7 ? 1 : 0);
const monthOf = day => +day.slice(5, 7);

// (start, length) of each run of true within [from, to)
function spells(mask, from, to) {
  const out = []; let start = -1;
  for (let i = from; i < to; i++) {
    if (mask[i]) { if (start < 0) start = i; } else if (start >= 0) { out.push([start, i - start]); start = -1; }
  }
  if (start >= 0) out.push([start, to - start]);
  return out;
}

function waterYears(days) {
  const out = []; let from = 0;
  for (let i = 1; i <= days.length; i++) if (i === days.length || wyOf(days[i]) !== wyOf(days[from])) { out.push({ wy: wyOf(days[from]), from, to: i }); from = i; }
  return out;
}

const round = (v, n) => { const f = 10 ** n; return Math.round(v * f) / f; };
const isoDay = (days, i) => days[i] + ' 00:00:00';

function ecology(flow, days) {
  const years = waterYears(days);
  const fish = { water_year: [], ctf_days: [], ctf_spells: [], longest_ctf_days: [], survival: [], CF1_met: [] };
  const birds = { water_year: [], triggered: [], sustained: [], trigger_date: [] };
  const gum = { water_year: [], flood_days: [], flooded: [], years_since_flood: [], condition: [] };

  const ctf = Array.from(flow, v => v <= 1.0);
  const TRIGGER_FLOW = 15500, TRIGGER_DAYS = 9, SUSTAIN_FLOW = TRIGGER_FLOW / 2, SUSTAIN_DAYS = 90;
  const high = Array.from(flow, v => v >= TRIGGER_FLOW);
  const FLOOD_FLOW = 15000, FLOOD_DAYS = 11, MAX_DRY = 4, MAX_WET = 3, GAIN = 0.25, LOSS = 0.15;
  const inSeason = days.map(d => [8, 9, 10, 11, 12, 1, 2].includes(monthOf(d)));
  let condition = 0.7, dry = 0, wet = 0;

  for (const { wy, from, to } of years) {
    const runs = spells(ctf, from, to), nDays = runs.reduce((a, [, n]) => a + n, 0);
    fish.water_year.push(wy); fish.ctf_days.push(nDays); fish.ctf_spells.push(runs.length);
    fish.longest_ctf_days.push(runs.reduce((a, [, n]) => Math.max(a, n), 0));
    fish.survival.push(round(Math.exp(-0.02 * nDays), 3)); fish.CF1_met.push(nDays === 0);

    let trigger = -1;
    for (const [start, n] of spells(high, from, to)) if (n >= TRIGGER_DAYS && [8, 9, 10, 11, 12].includes(monthOf(days[start]))) { trigger = start; break; }
    let sustained = false;
    if (trigger >= 0) {
      const end = trigger + SUSTAIN_DAYS;  // exclusive; the series must still reach this far
      sustained = end <= flow.length && flow.slice(trigger, end).every(v => v >= SUSTAIN_FLOW);
    }
    birds.water_year.push(wy); birds.triggered.push(trigger >= 0); birds.sustained.push(sustained);
    birds.trigger_date.push(trigger >= 0 ? isoDay(days, trigger) : null);

    let fd = 0;
    for (let i = from; i < to; i++) if (flow[i] >= FLOOD_FLOW && inSeason[i]) fd++;
    const flooded = fd >= FLOOD_DAYS;
    if (flooded) { dry = 0; wet++; } else { dry++; wet = 0; }
    if (flooded && wet <= MAX_WET) condition += GAIN; else if (wet > MAX_WET || dry > MAX_DRY) condition -= LOSS;
    condition = Math.min(1, Math.max(0, condition));
    gum.water_year.push(wy); gum.flood_days.push(fd); gum.flooded.push(flooded); gum.years_since_flood.push(dry); gum.condition.push(round(condition, 3));
  }
  return { fish, birds, gum };
}

// ---------- the whole chain ----------
function b64ToU16(b64) {
  if (typeof atob === 'function') { const bin = atob(b64), u8 = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i); return new Uint16Array(u8.buffer); }
  const buf = Buffer.from(b64, 'base64'); return new Uint16Array(buf.buffer, buf.byteOffset, buf.length / 2).slice();
}

/** engine: the page's engine data file; days: the date strings; rr / routing: {algorithm, params}. */
function run(engine, days, rr, routing) {
  const nb = engine.basins.length, n = days.length;
  const P = b64ToU16(engine.P), PET = b64ToU16(engine.PET), sc = engine.scale;
  const simulate = RAINFALL_RUNOFF[rr.algorithm], route = ROUTING[routing.algorithm];
  if (!simulate || !route) throw new Error(`Unknown algorithm ${rr.algorithm} / ${routing.algorithm}`);

  const runoff = engine.basins.map((b, i) => {
    const p = Float64Array.from(P.subarray(i * n, (i + 1) * n), v => v / sc), e = Float64Array.from(PET.subarray(i * n, (i + 1) * n), v => v / sc);
    const depth = simulate(p, e, rr.params);
    return depth.map(v => v * b.area * 1000 / 86400);  // mm/day over km2 -> m3/s
  });
  const { basinFlow, lateralMLd } = route(runoff, engine.basins, routing.params);
  const at = Object.fromEntries(engine.basins.map((b, i) => [b.id, i]));

  const flow = basinFlow[at[engine.outlet]];
  const reachFlow = {};
  for (const [unit, basin] of Object.entries(engine.reachOutlet)) reachFlow[unit] = Array.from(basinFlow[at[basin]], v => Math.round(v));
  const riverFlow = {};
  for (const [id, basin, kind, share] of engine.rivers) {
    const bi = at[basin], out = new Uint16Array(n);
    for (let t = 0; t < n; t++) {
      const v = kind === 'channel' ? basinFlow[bi][t] : lateralMLd[bi][t] * share;
      out[t] = Math.min(65535, Math.max(0, Math.round(v)));
    }
    riverFlow[id] = out;
  }
  return { reachFlow, riverFlow, flow: Array.from(flow, v => Math.round(v)), ...ecology(flow, days) };
}

if (typeof module !== 'undefined') module.exports = { run, ecology, RAINFALL_RUNOFF, ROUTING };

// Worker protocol: {id, engine, days, rr, routing} in; {id, result} or {id, error} out.
if (typeof self !== 'undefined' && typeof self.postMessage === 'function' && typeof window === 'undefined') {
  self.onmessage = ({ data }) => {
    try {
      const result = run(data.engine, data.days, data.rr, data.routing);
      self.postMessage({ id: data.id, result }, Object.values(result.riverFlow).map(a => a.buffer));
    } catch (error) { self.postMessage({ id: data.id, error: String(error) }); }
  };
}
