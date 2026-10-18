"""scripts/eval_sim.py (D83) runs end to end: fallback extractor, real planner and simulator, three samples."""
import subprocess
import sys

import pytest

from residents.config import PKG_ROOT
from scripts.eval_sim import classify


@pytest.mark.parametrize("ok,extracted,asked,reports,urgency_ok,want", [
    (True, True, False, True, True, "PASS"),
    (True, True, False, False, False, "FAIL"),  # equal metrics cannot conceal missed urgency
    (False, True, True, True, True, "FAIL"),   # asking does not excuse a harmful partial report
    (False, False, True, False, True, "ASK"),
    (True, True, True, False, True, "ASK"),
])
def test_scoring_distinguishes_clarification_from_a_wrong_action(ok, extracted, asked, reports, urgency_ok, want):
    assert classify(ok, extracted, asked, reports, urgency_ok) == want


def test_eval_sim_runs_on_three_samples():
    out = subprocess.run([sys.executable, "scripts/eval_sim.py", "--limit", "3", "--moves", "10"], cwd=PKG_ROOT,
                         capture_output=True, text=True, timeout=300, check=True).stdout
    rows = out.splitlines()[1:4]
    assert [r.split()[:2] for r in rows] == [["1", "resident"], ["2", "resident"], ["3", "resident"]]
    assert "Me and my mom" in rows[1] and "van-3" in rows[1] and rows[1].endswith("PASS")  # wheelchair → accessible van
    assert "/3 pass (" in out
