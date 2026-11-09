from ..llm.provider import extract_fields
from ..observability.metrics import EVAL_ACCURACY, EXTRACTION_FIELDS
from ..drift.detector import observe
from .dataset import load_dataset

FIELDS = ("full_name", "date_of_birth", "document_number", "expiry_date", "address")

def evaluate_one(sample: dict, record_observation: bool = True, simulate_ocr_error: bool = False):
    extracted, usage = extract_fields(sample["document_text"], sample["document_type"])
    actual = extracted.model_dump()
    # Demo-only vendor regression: corrupt one extracted field before comparison,
    # so the evaluator measures an actual field-level mismatch against ground truth.
    if simulate_ocr_error:
        actual["date_of_birth"] = "1900-01-01"
    comparisons = {}
    for field in FIELDS:
        expected, got = sample["expected"].get(field), actual.get(field)
        correct = got == expected
        comparisons[field] = {"expected": expected, "actual": got, "correct": correct}
        EXTRACTION_FIELDS.labels(field, "correct" if correct else "incorrect").inc()
    correct_count, total = sum(v["correct"] for v in comparisons.values()), len(comparisons)
    accuracy = correct_count / total if total else 0.0
    EVAL_ACCURACY.set(accuracy)
    if record_observation:
        observe(accuracy, "ocr-v2-simulated" if simulate_ocr_error else sample.get("vendor_version", "unknown"))
    return {"sample_id": sample["sample_id"], "accuracy": accuracy,
            "correct_fields": correct_count, "total_fields": total,
            "comparisons": comparisons, "usage": usage}

def run_evaluation(sample_ids=None):
    samples = load_dataset()
    if sample_ids:
        samples = [s for s in samples if s["sample_id"] in sample_ids]
    results = [evaluate_one(s) for s in samples]
    correct = sum(r["correct_fields"] for r in results)
    total = sum(r["total_fields"] for r in results)
    return {"samples_evaluated": len(results),
            "overall_field_accuracy": correct / total if total else 0.0,
            "results": results}


def run_degraded_evaluation(repetitions: int = 4):
    """Run labelled samples with a deliberately corrupted DOB extraction."""
    samples = load_dataset()
    results = []
    for _ in range(repetitions):
        for sample in samples:
            results.append(evaluate_one(sample, record_observation=True, simulate_ocr_error=True))
    correct = sum(r["correct_fields"] for r in results)
    total = sum(r["total_fields"] for r in results)
    return {"samples_evaluated": len(results),
            "overall_field_accuracy": correct / total if total else 0.0,
            "simulated_vendor_version": "ocr-v2-simulated",
            "results": results}
