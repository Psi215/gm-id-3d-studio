from __future__ import annotations

import unittest

import numpy as np

from gmidlib.metrics import detect_metric
from gmstudio.core.model import Curve, Metric, Source
from gmstudio.core.session import PREFIX_DEFAULT, Session


def make_metric(path: str, name: str, ys) -> Metric:
    metric = Metric(
        base=name,
        display=name,
        source_label="total",
        source_path=path,
        profile=detect_metric(name),
    )
    for index, y in enumerate(ys, start=1):
        values = np.asarray(y, dtype=float)
        metric.curves.append(
            Curve(
                L_um=float(index),
                x=np.arange(1, values.size + 1, dtype=float),
                y=values,
            )
        )
    return metric


class SessionRegressionTests(unittest.TestCase):
    def test_prefix_scale_is_shared_by_every_curve_of_a_metric(self):
        metric = make_metric(
            "nmos/total.csv",
            "ft",
            ([1.0e9, 1.1e9, 1.2e9], [1.0e6, 1.1e6, 1.2e6]),
        )
        session = Session()
        session.display_mode = PREFIX_DEFAULT

        high = session.disp(metric, metric.curves[0].y)
        low = session.disp(metric, metric.curves[1].y)

        self.assertEqual(session.unit_str(metric), "MHz")
        self.assertAlmostEqual(high[0] / low[0], 1000.0)

    def test_selecting_metric_updates_direction_and_exact_source(self):
        first = Source(path="nmos/total.csv", label="total")
        first.metrics["vdsat"] = make_metric(first.path, "vdsat", ([0.1, 0.2],))
        second = Source(path="pmos/total.csv", label="total")
        second.metrics["ft"] = make_metric(second.path, "ft", ([1.0e9, 2.0e9],))
        session = Session()
        session.add_source(first)
        session.add_source(second)

        session.set_active(second.path, "ft")

        self.assertIs(session.active_metric(), second.metrics["ft"])
        self.assertEqual(session.direction, "max")
        session.set_active(first.path, "vdsat")
        self.assertIs(session.active_metric(), first.metrics["vdsat"])
        self.assertEqual(session.direction, "min")

    def test_same_named_sources_do_not_share_effective_series_cache(self):
        first = make_metric("nmos/total.csv", "ft", ([10.0, 20.0],))
        second = make_metric("pmos/total.csv", "ft", ([100.0, 200.0],))
        session = Session()

        first_result = session.effective_series(first)
        second_result = session.effective_series(second)

        np.testing.assert_array_equal(first_result[0][2], [10.0, 20.0])
        np.testing.assert_array_equal(second_result[0][2], [100.0, 200.0])
        self.assertEqual(len(session._eff_cache), 2)


if __name__ == "__main__":
    unittest.main()
