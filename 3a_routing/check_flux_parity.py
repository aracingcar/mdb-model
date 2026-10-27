"""Full-record Python/JS hydrology parity using exported topology, without rebuilding map geometry."""
import base64
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for folder in ('1_masking', '2a_rainfall_runoff', '3a_routing'):
    sys.path.insert(0, str(ROOT / folder))
from config import DISPLAY_SYSTEMS, RUN_KEY, SYSTEM_ID
from run_rainfall_runoff import model_specs as rr_specs, run_rainfall_runoff
from run_routing import model_specs as routing_specs
import muskingum
from channel_fluxes import channel_inputs
from nodes import basin_outlets


def check():
    e = json.loads((ROOT / 'docs/data' / f"engine_{SYSTEM_ID}_{'_'.join(RUN_KEY)}.json").read_text())
    basins = pd.DataFrame(e['basins']).rename(columns={'id':'subcatchment', 'area':'area_km2', 'next':'next_id', 'lossRank':'from_outlet'})
    nodes = pd.DataFrame(e['nodes']).rename(columns={'area':'area_km2', 'length':'length_km', 'lossRank':'loss_rank'})
    if 'storage' not in nodes:
        nodes['storage'] = ''
    nodes['storage'] = nodes.storage.fillna('')
    nb = len(basins)
    raw = np.frombuffer(base64.b64decode(e['P']), dtype='<u2').reshape(nb, -1)
    n = raw.shape[1]
    columns = {}
    climate = {b:{} for b in basins.subcatchment}
    for var in ('P', 'PET'):
        data = np.frombuffer(base64.b64decode(e[var]), dtype='<u2').reshape(nb,n) / e['scale']
        for i,b in enumerate(basins.subcatchment):
            columns[f'{b}_{var}'] = data[i]
            climate[b][var] = data[i].tolist()
    forcing = pd.DataFrame(columns, index=pd.RangeIndex(n))
    outlet = next(b['id'] for b in e['basins'] if not b['next'])
    outlets = basin_outlets(nodes)
    for rr, rt in itertools.product(rr_specs(), routing_specs()):
        runoff = run_rainfall_runoff(forcing, basins, rr)
        p = {**routing_specs()[rt]['params'], **e['calibration']}
        channel = channel_inputs(runoff, nodes, basins, forcing, p, muskingum.delivery)
        loss = muskingum._calibrate_loss(runoff, nodes, basins, outlets[outlet], p, channel)
        py = muskingum._route(runoff, nodes, loss, p, channel)
        request = dict(runoff=[runoff[b].tolist() for b in basins.subcatchment], basins=e['basins'], nodes=e['nodes'], p=p, climate=climate)
        script = "const fs=require('fs'),e=require(process.argv[1]),d=JSON.parse(fs.readFileSync(process.argv[2]));const r=e.ROUTING.muskingum(d.runoff,d.basins,d.p,d.nodes,d.climate);fs.writeFileSync(process.argv[3],JSON.stringify({loss:r.loss,flow:r.basinFlow.map(a=>Array.from(a))}));"
        with tempfile.TemporaryDirectory() as tmp:
            inp, out = Path(tmp)/'input.json', Path(tmp)/'output.json'
            inp.write_text(json.dumps(request, allow_nan=False))
            subprocess.run(['node','-e',script,str(ROOT/'docs/engine.js'),str(inp),str(out)],check=True)
            js = json.loads(out.read_text())
        np.testing.assert_allclose(js['loss'], loss, atol=1e-12)
        worst = 0.
        for i,b in enumerate(basins.subcatchment):
            values = py[outlets[b]].to_numpy() * 86.4 if b in outlets else np.zeros(n)
            np.testing.assert_allclose(js['flow'][i], values, atol=1e-7, rtol=1e-10)
            worst = max(worst, float(np.max(np.abs(values - js['flow'][i]))))
        print(f'{SYSTEM_ID} {rr} + {rt}: {n} days, max difference {worst:.3g} ML/day', flush=True)


if __name__ == '__main__':
    if 'SYSTEM' in os.environ:
        check()
    else:
        for system in DISPLAY_SYSTEMS:
            subprocess.run([sys.executable,__file__],env={**os.environ,'SYSTEM':system},check=True)
