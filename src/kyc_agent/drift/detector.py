from collections import deque
from datetime import datetime, timezone
from threading import Lock
from ..config import settings
from ..observability.metrics import DRIFT_ACCURACY, DRIFT_STATE

_observations = deque(maxlen=settings.drift_window_size)
_lock = Lock()
_state = {"status":"INSUFFICIENT_DATA","accuracy":None,"samples":0,
          "vendor_versions":[],"updated_at":None}

def observe(accuracy: float, vendor_version: str):
    global _state
    with _lock:
        _observations.append({"accuracy":float(accuracy),"vendor_version":vendor_version})
        n = len(_observations)
        rolling = sum(x["accuracy"] for x in _observations) / n
        versions = sorted({x["vendor_version"] for x in _observations})
        if n < settings.drift_min_samples:
            status, gauge = "INSUFFICIENT_DATA", 0
        elif rolling < settings.drift_critical_accuracy:
            status, gauge = "CRITICAL", 2
        elif rolling < settings.drift_warning_accuracy:
            status, gauge = "WARNING", 1
        else:
            status, gauge = "HEALTHY", 0
        _state = {"status":status,"accuracy":rolling,"samples":n,
                  "vendor_versions":versions,"updated_at":datetime.now(timezone.utc).isoformat()}
        DRIFT_ACCURACY.set(rolling)
        DRIFT_STATE.set(gauge)
        return dict(_state)

def status():
    with _lock:
        return dict(_state)

def reset():
    global _state
    with _lock:
        _observations.clear()
        _state = {"status":"INSUFFICIENT_DATA","accuracy":None,"samples":0,
                  "vendor_versions":[],"updated_at":None}
        DRIFT_ACCURACY.set(0)
        DRIFT_STATE.set(0)

def seed_degradation(count=12, accuracy=0.88, vendor_version="ocr-v2"):
    result = None
    for _ in range(count):
        result = observe(accuracy, vendor_version)
    return result
