# -*- coding: utf-8 -*-
"""旧版单窗口 GUI(gui.py, v1)回归压测(离屏)。"""
from __future__ import annotations

import os
import sys
import time
import traceback

os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

CSV = os.path.join(ROOT, "csvdata", "selfgain_nch_2.5V.csv")
FAILS = []

_orig = sys.excepthook


def _hook(t, v, tb):
    FAILS.append("".join(traceback.format_exception(t, v, tb)))
    _orig(t, v, tb)


sys.excepthook = _hook


def pump(app, n=25, dt=0.03):
    for _ in range(n):
        app.processEvents()
        time.sleep(dt)


def step(app, w, name, action):
    try:
        action()
        pump(app)
        for p in (w.p_curves, w.p_surf, w.p_prof):
            p.canvas.draw()
        pump(app, 5)
        print(f"  [OK ] {name:<40} 2D线={len(w.p_curves.axes.lines):>3} "
              f"3D集合={len(w.p_surf.axes.collections):>3}")
    except Exception as e:  # noqa: BLE001
        FAILS.append(name)
        print(f"  [ERR] {name}: {type(e).__name__}: {e}")


def main() -> int:
    app = QApplication([])
    from gui import MainWindow          # v1 旧窗口(兼容回归)
    w = MainWindow()
    w.resize(1460, 900)
    w.show()

    step(app, w, "打开样例 selfgain CSV", lambda: w.open_paths([CSV]))
    assert len(w._surf) == 1 and w._lookup and len(w._lookup.rows) > 0

    step(app, w, "关闭回折剔除", lambda: w.cb_fold.setChecked(False))
    step(app, w, "开启 Savgol 平滑(窗15阶3)",
         lambda: (w.sp_swin.setValue(15), w.sp_sord.setValue(3),
                  w.cb_smooth.setChecked(True)))
    step(app, w, "开启 MAD 剔除(k=3)",
         lambda: (w.sp_madk.setValue(3.0), w.cb_outlier.setChecked(True)))
    step(app, w, "恢复默认清洗",
         lambda: (w.cb_outlier.setChecked(False),
                  w.cb_smooth.setChecked(False),
                  w.cb_fold.setChecked(True)))
    step(app, w, "gm/ID 上限收到 10", lambda: w.sp_xmax.setValue(10.0))
    step(app, w, "指标范围 40..53 dB",
         lambda: (w.sp_gmin.setValue(40.0), w.sp_gmax.setValue(53.0)))
    step(app, w, "自动范围", lambda: w._auto_range_full())
    step(app, w, "X 对数轴", lambda: w.cb_xlog.setChecked(True))
    step(app, w, "X 线性轴", lambda: w.cb_xlog.setChecked(False))
    step(app, w, "L 对数轴", lambda: w.cb_Llog.setChecked(True))
    step(app, w, "L 线性轴", lambda: w.cb_Llog.setChecked(False))
    step(app, w, "显示切到线性 V/V", lambda: w.cb_db.setChecked(False))
    step(app, w, "显示切回 dB", lambda: w.cb_db.setChecked(True))
    step(app, w, "关闭查表", lambda: w.cb_lk.setChecked(False))
    step(app, w, "开启查表且阈值 45 dB",
         lambda: (w.cb_lk.setChecked(True), w.sp_thr.setValue(45.0)))
    step(app, w, "旧 bug 回归: 手工放大视图后调过滤",
         lambda: (w.p_curves.axes.set_xlim(0, 1e6),
                  w.p_curves.axes.set_ylim(-1e6, 1e6),
                  w.sp_xmax.setValue(15.0)))
    x0, x1 = w.p_curves.axes.get_xlim()
    assert 5 < x1 < 30, f"自动定标未恢复 xlim={x0:.2f},{x1:.2f}"
    step(app, w, "阈值 90 dB(应无可行区)", lambda: w.sp_thr.setValue(90.0))
    step(app, w, "阈值回 50 dB", lambda: w.sp_thr.setValue(50.0))

    # 导出(桩掉文件对话框)
    import gui as guimod
    _orig_save = guimod.QFileDialog.getSaveFileName
    guimod.QFileDialog.getSaveFileName = \
        lambda *a, **k: (os.path.join(ROOT, "_exp_out.csv"), "CSV (*.csv)")
    try:
        w._export_data()
        w._export_grid()
        w._export_lookup()
    finally:
        guimod.QFileDialog.getSaveFileName = _orig_save
    assert os.path.getsize(os.path.join(ROOT, "_exp_out.csv")) > 100
    os.remove(os.path.join(ROOT, "_exp_out.csv"))
    print("  [OK ] 导出 清洗长表/公共栅格/查表结果 CSV")

    # 长表第二数据集
    tmp2 = os.path.join(HERE, "_tmp_long2.csv")
    with open(tmp2, "w", newline="") as fh:
        fh.write("L, gm_id, selfgain, ft\n")
        for L in (0.8, 1.6):
            for gm in (3.0, 8.0, 15.0, 25.0):
                fh.write(f"{L}, {gm}, {600*(1-1/(gm+1)):.4f}, "
                         f"{2e9/gm:.3e}\n")
    step(app, w, "载入长表第二数据集", lambda: w.open_paths([tmp2]))
    os.remove(tmp2)
    step(app, w, "清空全部数据", lambda: w._clear_all_data())
    step(app, w, "重载样例 CSV", lambda: w.open_paths([CSV]))

    if FAILS:
        print("FAILED:", FAILS)
        return 1
    print("LEGACY GUI REGRESSION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
