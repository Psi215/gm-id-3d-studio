from __future__ import annotations

import pathlib
import unittest


class WindowsLauncherTests(unittest.TestCase):
    def test_launcher_uses_repository_local_virtual_environment(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        launcher = (root / "run.bat").read_text(encoding="utf-8")

        self.assertIn(r'"%~dp0.venv\Scripts\pythonw.exe"', launcher)
        self.assertNotIn(r'"..\.venv\Scripts\pythonw.exe"', launcher)


if __name__ == "__main__":
    unittest.main()
