"""Run with python -m unittest discover -s 3_routing -p 'test_*.py'."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '1_masking'))
import config
from nodes import check_network
from routing import MAX_K_DAYS, route_network

ENGINE = {s: ROOT / 'docs' / 'data' / f"engine_{s}_{'_'.join(config.DEFAULT_RUN)}.json" for s in config.DISPLAY_SYSTEMS}
ENGINE = {s: f for s, f in ENGINE.items() if f.exists()}  # systems with built engine data (the network the page and the model route)
MURRAY_OUTLET = 'B5080589480'  # the Murray at the South Australian border: the end of everything modelled


def engine(system):
    return json.loads(ENGINE[system].read_text())


def frame(nodes):
    return pd.DataFrame({'id': [n['id'] for n in nodes], 'next': [n['next'] for n in nodes]})


def outlet_nodes(data):
    """{basin: the node its flow is read at}, as muskingum.basin_outlets and engine.js read it."""
    out = {n['basin']: n['id'] for n in data['nodes'] if n['outlet']}
    out.update({b: n['id'] for n in data['nodes'] for b in n.get('reports') or []})
    return out


def end(down, i):
    while down[i]:
        i = down[i]
    return i


class CheckNetworkTests(unittest.TestCase):
    def test_refuses_loops_missing_nodes_and_repeated_ids(self):
        ok = pd.DataFrame({'id': ['a', 'b', 'c', 'd'], 'next': ['c', 'c', 'd', '']})
        self.assertIs(check_network(ok), ok)
        for ids, nxt, message in [(['a', 'b', 'c'], ['b', 'c', 'a'], 'loops'), (['a', 'b'], ['b', 'b'], 'loops'),
                                  (['a', 'b'], ['x', ''], 'do not exist'), (['a', 'a'], ['', ''], 'repeated')]:
            with self.subTest(ids=ids, next=nxt), self.assertRaisesRegex(ValueError, message):
                check_network(pd.DataFrame({'id': ids, 'next': nxt}))


class StoredNetworkTests(unittest.TestCase):
    def test_every_system_is_a_dag_ending_at_its_outlet(self):
        self.assertTrue(ENGINE, 'no engine data in docs/data')
        for system in ENGINE:
            with self.subTest(system=system):
                data = engine(system)
                check_network(frame(data['nodes']), system)
                down = {n['id']: n['next'] for n in data['nodes']}
                basin = {n['id']: n['basin'] for n in data['nodes']}
                outlets = {b['id'] for b in data['basins'] if not b['next']}
                self.assertEqual({basin[end(down, i)] for i in down} - outlets, set(), 'rivers ending away from the system outlet')
                for n in data['nodes']:
                    self.assertTrue(all(to == '' or to in down for to in n.get('splits', {})), f'{n["id"]} splits to a missing node')
                    self.assertLessEqual(sum(n.get('splits', {}).values()), 1)
                    self.assertTrue(n['length'] is None or (np.isfinite(n['length']) and n['length'] >= 0), f'{n["id"]} length')
                self.assertLessEqual(outlets, set(outlet_nodes(data)), 'a system outlet basin with no node reporting its flow')

    def test_systems_join_into_one_dag_ending_at_the_murray(self):
        """Every modelled node, followed downstream within its system and on through LINKS, reaches the Murray at the border."""
        down, systems = {}, {s: engine(s) for s in ENGINE}
        for s, data in systems.items():
            down.update({f"{s}:{n['id']}": f"{s}:{n['next']}" if n['next'] else '' for n in data['nodes']})
        for link in config.LINKS:
            if link['from'] not in systems or link['to'] not in systems:
                continue
            source, target = systems[link['from']], systems[link['to']]
            self.assertIn(link['basin'], {b['id'] for b in source['basins'] if not b['next']}, f'{link} leaves from a basin that is not a system outlet')
            self.assertIn(link['into'], outlet_nodes(target), f'{link} enters a basin with no node')
            node = f"{link['from']}:{outlet_nodes(source)[link['basin']]}"
            self.assertEqual(down[node], '', f'{link} leaves from a node that drains on within its system')
            down[node] = f"{link['to']}:{outlet_nodes(target)[link['into']]}"
        check_network(pd.DataFrame({'id': list(down), 'next': list(down.values())}), 'linked systems')
        if 'murray' not in systems:
            self.skipTest('no Murray engine data')
        outlet = f"murray:{outlet_nodes(systems['murray'])[MURRAY_OUTLET]}"
        self.assertEqual({end(down, i) for i in down}, {outlet})

    def test_no_reach_skips_past_the_lower_darling(self):
        """Talyawalka Creek (B5080103090) rejoins the Darling above Lake Wetherell, not at Wentworth 700 km away."""
        if 'lower_darling' not in ENGINE:
            self.skipTest('no Lower Darling engine data')
        node = next(n for n in engine('lower_darling')['nodes'] if n['basin'] == 'B5080103090')
        self.assertEqual(node['next'], 'N5100570770')
        self.assertLess(node['length'], 100)


class CascadeTests(unittest.TestCase):
    def route_one(self, k, inflow, x=0.2):
        index = pd.RangeIndex(len(inflow))
        return route_network({'a': pd.Series(inflow, index=index)}, {'a': ''}, {'a': {'k_days': k, 'x': x}})['a'].to_numpy()

    def test_long_reach_keeps_volume_and_travel_time(self):
        pulse = np.zeros(400)
        pulse[5] = 100.0
        for k in (1.5, 2.4, 3.0, 8.08):  # 8.08 d: the Lachlan's or a 700 km reach at 1 m/s
            with self.subTest(k=k):
                out = self.route_one(k, pulse)
                self.assertTrue(np.all(out >= -1e-12))
                np.testing.assert_allclose(out.sum(), pulse.sum(), rtol=1e-9)  # nothing left in channel storage after the long dry tail
                lag = (out * np.arange(len(out))).sum() / out.sum() - 5
                self.assertAlmostEqual(lag, k, delta=0.02)  # Muskingum's mean lag is K: the cascade keeps the whole reach's
        self.assertLess(self.route_one(8.08, pulse).max(), self.route_one(2.4, pulse).max())  # longer reach, more attenuation

    def test_short_reaches_are_unchanged(self):
        from scipy.signal import lfilter, lfilter_zi
        inflow = np.abs(np.sin(np.arange(60) / 4)) * 10 + 1
        k, x = 2.0, 0.2
        d = 2 * k * (1 - x) + 1
        b, a = [(1 - 2 * k * x) / d, (1 + 2 * k * x) / d], [1.0, -(2 * k * (1 - x) - 1) / d]
        np.testing.assert_allclose(self.route_one(k, inflow), lfilter(b, a, inflow, zi=lfilter_zi(b, a) * inflow[0])[0])
        self.assertLessEqual(MAX_K_DAYS * 2 * 0.2, 1.0)  # each sub-reach is stable at the default x
        with self.assertRaises(ValueError):
            self.route_one(np.nan, inflow)

    def test_network_water_balance_from_headwaters_to_outlet(self):
        """Two headwaters, a long reach, a junction, a split off the river and channel fluxes: what goes in comes out."""
        n = 500
        index = pd.RangeIndex(n)
        t = np.arange(n)
        wet = np.where((t % 40 >= 2) & (t % 40 < 10) & (t < 300), 20.0, 0.0)  # storms from a dry start, then a long dry tail to drain storage
        lateral = {'h1': pd.Series(wet, index=index), 'h2': pd.Series(wet * 0.5, index=index),
                   'j': pd.Series(np.zeros(n), index=index), 'o': pd.Series(np.zeros(n), index=index)}
        downstream = {'h1': 'j', 'h2': 'j', 'j': 'o', 'o': ''}
        reaches = {'h1': {'k_days': 6.5, 'x': 0.2, 'rain_m3s': np.where((t % 40 == 5) & (t < 300), 0.5, 0.0), 'evap_m3s': 0.2, 'seepage_m3s': 0.1, 'loss': 0.05},
                   'h2': {'k_days': 0.3, 'x': 0.2}, 'j': {'k_days': 2.0, 'x': 0.2, 'loss': 0.02}, 'o': {'k_days': 3.1, 'x': 0.15}}
        out = route_network(lateral, downstream, reaches, {'j': {'': 0.1}})
        budget = out.attrs['channel_budget']
        gains = sum(s.sum() for s in lateral.values()) + sum(b.rain_m3s.sum() for b in budget.values())
        losses = sum((b.evap_m3s + b.seepage_m3s + b.misc_m3s).sum() for b in budget.values())
        split_off = 0.1 * out['j'].sum()
        np.testing.assert_allclose(out['o'].sum() + losses + split_off, gains, rtol=1e-8)
        self.assertLess(out['o'].iloc[-1], 1e-9)  # storage at the end has drained: the balance above closes with no residual

    def test_python_browser_cascade_parity(self):
        import muskingum
        n, length = 120, 650.0
        index = pd.RangeIndex(n)
        runoff = pd.DataFrame({'a': np.where(np.arange(n) % 30 < 4, 5.0, 0.2), 'b': np.full(n, 0.5)}, index=index)
        p = {**muskingum.PARAMS, 'loss_regions': None, 'target_outlet_m3s': None, 'channel_width_m': 0.0, 'seepage_ML_day_km': 0.0}
        py = route_network({'a': runoff['a'], 'b': runoff['b']}, {'a': 'b', 'b': ''},
                           {'a': {'k_days': length / p['velocity_km_day'], 'x': p['x'], 'loss': -np.expm1(-p['misc_loss_per_km'] * length)},
                            'b': {'k_days': 10.0 / p['velocity_km_day'], 'x': p['x'], 'loss': -np.expm1(-p['misc_loss_per_km'] * 10.0)}})
        data = dict(runoff=[runoff[b].tolist() for b in runoff], basins=[dict(id='a', area=50., next='b'), dict(id='b', area=50., next='')], params=p,
                    nodes=[dict(id='a', basin='a', share=1., area=50., length=length, next='b', outlet=True, lossRank=0),
                           dict(id='b', basin='b', share=1., area=50., length=10.0, next='', outlet=True, lossRank=0)],
                    climate={b: {'P': [0.0] * n, 'PET': [0.0] * n} for b in runoff})
        script = "const e=require('./docs/engine.js');let s='';process.stdin.on('data',d=>s+=d);process.stdin.on('end',()=>{const d=JSON.parse(s);console.log(JSON.stringify(Array.from(e.ROUTING.muskingum(d.runoff,d.basins,d.params,d.nodes,d.climate).basinFlow,a=>Array.from(a))));});"
        js = json.loads(subprocess.run(['node', '-e', script], input=json.dumps(data), text=True, capture_output=True, check=True, cwd=ROOT).stdout)
        for i, b in enumerate(runoff):
            np.testing.assert_allclose(py[b] * 86.4, js[i], atol=1e-10)


if __name__ == '__main__':
    unittest.main()
