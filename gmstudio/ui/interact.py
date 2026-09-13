# -*- coding: utf-8 -*-
"""
图上交互:可拖动竖线/横线(交点读数) · 两点取点算斜率 · 可拖阈值线
================================================================
* 竖线游标: 拖动竖直虚线, 实时给出它与**每条曲线的交点值**(带曲线标签),
  图上用小圆圈标出交点并标注数值;
* 横线游标: 拖动水平虚线, 给出它与每条曲线的交点 x 值(可多个交点);
* 取点算斜率: 进入测量模式后点两下(自动吸附到最近数据点), 给出 Δx、Δy、
  斜率 dy/dx, 标记可继续拖动微调;
* 阈值线拖动: 拖动 2D 里的红色阈值虚线即可改查表阈值;
* 与 matplotlib 工具栏兼容: 缩放/平移模式下自动让位。
"""
from __future__ import annotations

import numpy as np

from PySide6.QtCore import QObject, Signal

MAX_LABELS = 8          # 图上最多标注的交点个数(读数面板里给全)


def _fmt(v, sig=5):
    try:
        if not np.isfinite(v):
            return "-"
        return f"{v:.{sig}g}"
    except Exception:
        return "-"


class PlotInteractor(QObject):
    """2D 画布交互管理器。

    data_provider(ax_index) -> list[(x_array, y_array, label)]:
        该子图上已绘制的曲线(用于吸附、游标交点与读数);
    on_threshold(value): 拖动阈值线时回调;
    changed: 任何游标/测量变化后发出(刷新读数面板)。
    """

    changed = Signal()

    def __init__(self, canvas, data_provider, on_threshold=None, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        self.provider = data_provider
        self.on_threshold = on_threshold
        self.snap = True            # 取点时吸附数据点
        self.snap_cursors = False   # 游标是否吸附数据点
        self.label_on_plot = True   # 是否在图上标注交点值
        self.vcursors: list[list] = []      # [ax_index, x]
        self.hcursors: list[list] = []      # [ax_index, y]
        self.measure: list = []             # [[ax, x, y], [ax, x, y]]
        self.measuring = False
        self._drag = None
        self._thr_y = None
        self._artists = []
        self._cid = [
            canvas.mpl_connect("button_press_event", self._on_press),
            canvas.mpl_connect("motion_notify_event", self._on_motion),
            canvas.mpl_connect("button_release_event", self._on_release),
        ]

    # ---------------- 基础 ----------------
    def _busy_toolbar(self):
        try:
            mode = self.canvas.parent()._toolbar.mode
            return mode not in ("", None)
        except Exception:
            return False

    def _axes_list(self):
        fig = self.canvas.figure
        return [a for a in fig.axes
                if not str(getattr(a, "name", "")).startswith("3d")]

    def _ax_index(self, ax):
        try:
            return self._axes_list().index(ax)
        except ValueError:
            return None

    def _series(self, idx):
        try:
            return self.provider(idx) or []
        except Exception:
            return []

    def _snap_xy(self, idx, x, y):
        if not self.snap:
            return x, y
        ax = self._axes_list()[idx]
        try:
            px, py = ax.transData.transform((x, y))
        except Exception:
            return x, y
        best, bd = None, np.inf
        for s in self._series(idx):
            xa, ya = s[0], s[1]
            if xa is None or xa.size == 0:
                continue
            pts = ax.transData.transform(np.column_stack([xa, ya]))
            d = np.hypot(pts[:, 0] - px, pts[:, 1] - py)
            i = int(np.argmin(d))
            if d[i] < bd:
                bd = float(d[i])
                best = (float(xa[i]), float(ya[i]))
        if best is not None and bd <= 25:
            return best
        return x, y

    # ---------------- 交点计算 ----------------
    def _crossings_v(self, idx, x):
        """竖线 x 与各曲线的交点: [(label, y)]。"""
        out = []
        for s in self._series(idx):
            xa, ya = s[0], s[1]
            label = s[2] if len(s) > 2 else ""
            if xa is None or xa.size < 2:
                continue
            if x < float(xa[0]) or x > float(xa[-1]):
                continue
            out.append((label, float(np.interp(x, xa, ya))))
        return out

    def _crossings_h(self, idx, y):
        """横线 y 与各曲线的交点: [(label, x)] (可能多个)。"""
        out = []
        for s in self._series(idx):
            xa, ya = s[0], s[1]
            label = s[2] if len(s) > 2 else ""
            if xa is None or xa.size < 2:
                continue
            d = ya - y
            sign = np.sign(d)
            for i in range(len(d) - 1):
                if sign[i] == 0:
                    out.append((label, float(xa[i])))
                elif sign[i] != sign[i + 1] and sign[i] != 0 and sign[i + 1] != 0:
                    # 线性插值求交点
                    y1, y2 = ya[i], ya[i + 1]
                    if y2 == y1:
                        continue
                    t = (y - y1) / (y2 - y1)
                    out.append((label, float(xa[i] + t * (xa[i + 1] - xa[i]))))
            if sign[-1] == 0:
                out.append((label, float(xa[-1])))
        return out

    # ---------------- 事件 ----------------
    def _on_press(self, ev):
        if ev.inaxes is None or self._busy_toolbar() or ev.button != 1:
            return
        idx = self._ax_index(ev.inaxes)
        if idx is None:
            return
        ax = ev.inaxes
        # 命中竖线?
        for i, (ci, cx) in enumerate(self.vcursors):
            if ci != idx:
                continue
            try:
                px = ax.transData.transform((cx, 0))[0]
            except Exception:
                continue
            if abs(px - ev.x) <= 6:
                self._drag = ("v", i)
                return
        # 命中横线?
        for i, (ci, cy) in enumerate(self.hcursors):
            if ci != idx:
                continue
            try:
                py = ax.transData.transform((0, cy))[1]
            except Exception:
                continue
            if abs(py - ev.y) <= 6:
                self._drag = ("h", i)
                return
        # 命中 A/B 标记?
        for i, (mi, mx, my) in enumerate(self.measure):
            if mi != idx:
                continue
            try:
                px, py = ax.transData.transform((mx, my))
            except Exception:
                continue
            if np.hypot(px - ev.x, py - ev.y) <= 10:
                self._drag = ("m", i)
                return
        # 测量模式取点
        if self.measuring:
            x, y = self._snap_xy(idx, ev.xdata, ev.ydata)
            self.measure.append([idx, x, y])
            if len(self.measure) >= 2:
                self.measuring = False
            self.redraw()
            self.changed.emit()
            return
        # 阈值线拖动
        if (self.on_threshold is not None and ev.ydata is not None
                and self._thr_y is not None):
            try:
                py = ax.transData.transform((0, self._thr_y))[1]
            except Exception:
                py = None
            if py is not None and abs(py - ev.y) <= 6:
                self._drag = ("thr",)
                return

    def _on_motion(self, ev):
        if self._drag is None or ev.inaxes is None:
            return
        idx = self._ax_index(ev.inaxes)
        kind = self._drag[0]
        if kind == "v":
            i = self._drag[1]
            if idx != self.vcursors[i][0]:
                return
            x = float(ev.xdata)
            if self.snap_cursors:
                x, _ = self._snap_xy(idx, x, ev.ydata)
            self.vcursors[i][1] = x
        elif kind == "h":
            i = self._drag[1]
            if idx != self.hcursors[i][0]:
                return
            self.hcursors[i][1] = float(ev.ydata)
        elif kind == "m":
            i = self._drag[1]
            if idx != self.measure[i][0]:
                return
            x, y = self._snap_xy(idx, ev.xdata, ev.ydata)
            self.measure[i][1] = x
            self.measure[i][2] = y
        elif kind == "thr":
            if self.on_threshold is not None and ev.ydata is not None:
                self.on_threshold(float(ev.ydata))
            return
        self.redraw()
        self.changed.emit()

    def _on_release(self, ev):
        self._drag = None

    # ---------------- 对外操作 ----------------
    def set_threshold(self, y):
        self._thr_y = float(y)

    def add_cursor(self, ax_index=0, x=None):
        axes = self._axes_list()
        if not axes:
            return
        idx = min(ax_index, len(axes) - 1)
        if x is None:
            try:
                lo, hi = axes[idx].get_xlim()
                x = 0.5 * (lo + hi)
            except Exception:
                x = 0.0
        self.vcursors.append([idx, float(x)])
        self.redraw()
        self.changed.emit()

    def add_hcursor(self, ax_index=0, y=None):
        axes = self._axes_list()
        if not axes:
            return
        idx = min(ax_index, len(axes) - 1)
        if y is None:
            try:
                lo, hi = axes[idx].get_ylim()
                y = 0.5 * (lo + hi)
            except Exception:
                y = 0.0
        self.hcursors.append([idx, float(y)])
        self.redraw()
        self.changed.emit()

    def clear_cursors(self, which="both"):
        if which in ("v", "both"):
            self.vcursors.clear()
        if which in ("h", "both"):
            self.hcursors.clear()
        self.redraw()
        self.changed.emit()

    def start_measure(self):
        self.measure = []
        self.measuring = True
        self.redraw()
        self.changed.emit()

    def clear_measure(self):
        self.measure = []
        self.measuring = False
        self.redraw()
        self.changed.emit()

    def clear_all(self):
        self.vcursors.clear()
        self.hcursors.clear()
        self.measure = []
        self.measuring = False
        self.redraw()
        self.changed.emit()

    # ---------------- 绘制 ----------------
    def on_replot(self):
        axes = self._axes_list()
        self.vcursors = [c for c in self.vcursors if c[0] < len(axes)]
        self.hcursors = [c for c in self.hcursors if c[0] < len(axes)]
        self.measure = [m for m in self.measure if m[0] < len(axes)]
        self.redraw()

    def redraw(self):
        for a in self._artists:
            try:
                a.remove()
            except Exception:
                pass
        self._artists = []
        axes = self._axes_list()
        if not axes:
            return
        for i, (idx, x) in enumerate(self.vcursors):
            if idx >= len(axes):
                continue
            ax = axes[idx]
            ln = ax.axvline(x, color="#e0443b", ls="--", lw=1.0, alpha=0.85,
                            zorder=6)
            tag = ax.text(x, 0.985, f" C{i + 1} x={_fmt(x)}",
                          transform=ax.get_xaxis_transform(), ha="left",
                          va="top", fontsize=8, color="#b3261e", zorder=7)
            self._artists += [ln, tag]
            self._mark(ax, self._crossings_v(idx, x), "v", x, "#b3261e")
        for i, (idx, y) in enumerate(self.hcursors):
            if idx >= len(axes):
                continue
            ax = axes[idx]
            ln = ax.axhline(y, color="#0f9d58", ls="--", lw=1.0, alpha=0.85,
                            zorder=6)
            tag = ax.text(0.995, y, f"H{i + 1} y={_fmt(y)} ",
                          transform=ax.get_yaxis_transform(), ha="right",
                          va="bottom", fontsize=8, color="#0b7a44", zorder=7)
            self._artists += [ln, tag]
            self._mark(ax, self._crossings_h(idx, y), "h", y, "#0b7a44")
        # A/B 与连线
        for i, (idx, x, y) in enumerate(self.measure[:2]):
            if idx >= len(axes):
                continue
            ax = axes[idx]
            mk, = ax.plot([x], [y], marker="o", ms=7, mfc="#ffffff",
                          mec="#1e6fd9", mew=1.6, ls="none", zorder=8)
            tx = ax.text(x, y, f"  {'AB'[i]}({_fmt(x)}, {_fmt(y)})",
                         fontsize=8, color="#1e6fd9", zorder=8, ha="left",
                         va="bottom")
            self._artists += [mk, tx]
        if len(self.measure) == 2:
            (i1, x1, y1), (i2, x2, y2) = self.measure
            if i1 == i2 and i1 < len(axes):
                ax = axes[i1]
                ln, = ax.plot([x1, x2], [y1, y2], color="#1e6fd9", lw=1.0,
                              alpha=0.9, zorder=7)
                self._artists.append(ln)
        self.canvas.draw_idle()

    def _mark(self, ax, crossings, at, coord, color):
        """在交点处画空心圆圈, 并按需标注数值(限制条数防遮挡)。"""
        if not crossings:
            return
        vals = [c[1] for c in crossings]
        if at == "v":
            xs, ys = [coord] * len(vals), vals
        else:
            xs, ys = vals, [coord] * len(vals)
        try:
            sc = ax.scatter(xs, ys, s=26, facecolors="none",
                            edgecolors=color, linewidths=1.2, zorder=9)
            self._artists.append(sc)
        except Exception:
            return
        if not self.label_on_plot:
            return
        for label, val in crossings[:MAX_LABELS]:
            if at == "v":
                tx, ty, txt = coord, val, _fmt(val)
            else:
                tx, ty, txt = val, coord, f"x={_fmt(val)}"
            t = ax.text(tx, ty, " " + txt, fontsize=7, color=color,
                        zorder=10, ha="left", va="bottom")
            self._artists.append(t)

    # ---------------- 读数 ----------------
    def summary(self) -> str:
        lines = []
        for i, (idx, x) in enumerate(self.vcursors):
            cr = self._crossings_v(idx, x)
            if not cr:
                lines.append(f"C{i + 1}  x={_fmt(x)}: (该 x 处无曲线)")
                continue
            items = [f"{lbl or '曲线'}: {_fmt(v)}" for lbl, v in cr[:6]]
            more = f" …(共 {len(cr)} 条)" if len(cr) > 6 else ""
            lines.append(f"C{i + 1}  x={_fmt(x)} → " + " | ".join(items) + more)
        if len(self.vcursors) >= 2:
            lines.append(f"Δx(C2-C1) = "
                         f"{_fmt(self.vcursors[1][1] - self.vcursors[0][1])}")
        for i, (idx, y) in enumerate(self.hcursors):
            cr = self._crossings_h(idx, y)
            if not cr:
                lines.append(f"H{i + 1}  y={_fmt(y)}: (无交点)")
                continue
            groups: dict[str, list] = {}
            for lbl, v in cr:
                groups.setdefault(lbl or "曲线", []).append(v)
            items = []
            for k, vals in list(groups.items())[:6]:
                shown = "/".join(_fmt(v) for v in vals[:3])
                items.append(f"{k}: x={shown}" + ("…" if len(vals) > 3 else ""))
            more = (f" …(共 {len(cr)} 个交点)"
                    if len(cr) > sum(len(v[:3]) for v in
                                     list(groups.values())[:6]) else "")
            lines.append(f"H{i + 1}  y={_fmt(y)} → " + " | ".join(items) + more)
        if len(self.measure) == 2:
            (_, x1, y1), (_, x2, y2) = self.measure
            dx, dy = x2 - x1, y2 - y1
            slope = dy / dx if dx != 0 else float("inf")
            txt = f"A→B: Δx={_fmt(dx)}  Δy={_fmt(dy)}  斜率={_fmt(slope)}"
            if slope not in (0, float("inf")):
                txt += f"  (1/斜率={_fmt(1 / slope)})"
            lines.append(txt)
        elif self.measuring:
            lines.append("测量中: 在曲线上点两下(A、B)…")
        return "\n".join(lines)
