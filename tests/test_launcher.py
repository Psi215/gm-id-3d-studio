# -*- coding: utf-8 -*-
"""启动脚本检查: run.bat 应优先使用仓库内的 .venv(并保留回退)。"""
from __future__ import annotations

import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RUN_BAT = os.path.join(ROOT, "run.bat")
REQUIREMENTS = os.path.join(ROOT, "requirements.txt")
README = os.path.join(ROOT, "README.md")


class TestLauncher(unittest.TestCase):
    def test_run_bat_uses_repo_venv(self):
        with open(RUN_BAT, encoding="utf-8") as fh:
            txt = fh.read()
        self.assertIn("%~dp0.venv", txt,
                      "run.bat 应先查找仓库内的 .venv")
        self.assertIn("main.py", txt)
        # 必须保留回退路径, 否则没建 .venv 的机器直接失效
        self.assertTrue("..\\.venv" in txt or "pythonw" in txt)

    def test_readme_matches_launcher(self):
        with open(README, encoding="utf-8") as fh:
            txt = fh.read()
        self.assertIn("python -m venv .venv", txt)
        with open(REQUIREMENTS, encoding="utf-8") as fh:
            req = fh.read()
        for pkg in ("PySide6", "matplotlib", "numpy", "scipy"):
            self.assertIn(pkg, req)


if __name__ == "__main__":
    unittest.main(verbosity=2)
