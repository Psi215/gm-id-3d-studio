from __future__ import annotations

import os
import unittest

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gmidlib.metrics import detect_metric
from gmstudio.core.model import Curve, Metric, Source
from gmstudio.ui.viewer import MainWindow


def source_with_metric(path: str, name: str) -> tuple[Source, Metric]:
    source = Source(path=path, label="total")
    metric = Metric(
        base=name,
        display=name,
        source_label=source.label,
        source_path=path,
        profile=detect_metric(name),
        curves=[
            Curve(
                L_um=1.0,
                x=np.array([1.0, 2.0, 3.0]),
                y=np.array([1.0, 2.0, 3.0]),
            )
        ],
    )
    source.metrics[name] = metric
    return source, metric


class ViewerStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()

    def tearDown(self):
        self.window.close()

    def test_direction_control_tracks_session_value(self):
        source, _ = source_with_metric("nmos/total.csv", "vdsat")
        self.window.sess.add_source(source)
        self.window._sync_from_session()

        self.assertEqual(self.window.sess.direction, "min")
        self.assertEqual(self.window.cmb_dir.currentData(), "min")

        self.window.cmb_dir.setCurrentIndex(self.window.cmb_dir.findData("max"))
        self.assertEqual(self.window.sess.direction, "max")
        self.assertEqual(self.window.cmb_dir.currentData(), "max")

    def test_active_control_distinguishes_same_named_sources(self):
        first, first_metric = source_with_metric("nmos/total.csv", "ft")
        second, second_metric = source_with_metric("pmos/total.csv", "ft")
        self.window.sess.add_source(first)
        self.window.sess.add_source(second)
        self.window._sync_from_session()

        index = self.window.cmb_active.findData(second.path + "\u0001ft")
        self.assertGreaterEqual(index, 0)
        self.window.cmb_active.blockSignals(True)
        self.window.cmb_active.setCurrentIndex(index)
        self.window.cmb_active.blockSignals(False)
        self.window._on_active()

        self.assertIsNot(self.window.sess.active_metric(), first_metric)
        self.assertIs(self.window.sess.active_metric(), second_metric)


if __name__ == "__main__":
    unittest.main()
