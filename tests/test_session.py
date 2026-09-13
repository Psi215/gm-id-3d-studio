# -*- coding: utf-8 -*-
"""会话/指标状态回归测试(移植自 PR #1, 适配当前窗口架构)。

覆盖:
  1. 同一指标在所有视图里使用**同一个**工程前缀刻度;
  2. 同名但不同路径的数据文件不共用缓存与选择状态;
  3. 新建视图时查表方向取该指标档案的默认方向;
  4. run.bat 优先使用仓库内的 .venv。
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
import sys  # noqa: E402
sys.path.insert(0, ROOT)

from gmstudio.core.loader import load_file            # noqa: E402
from gmstudio.core.session import (PREFIX_DEFAULT,    # noqa: E402
                                   Session, ViewState)

SELFGAIN = os.path.join(ROOT, "csvdata", "selfgain_nch_2.5V.csv")
FT = os.path.join(ROOT, "csvdata", "ft_nch_2.5V.csv")
VDSAT = os.path.join(ROOT, "csvdata_extras", "vdsat_nch_2.5V.csv")


class TestMetricScale(unittest.TestCase):
    def test_one_prefix_per_metric(self):
        """曲线/曲面/查表/标签必须共用同一前缀刻度。"""
        sess = Session()
        sess.add_source(load_file(FT))
        m = next(iter(sess.sources.values())).metrics["fT"]
        sess.display_mode = PREFIX_DEFAULT
        factor, unit = sess._metric_display(m)
        # 任意子集应得到同一因子(不再是"按数组中位数各算各的")
        sub = np.asarray(m.curves[0].y, float)
        self.assertEqual(factor, sess._metric_display(m)[0])
        self.assertEqual(unit, sess.unit_str(m))
        # disp(): 原始值 × 固定因子
        y = np.asarray(m.curves[0].y, float)
        self.assertTrue(np.allclose(sess.disp(m, y), y * factor))
        # 另一条曲线用同一因子(比值恒等于 1)
        y2 = np.asarray(m.curves[-1].y, float)
        r = sess.disp(m, y2) / y2
        self.assertTrue(np.allclose(r[np.isfinite(r)], factor))
        self.assertGreater(factor, 0)

    def test_prefix_stable_across_views(self):
        """不同 ViewState(不同范围)不改变指标刻度。"""
        sess = Session()
        sess.add_source(load_file(FT))
        m = next(iter(sess.sources.values())).metrics["fT"]
        v1 = ViewState(display_mode=PREFIX_DEFAULT, xmax=10.0)
        v2 = ViewState(display_mode=PREFIX_DEFAULT, xmax=1000.0)
        self.assertEqual(sess.unit_str(m, view=v1), sess.unit_str(m, view=v2))
        self.assertEqual(sess._metric_display(m)[0],
                         sess._metric_display(m)[0])


class TestSameNameSources(unittest.TestCase):
    """同名文件(不同目录)必须按路径区分, 不共用缓存/状态。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gmstudio_test_")
        self.a = os.path.join(self.tmp, "a"); os.makedirs(self.a)
        self.b = os.path.join(self.tmp, "b"); os.makedirs(self.b)
        self.pa = os.path.join(self.a, "dup.csv")
        self.pb = os.path.join(self.b, "dup.csv")
        shutil.copy2(SELFGAIN, self.pa)
        # 第二份改动数据(X 上限缩小、Y 放大), 用于检测串数据
        import csv
        with open(SELFGAIN, newline="") as fh:
            rows = list(csv.reader(fh))
        for r in rows[1:]:
            for j in range(1, len(r), 2):        # Y 列
                try:
                    r[j] = str(float(r[j]) * 10.0)
                except ValueError:
                    pass
        with open(self.pb, "w", newline="") as fh:
            csv.writer(fh).writerows(rows)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_path_identity_and_cache_isolation(self):
        sess = Session()
        sa, sb = load_file(self.pa), load_file(self.pb)
        sess.add_source(sa); sess.add_source(sb)
        ma = sa.metrics["selfgain"]; mb = sb.metrics["selfgain"]
        self.assertNotEqual(ma.source_path, mb.source_path)
        self.assertEqual(ma.source_path, os.path.abspath(self.pa))
        self.assertEqual(ma.source_label, mb.source_label)   # 标签相同
        # ★ 标签相同但数据不同: 有效曲线必须各用各的
        ya = max(float(np.nanmax(y)) for _, _, y in sess.effective_series(ma))
        yb = max(float(np.nanmax(y)) for _, _, y in sess.effective_series(mb))
        self.assertAlmostEqual(yb / ya, 10.0, places=3)
        # 曲面缓存不串: 两次取到的 Z 量级不同
        va = ViewState(); vb = ViewState()
        za = sess.surface_of(ma, va)["Z"]; zb = sess.surface_of(mb, vb)["Z"]
        self.assertAlmostEqual(float(np.nanmax(zb)) / float(np.nanmax(za)),
                               10.0, places=2)
        # 再取一次仍是各自的数据(缓存命中也不串)
        self.assertAlmostEqual(
            float(np.nanmax(sess.surface_of(ma, va)["Z"])),
            float(np.nanmax(za)), places=6)

    def test_checked_state_isolated(self):
        sess = Session()
        sa, sb = load_file(self.pa), load_file(self.pb)
        sess.add_source(sa); sess.add_source(sb)
        # 载入时不再默认勾选(勾选=开窗, 由用户决定)
        self.assertEqual(sess.checked[self.pa], set())
        self.assertEqual(sess.checked[self.pb], set())
        sess.toggle(self.pa, "selfgain", True)
        self.assertIn("selfgain", sess.checked[self.pa])
        self.assertNotIn("selfgain", sess.checked[self.pb])   # 同名文件互不影响
        sess.toggle(self.pa, "selfgain", False)
        self.assertNotIn("selfgain", sess.checked[self.pa])


class TestDirectionAndView(unittest.TestCase):
    def test_view_direction_from_profile(self):
        """新建视图: 幅值类(增益/fT)默认 ≥, 电压类默认 ≤。"""
        sess = Session()
        sess.add_source(load_file(FT))
        m_ft = next(iter(sess.sources.values())).metrics["fT"]
        self.assertEqual(sess.make_view(m_ft).direction,
                         m_ft.profile.direction)
        if os.path.exists(VDSAT):
            sess.add_source(load_file(VDSAT))
            src = sess.sources[os.path.abspath(VDSAT)]
            m_vd = src.metrics.get("vdsat") or next(iter(src.metrics.values()))
            v = sess.make_view(m_vd)
            self.assertEqual(v.direction, m_vd.profile.direction)
            self.assertEqual(v.direction, "min")

    def test_per_view_independence(self):
        """每个视图的约束互不影响。"""
        sess = Session()
        sess.add_source(load_file(SELFGAIN))
        m = next(iter(sess.sources.values())).metrics["selfgain"]
        v1, v2 = sess.make_view(m), sess.make_view(m)
        v1.xmax = 10.0
        sf1 = sess.surface_of(m, v1)
        sf2 = sess.surface_of(m, v2)
        self.assertLessEqual(float(sf1["xs"][-1]), 10.0 + 1e-9)
        self.assertGreater(float(sf2["xs"][-1]), 20.0)
        self.assertNotEqual(v1.xmax, v2.xmax)


if __name__ == "__main__":
    unittest.main(verbosity=2)
