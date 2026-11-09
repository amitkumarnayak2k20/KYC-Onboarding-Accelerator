import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from kyc_agent.evaluation.evaluator import run_evaluation
from kyc_agent.drift.detector import reset, seed_degradation, status

def test_ground_truth_evaluation():
    reset()
    result = run_evaluation()
    assert result["samples_evaluated"] == 3
    assert result["overall_field_accuracy"] == 1.0

def test_drift_simulation_triggers_critical():
    reset()
    result = seed_degradation(count=12, accuracy=0.88, vendor_version="ocr-v2")
    assert result["status"] == "CRITICAL"
    assert status()["samples"] == 12


def test_degraded_evaluation_measures_field_errors():
    reset()
    from kyc_agent.evaluation.evaluator import run_degraded_evaluation
    result = run_degraded_evaluation(repetitions=4)
    assert result["overall_field_accuracy"] < 0.95
    assert status()["status"] == "CRITICAL"
    assert "ocr-v2-simulated" in status()["vendor_versions"]
