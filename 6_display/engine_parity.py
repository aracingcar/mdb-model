"""Check that docs/engine.js (the browser engine) reproduces the Python pipeline for every method pair and river system.

Python runs from the same quantised basin forcing that the browser receives, so any difference is the algorithms.
Usage: python 6_display/engine_parity.py [systems ...] [--changed] [--methods NAME ...] [--years START-END]
(needs node on the PATH; each displayed river system runs in its own process)
  systems    only these river systems (default: all displayed ones)
  --changed  only the systems and methods affected by files changed since origin/main (and in the working tree)
  --methods  only these rainfall-runoff or routing methods, e.g. gr4j_2 muskingum_2
  --years    only these years of the forcing, e.g. 2027-2036 (about a tenth of the days: a fast check; the full run is the real one)
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
for folder in ("1_masking", "2a_rainfall_runoff", "3a_routing", "4_ecology", "5_outputs"):
    sys.path.insert(0, str(ROOT / folder))

from config import DISPLAY_SYSTEMS, LINKS, RUN_KEY, SDL_UNITS, SYSTEM_ID, UNITS
from muskingum import link_flow
from results_db import load_climate, load_geometry
from run_ecology import run_ecology
from run_rainfall_runoff import AVAILABLE_MODELS as RR_MODELS, model_specs as rr_specs, run_rainfall_runoff
from run_routing import AVAILABLE_MODELS as ROUTING_MODELS, model_specs as routing_specs, run_routing

HARNESS = """
const fs = require('fs'), engine = require(process.argv[1]);
const {data, ref} = JSON.parse(fs.readFileSync(process.argv[2]));
let worst = 0;
for (const r of ref) {
  const out = engine.run(data.engine, data.days, data.rr[r.rr], data.routing[r.routing], data.upstream);
  const rep = {};
  const d = (name, a, b) => { let m = 0; for (let i = 0; i < b.length; i++) m = Math.max(m, Math.abs(a[i] - b[i])); rep[name] = m; };
  for (const u in r.reachFlow) d('reach ' + u, out.reachFlow[u], r.reachFlow[u]);
  for (const id in r.riverFlow) d('river ' + id, out.riverFlow[id], r.riverFlow[id]);
  for (const unit in r.sdl) {
    d('flow ' + unit, out.sdl[unit].flow, r.sdl[unit].flow);
    for (const t of ['fish', 'birds', 'gum']) if ((out.sdl[unit][t] === null) !== (r.sdl[unit][t] === null)) rep[unit + ' ' + t] = 1; else for (const c in r.sdl[unit][t]) {
      const a = out.sdl[unit][t][c], b = r.sdl[unit][t][c];
      const same = a.length === b.length && a.every((v, i) => typeof v === 'number' ? Math.abs(v - b[i]) < 1.001e-3 : v === b[i]);
      rep[unit + ' ' + t + '.' + c] = same ? 0 : 1;
      if (!same) console.log('  differs: ' + unit + ' ' + t + '.' + c + '\\n    browser ' + JSON.stringify(a.slice(0, 12)) + '\\n    python  ' + JSON.stringify(b.slice(0, 12)));
    }
  }
  const flows = Object.entries(rep).filter(([k]) => k.match(/^(flow|reach|river)/));
  const bad = Object.entries(rep).filter(([k, v]) => k.match(/^(flow|reach|river)/) ? v > 1 : v > 0);
  console.log(data.system, r.rr, '+', r.routing, bad.length ? 'MISMATCH ' + JSON.stringify(bad.slice(0, 6)) : 'ok (max flow diff ' + Math.max(...flows.map(([, v]) => v)) + ' ML/d)');
  if (bad.length) worst = 1;
}
process.exit(worst);
"""


def _window(engine, days, years):
    """The engine's forcing and day list cut to ``years`` (START-END, inclusive)."""
    first, last = (int(y) for y in years.split("-"))
    keep = np.array([first <= int(d[:4]) <= last for d in days])
    names, n = len(engine["basins"]), len(days)
    cut = {var: base64.b64encode(np.frombuffer(base64.b64decode(engine[var]), dtype="<u2").reshape(names, n)[:, keep].astype("<u2").tobytes()).decode() for var in ("P", "PET")}
    return {**engine, **cut}, keep


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
    if os.environ.get("PARITY_YEARS"):
        engine, keep = _window(engine, days, os.environ["PARITY_YEARS"])
        quantised, days = quantised[keep], [d for d, k in zip(days, keep) if k]
    table = lambda df: None if df is None else {c: df.reset_index()[c].tolist() for c in df.reset_index().columns}

    ref = []
    only = os.environ.get("PARITY_METHODS", "").split()
    for rr, routing in itertools.product([m for m in RR_MODELS if not only or m in only or not set(only) & set(RR_MODELS)],
                                         [m for m in ROUTING_MODELS if not only or m in only or not set(only) & set(ROUTING_MODELS)]):
        runoff = run_rainfall_runoff(quantised, basins, rr)
        unit_flow, reach_flow, _, rivers, river_flow = run_routing(runoff, basins, subs, routing, basin_forcing=quantised)
        sdl = {}
        for u in UNITS:
            fish, birds, gum = run_ecology(unit_flow[u], SDL_UNITS[u]["ecology"])
            if birds is not None:
                birds = {**table(birds.drop(columns="trigger_date")), "trigger_date": [None if v is None or v != v else str(v) for v in birds["trigger_date"]]}
            sdl[u] = {"flow": unit_flow[u].round(0).tolist(), "fish": table(fish if fish is None else fish.round(3)), "birds": birds,
                      "gum": table(gum if gum is None else gum.round(3))}
        ref.append({"rr": rr, "routing": routing, "sdl": sdl,
                    "reachFlow": {c: reach_flow[c].round(0).tolist() for c in reach_flow},
                    "riverFlow": {c: np.clip(river_flow[c].round(0), 0, 65535).tolist() for c in river_flow}})
    upstream = {}  # the stored outflows of the systems feeding this one, which Python read for the same dates
    for link in (l for l in LINKS if l["to"] == SYSTEM_ID):
        upstream.setdefault(link["from"], {})[link["basin"]] = link_flow(link, quantised.index).tolist()
    data = {"system": SYSTEM_ID, "engine": engine, "days": days, "rr": rr_specs(), "routing": routing_specs(), "upstream": upstream}
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ref.json"
        path.write_text(json.dumps({"data": data, "ref": ref}, allow_nan=False))
        return subprocess.run(["node", "-e", HARNESS, str(ROOT / "docs" / "engine.js"), str(path)]).returncode


# files whose change touches only some systems or methods; any other model file touches everything
ALL_SYSTEMS_DIRS = ("1_masking/", "2a_rainfall_runoff/", "3a_routing/", "4_ecology/", "5_outputs/")
METHOD_FILES = {"2a_rainfall_runoff/gr4j_2.py": ["gr4j_2"], "2a_rainfall_runoff/gr4j.py": ["gr4j", "gr4j_2"], "3a_routing/muskingum_2.py": ["muskingum_2"]}
NO_EFFECT = ("2b_calibration/", "3b_calibration/", "downloads/", "tests/", "1_masking/download", "3a_routing/check_flux", "1_masking/run_masking")


def _git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True).stdout


def changed_scope():
    """(systems, methods) the files changed since origin/main (committed, staged, unstaged, new) can affect; methods is [] for every method."""
    files = set(_git("diff", "--name-only", "origin/main").split()) | set(_git("ls-files", "--others", "--exclude-standard").split())
    systems, methods, everything, any_method = set(), set(), False, False
    for f in sorted(files):
        if f.startswith("docs/data/engine_"):
            systems |= {s for s in DISPLAY_SYSTEMS if f.startswith(f"docs/data/engine_{s}_")}
        elif f in ("docs/engine.js", "6_display/run_display.py"):
            everything, any_method = True, True
        elif f == "1_masking/config.py":
            systems |= _config_systems()
            any_method = True
        elif f in METHOD_FILES:
            everything, methods = True, methods | set(METHOD_FILES[f])
        elif f.startswith(ALL_SYSTEMS_DIRS) and f.endswith(".py") and not f.startswith(NO_EFFECT):
            everything, any_method = True, True
    return (set(DISPLAY_SYSTEMS) if everything else systems), ([] if any_method else sorted(methods))


def _config_systems():
    """The displayed systems whose block in config.py differs from origin/main (all of them if the comparison fails)."""
    try:
        old = {}
        exec(compile(_git("show", "origin/main:1_masking/config.py"), "config_old", "exec"), {"__file__": str(ROOT / "1_masking" / "config.py"), "__name__": "config_old"}, old)
        from config import SYSTEMS
        return {s for s in DISPLAY_SYSTEMS if old["SYSTEMS"].get(s) != SYSTEMS[s]}
    except Exception:
        return set(DISPLAY_SYSTEMS)


if __name__ == "__main__":
    if "SYSTEM" in os.environ:
        sys.exit(check_system())
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("systems", nargs="*", choices=DISPLAY_SYSTEMS, help="river systems to check")
    ap.add_argument("--changed", action="store_true")
    ap.add_argument("--methods", nargs="+", default=[])
    ap.add_argument("--years")
    args = ap.parse_args()
    systems, methods = list(args.systems) or list(DISPLAY_SYSTEMS), list(args.methods)
    if args.changed:
        hit, hit_methods = changed_scope()
        systems = [s for s in systems if s in hit]
        methods = methods or hit_methods
        if not systems:
            print("engine_parity: no changed file affects the engine; nothing to check")
            sys.exit(0)
    print(f"engine_parity: {', '.join(systems)}" + (f"; methods {', '.join(methods)}" if methods else "") + (f"; years {args.years}" if args.years else ""))
    env = {**os.environ, "PARITY_METHODS": " ".join(methods), **({"PARITY_YEARS": args.years} if args.years else {})}
    codes = [subprocess.run([sys.executable, __file__], env={**env, "SYSTEM": s}).returncode for s in systems]
    sys.exit(max(codes))
