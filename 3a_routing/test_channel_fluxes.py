"""Run with python -m unittest discover -s 3a_routing -p 'test_*.py'."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '1_masking'))
from channel_fluxes import channel_inputs
from routing import route_network


class ChannelFluxTests(unittest.TestCase):
    def test_units_and_no_double_counting(self):
        index = pd.date_range('2000-01-01', periods=2)
        runoff = pd.DataFrame({'B': [1., 1.]}, index=index)
        nodes = pd.DataFrame([dict(id='n', basin='B', share=1., area_km2=1., length_km=10.)])
        basins = pd.DataFrame([dict(subcatchment='B', area_km2=1.)])
        forcing = pd.DataFrame({'B_P': [5., 0.], 'B_PET': [5., 0.]}, index=index)
        params = dict(channel_width_m=20., pet_factor=1., seepage_ML_day_km=.02, misc_loss_per_km=.001)
        lateral, flux = channel_inputs(runoff, nodes, basins, forcing, params, lambda p, b: 1.)
        np.testing.assert_allclose(lateral['n'], .8)
        self.assertAlmostEqual(flux['n']['rain_m3s'][0] * 86.4, 1.)
        self.assertAlmostEqual(flux['n']['evap_m3s'][0] * 86.4, 1.)
        self.assertAlmostEqual(flux['n']['seepage_m3s'] * 86.4, .2)
        with self.assertRaises(ValueError):
            channel_inputs(runoff, nodes, basins, None, params, lambda p, b: 1.)

    def test_dry_limits_budget_and_split(self):
        index = pd.RangeIndex(3)
        lateral = {n: pd.Series(v, index=index) for n, v in {'a':[0., 10., 0.], 'b':[0., 0., 0.], 'c':[0., 0., 0.]}.items()}
        reaches = {n: dict(k_days=0., x=.2) for n in lateral}
        reaches['a'].update(rain_m3s=[0., 2., 1.], evap_m3s=2., seepage_m3s=1., loss=.1)
        out = route_network(lateral, {'a':'b', 'b':'', 'c':''}, reaches, {'a':{'c':.05}})
        np.testing.assert_allclose(out.a, [0., 8.1, 0.])
        np.testing.assert_allclose(out.b, out.a * .95)
        np.testing.assert_allclose(out.c, out.a * .05)
        budget = out.attrs['channel_budget']['a']
        np.testing.assert_allclose(budget.routed_m3s + budget.rain_m3s,
            budget.after_fluxes_m3s + budget.evap_m3s + budget.seepage_m3s + budget.misc_m3s)
        self.assertEqual(budget.evap_m3s.iloc[0], 0.)
        reaches['a']['rain_m3s'] = -1
        with self.assertRaises(ValueError):
            route_network(lateral, {'a':'b', 'b':'', 'c':''}, reaches)

    def test_calibration_bounds_and_reachable_target(self):
        import muskingum
        from unittest.mock import patch
        basins = pd.DataFrame({'from_outlet': [1]})
        p = {**muskingum.PARAMS, 'loss_regions': 1, 'target_outlet_m3s': 5., 'target_scale': 1.}
        # A simple monotone response isolates the residual fitter and its bounds.
        def response(runoff, nodes, coefficient, params, channel):
            return pd.DataFrame({'outlet': [10 * np.exp(-10 * coefficient)]})
        with patch.object(muskingum, '_route', side_effect=response):
            fitted = muskingum._calibrate_loss(None, None, basins, 'outlet', p, None)
            self.assertAlmostEqual(fitted, np.log(2) / 10, places=7)
            with self.assertWarns(UserWarning):
                self.assertEqual(muskingum._calibrate_loss(None, None, basins, 'outlet', {**p, 'target_outlet_m3s':20}, None), 0)
            with self.assertWarns(UserWarning):
                self.assertEqual(muskingum._calibrate_loss(None, None, basins, 'outlet', {**p, 'target_outlet_m3s':0}, None), 1)
        self.assertEqual(muskingum._calibrate_loss(None, None, basins, 'outlet', {**p, 'target_outlet_m3s':None}, None), p['misc_loss_per_km'])

    def test_python_browser_flux_parity(self):
        # Actual Muskingum routing, joins, split, storage, wet and dry days.
        import muskingum
        n = 30
        index = pd.RangeIndex(n)
        nodes = pd.DataFrame([dict(id=b, basin=b, share=1., area_km2=50., length_km=length,
            next=down, loss_rank=1 if b=='c' else 0, outlet=True, storage='')
            for b, length, down in [('a',90.,'c'),('b',100.,'c'),('c',80.,'d'),('d',70.,''),('e',60.,'')]])
        basins = pd.DataFrame([dict(subcatchment=r.id, area_km2=50., next_id=r.next) for r in nodes.itertuples()])
        runoff = pd.DataFrame({b: np.where(np.arange(n)%9 < 3, 0., 2.) for b in basins.subcatchment}, index=index)
        forcing = pd.DataFrame({f'{b}_{v}': np.full(n, 2. if v=='P' else 5.) for b in runoff for v in ('P','PET')}, index=index)
        p = {**muskingum.PARAMS, 'loss_regions':1, 'target_outlet_m3s':None}
        lateral, fluxes = channel_inputs(runoff, nodes, basins, forcing, p, muskingum.delivery)
        reaches = {r.id: dict(k_days=r.length_km/p['velocity_km_day'], x=p['x'],
            loss=-np.expm1(-p['misc_loss_per_km']*r.length_km), **fluxes[r.id]) for r in nodes.itertuples()}
        reaches['d']['max_release'] = 1.
        py = route_network(lateral, dict(zip(nodes.id,nodes.next)), reaches, {'c':{'e':.05}})
        data = dict(runoff=[runoff[b].tolist() for b in runoff], basins=[dict(id=r.id, area=50., next=r.next) for r in nodes.itertuples()],
            params=p, nodes=[dict(id=r.id, basin=r.basin, share=1., area=50., length=r.length_km, next=r.next,
                outlet=True, lossRank=r.loss_rank, **({'splits':{'e':.05}} if r.id=='c' else {}),
                **({'maxRelease':86.4} if r.id=='d' else {})) for r in nodes.itertuples()],
            climate={b:{v:forcing[f'{b}_{v}'].tolist() for v in ('P','PET')} for b in runoff})
        script = "const e=require('./docs/engine.js'); let s='';process.stdin.on('data',d=>s+=d);process.stdin.on('end',()=>{const d=JSON.parse(s);console.log(JSON.stringify(e.ROUTING.muskingum(d.runoff,d.basins,d.params,d.nodes,d.climate,true),(_,v)=>ArrayBuffer.isView(v)?Array.from(v):v));});"
        result = subprocess.run(['node','-e',script], input=json.dumps(data), text=True, capture_output=True, check=True, cwd=Path(__file__).resolve().parents[1])
        js = json.loads(result.stdout)
        for i,b in enumerate(runoff):
            np.testing.assert_allclose(py[b] * 86.4, js['basinFlow'][i], atol=1e-10)
            for pk,jk in [('rain_m3s','rain'),('evap_m3s','evaporation'),('seepage_m3s','seepage'),('misc_m3s','misc')]:
                np.testing.assert_allclose(py.attrs['channel_budget'][b][pk]*86.4, js['channelBudget'][b][jk], atol=1e-10)


if __name__ == '__main__':
    unittest.main()
