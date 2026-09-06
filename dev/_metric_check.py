# -*- coding: utf-8 -*-
"""指标适配自检: fT / Vdsat / Inor 长表档案与 GUI 单位联动。"""
from __future__ import annotations

import os
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, n=15, dt=0.03):
    for _ in range(n):
        app.processEvents()
        time.sleep(dt)


def main() -> int:
    tmp = os.path.join(HERE, "_tmp_long.csv")
    with open(tmp, "w", newline="") as fh:
        fh.write("L, gm_id, ft, vdsat, inor\n")
        for L in (0.5, 1.0, 2.0):
            for gm in (2.0, 5.0, 10.0, 20.0):
                ft = 3e9 / gm + 5e8 * (2.0 - L)
                vdsat = 0.4 * (gm / 25.0) ** 0.8 + 0.02 * L
                inor = 1e4 * (1.5 - gm / 40.0) + 2e3 * L
                fh.write(f"{L}, {gm}, {ft:.4e}, {vdsat:.4f}, {inor:.4f}\n")

    from gmstudio.core.loader import load_file
    src = load_file(tmp)
    profs = {m.base: m.profile.key for m in src.metrics.values()}
    print("profiles:", profs)
    assert profs.get("ft") == "ft"
    assert profs.get("vdsat") == "vdsat"
    assert profs.get("inor") == "idnor"

    app = QApplication([])
    from gmstudio.ui.viewer import MainWindow
    w = MainWindow()
    w.open_paths([tmp])
    pump(app, 30)
    print("  loaded; 2D 子图:", len(w.stacked.axes),
          "| 3D 集合:", len(w.p3d.axes.collections))
    os.remove(tmp)
    print("METRIC CHECK PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
