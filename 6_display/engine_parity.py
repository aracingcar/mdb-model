"""Check that docs/engine.js (the browser engine) reproduces the Python pipeline for every method pair and river system.

Python runs from the same quantised basin forcing that the browser receives, so any difference is the algorithms.
Usage: python 6_display/engine_parity.py   (needs node on the PATH; each displayed river system runs in its own process)
"""
import base64
import itertools
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
for folder in ("1_masking", "2_rainfall_runoff", "3_routing", "4_ecology", "5_outputs"):
    sys.path.insert(0, str(ROOT / folder))

from config import DISPLAY_SYSTEMS, RUN_KEY, SDL_UNITS, SYSTEM_ID, UNITS
from results_db import load_climate, load_geometry
from run_ecology import run_ecology
from run_rainfall_runoff import AVAILABLE_MODELS as RR_MODELS, model_specs as rr_specs, run_rainfall_runoff
from run_routing import AVAILABLE_MODELS as ROUTING_MODELS, model_specs as routing_specs, run_routing

HARNESS = """
const fs = require('fs'), engine = require(process.argv[1]);
const {data, ref} = JSON.parse(fs.readFileSync(process.argv[2]));
let worst = 0;
for (const r of ref) {
  const out = engine.run(data.engine, data.days, data.rr[r.rr], data.routing[r.routing]);
  const rep = {};
  const d = (name, a, b) => { let m = 0; for (let i = 0; i < b.length; i++) m = Math.max(m, Math.abs(a[i] - b[i])); rep[name] = m; };
  for (const u in r.reachFlow) d('reach ' + u, out.reachFlow[u], r.reachFlow[u]);
  for (const id in r.riverFlow) d('river ' + id, out.riverFlow[id], r.riverFlow[id]);
  for (const unit in r.sdl) {
    d('flow ' + unit, out.sdl[unit].flow, r.sdl[unit].flow);
    for (const t of ['fish', 'birds', 'gum']) if ((out.sdl[unit][t] === null) !== (r.sdl[unit][t] === null)) rep[unit + ' ' + t] = 1; else for (const c in r.sdl[unit][t]) {
      const a = out.sdl[unit][t][c], b = r.sdl[unit][t][c];
      rep[unit + ' ' + t + '.' + c] = a.length === b.length && a.every((v, i) => typeof v === 'number' ? Math.abs(v - b[i]) < 1.001e-3 : v === b[i]) ? 0 : 1;
    }
  }
  const flows = Object.entries(rep).filter(([k]) => k.match(/^(flow|reach|river)/));
  const bad = Object.entries(rep).filter(([k, v]) => k.match(/^(flow|reach|river)/) ? v > 1 : v > 0);
  console.log(data.system, r.rr, '+', r.routing, bad.length ? 'MISMATCH ' + JSON.stringify(bad.slice(0, 6)) : 'ok (max flow diff ' + Math.max(...flows.map(([, v]) => v)) + ' ML/d)');
  if (bad.length) worst = 1;
}
process.exit(worst);
"""


def check_system():
    engine = json.loads((ROOT / "docs" / "data" / f"engine_{SYSTEM_ID}_{'_'.join(RUN_KEY)}.json").read_text())
    subs = pd.concat([load_geometry(u, "subcatchments") for u in UNITS], ignore_index=True)
    basins = pd.concat([load_geometry(u, "basins") for u in UNITS], ignore_index=True)
    basin_forcing = pd.concat([load_climate(u, RUN_KEY)[2] for u in UNITS], axis=1)
    names = [b["id"] for b in engine["basins"]]
    n = len(basin_forcing)
    quantised = pd.DataFrame(index=basin_forcing.index)
    for var in ("P", "PET"):
        a = np.frombuffer(base64.b64decode(engine[var]), dtype="<u2").reshape(len(names), n) / engine["scale"]
        for i, name in enumerate(names):
            quantised[f"{name}_{var}"] = a[i]
    days = basin_forcing.index.strftime("%Y-%m-%d").tolist()
    table = lambda df: None if df is None else {c: df.reset_index()[c].tolist() for c in df.reset_index().columns}

    ref = []
    for rr, routing in itertools.product(RR_MODELS, ROUTING_MODELS):
        runoff = run_rainfall_runoff(quantised, basins, rr)
        unit_flow, reach_flow, _, rivers, river_flow = run_routing(runoff, basins, subs, routing)
        sdl = {}
        for u in UNITS:
            fish, birds, gum = run_ecology(unit_flow[u], SDL_UNITS[u]["ecology"])
            if birds is not None:
                birds = {**table(birds.drop(columns="trigger_date")), "trigger_date": [None if v != v else str(v) for v in birds["trigger_date"]]}
            sdl[u] = {"flow": unit_flow[u].round(0).tolist(), "fish": table(fish if fish is None else fish.round(3)), "birds": birds,
                      "gum": table(gum if gum is None else gum.round(3))}
        ref.append({"rr": rr, "routing": routing, "sdl": sdl,
                    "reachFlow": {c: reach_flow[c].round(0).tolist() for c in reach_flow},
                    "riverFlow": {c: np.clip(river_flow[c].round(0), 0, 65535).tolist() for c in river_flow}})
    data = {"system": SYSTEM_ID, "engine": engine, "days": days, "rr": rr_specs(), "routing": routing_specs()}
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ref.json"
        path.write_text(json.dumps({"data": data, "ref": ref}, allow_nan=False))
        return subprocess.run(["node", "-e", HARNESS, str(ROOT / "docs" / "engine.js"), str(path)]).returncode


if __name__ == "__main__":
    if "SYSTEM" in os.environ:
        sys.exit(check_system())
    codes = [subprocess.run([sys.executable, __file__], env={**os.environ, "SYSTEM": s}).returncode for s in DISPLAY_SYSTEMS]
    sys.exit(max(codes))
