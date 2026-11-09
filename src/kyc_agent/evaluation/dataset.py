import json
from pathlib import Path

DATASET_PATH = Path(__file__).resolve().parents[3] / "data" / "ground_truth.json"

def load_dataset():
    with DATASET_PATH.open(encoding="utf-8") as f:
        return json.load(f)
