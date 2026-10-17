"""scripts/eval_sim.py (D83) runs end to end: fallback extractor, real planner and simulator, three samples."""
import subprocess
import sys

from residents.config import PKG_ROOT


def test_eval_sim_runs_on_three_samples():
    out = subprocess.run([sys.executable, "scripts/eval_sim.py", "--limit", "3", "--moves", "10"], cwd=PKG_ROOT,
                         capture_output=True, text=True, timeout=300, check=True).stdout
    rows = out.splitlines()[1:4]
    assert [r.split()[:2] for r in rows] == [["1", "resident"], ["2", "resident"], ["3", "resident"]]
    assert "Me and my mom" in rows[1] and "van-3" in rows[1] and rows[1].endswith("PASS")  # wheelchair → accessible van
    assert "/3 pass (" in out
