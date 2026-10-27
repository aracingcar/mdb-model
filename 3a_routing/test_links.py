"""Run with python -m unittest discover -s 3a_routing -p 'test_*.py'."""
import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '1_masking'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '5_outputs'))
import config
import muskingum


class LinkTests(unittest.TestCase):
    def test_links_name_systems_and_run_in_order(self):
        order = config.run_order()
        self.assertEqual(sorted(order), sorted(config.DISPLAY_SYSTEMS))
        for link in config.LINKS:
            self.assertIn(link['from'], config.DISPLAY_SYSTEMS)
            self.assertIn(link['to'], config.DISPLAY_SYSTEMS)
            self.assertLess(order.index(link['from']), order.index(link['to']))

    def test_links_that_loop_are_refused(self):
        loop = ({'from': 'murray', 'basin': 'B1', 'to': 'lachlan', 'into': 'B2'}, {'from': 'lachlan', 'basin': 'B2', 'to': 'murray', 'into': 'B1'})
        with mock.patch.object(config, 'LINKS', loop), self.assertRaises(ValueError):
            config.run_order()

    def test_a_return_takes_a_lagged_share_and_no_more_than_its_split(self):
        flow = np.array([100.0, 200.0, 300.0, 400.0, 0.0])
        np.testing.assert_allclose(muskingum.link_inflow({'fraction': 0.25, 'lag_days': 2}, flow), [25.0, 25.0, 25.0, 50.0, 75.0])
        np.testing.assert_allclose(muskingum.link_inflow({}, flow), flow)
        np.testing.assert_allclose(muskingum.link_inflow({'spill_above_ML_d': 150.0, 'lag_days': 9}, flow), np.full(5, 0.0))
        # volume: what arrives is the share of what left, less the days still on the way at the end
        long = np.random.default_rng(1).gamma(2.0, 50.0, 400)
        self.assertAlmostEqual(muskingum.link_inflow({'fraction': 0.1, 'lag_days': 30}, long).sum(),
                               0.1 * (long[0] * 30 + long[:-30].sum()), places=6)
        for fraction in (0.5, 0.0):
            loop = ({'from': 'murray', 'basin': 'B1', 'to': 'lachlan', 'into': 'B2', 'fraction': fraction},)
            with mock.patch.object(config, 'LINKS', loop), mock.patch.dict(config.SYSTEMS['murray'], {'splits': {'B1': {'': 0.2}}}), self.assertRaises(ValueError):
                config.run_order()

    def test_zones_follow_observed_aridity_and_fall_back_downstream(self):
        import aridity
        basins = pd.DataFrame({'subcatchment': ['wet', 'dry', 'blank', 'lost'], 'next_id': ['dry', '', 'wet', '']})
        climate = pd.DataFrame({'date': ['2020-01-01', '2020-01-02'], 'wet_P': [3.0, 1.0], 'wet_PET': [2.0, 2.0], 'dry_P': [1.0, 0.0],
                                'dry_PET': [4.0, 4.0], 'blank_P': [np.nan, np.nan], 'blank_PET': [np.nan, np.nan]})
        with mock.patch.object(aridity.pd, 'read_csv', return_value=climate.set_index('date')):
            zones = aridity.basin_zones('x', basins)
        self.assertEqual(zones, {'wet': 'highland', 'dry': 'plains', 'blank': 'highland', 'lost': 'plains'})

    def test_inflow_adds_links_into_one_node_and_spills_only_above_threshold(self):
        index = pd.date_range('2000-01-01', periods=2)
        nodes = pd.DataFrame([dict(id='N1', basin='B1', outlet=True), dict(id='N2', basin='B2', outlet=True)])
        links = ({'from': 'a', 'basin': 'X', 'to': 'sys', 'into': 'B1'},
                 {'from': 'b', 'basin': 'Y', 'to': 'sys', 'into': 'B1', 'spill_above_ML_d': 1000.0},
                 {'from': 'c', 'basin': 'Z', 'to': 'other', 'into': 'B2'})
        flows = {'X': [86.4, 172.8], 'Y': [500.0, 1864.0]}
        with mock.patch.object(muskingum, 'LINKS', links), mock.patch.object(muskingum, 'SYSTEM_ID', 'sys'), \
                mock.patch.object(muskingum, 'link_flow', lambda link, idx: pd.Series(flows[link['basin']], index=idx)):
            inflow = muskingum._inflows(nodes, index)
        self.assertEqual(list(inflow), ['N1'])
        np.testing.assert_allclose(inflow['N1'], [1.0, 2.0 + 10.0])


if __name__ == '__main__':
    unittest.main()
