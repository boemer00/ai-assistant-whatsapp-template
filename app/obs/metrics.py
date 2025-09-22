"""Minimal in-process counters and histograms.

No external dependencies. Thread-safe enough for single-process FastAPI usage.
"""

from typing import Dict, Any, Optional, Tuple, List
import threading


_COUNTERS_LOCK = threading.Lock()
_HISTOGRAMS_LOCK = threading.Lock()

# Internal store: (name, frozenset(labels.items())) -> value
_COUNTERS: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], int] = {}

# Histograms: name -> { "bins": List[int], "series": {(labels_tuple)-> {"counts": List[int], "sum_ms": float}} }
_DEFAULT_BINS: List[int] = [50, 100, 200, 500, 1000, 3000, 5000, 10000]
_HISTOGRAMS: Dict[str, Dict[str, Any]] = {}


def _labels_key(labels: Optional[Dict[str, str]]) -> Tuple[Tuple[str, str], ...]:
    if not labels:
        return tuple()
    # Stable ordering
    return tuple(sorted((str(k), str(v)) for k, v in labels.items()))


def inc_counter(metric: str, labels: Optional[Dict[str, str]] = None) -> None:
    key = (metric, _labels_key(labels))
    with _COUNTERS_LOCK:
        _COUNTERS[key] = _COUNTERS.get(key, 0) + 1


def record_timing(metric: str, value_ms: float, labels: Optional[Dict[str, str]] = None) -> None:
    if value_ms is None:
        return
    if metric not in _HISTOGRAMS:
        with _HISTOGRAMS_LOCK:
            if metric not in _HISTOGRAMS:
                _HISTOGRAMS[metric] = {"bins": list(_DEFAULT_BINS), "series": {}}
    series = _HISTOGRAMS[metric]
    bins: List[int] = series["bins"]
    lk = _labels_key(labels)
    with _HISTOGRAMS_LOCK:
        entry = series["series"].get(lk)
        if entry is None:
            entry = {"counts": [0] * (len(bins) + 1), "sum_ms": 0.0}
            series["series"][lk] = entry
        # Determine bin index
        idx = len(bins)
        for i, b in enumerate(bins):
            if value_ms <= b:
                idx = i
                break
        entry["counts"][idx] += 1
        entry["sum_ms"] += float(value_ms)


def get_metrics_snapshot() -> Dict[str, Any]:
    counters: List[Dict[str, Any]] = []
    with _COUNTERS_LOCK:
        for (name, labels_tuple), value in _COUNTERS.items():
            counters.append(
                {
                    "name": name,
                    "labels": {k: v for k, v in labels_tuple},
                    "value": value,
                }
            )

    histograms: List[Dict[str, Any]] = []
    with _HISTOGRAMS_LOCK:
        for name, h in _HISTOGRAMS.items():
            bins = h["bins"]
            for labels_tuple, entry in h["series"].items():
                histograms.append(
                    {
                        "name": name,
                        "labels": {k: v for k, v in labels_tuple},
                        "bins_ms": list(bins),
                        "counts": list(entry["counts"]),
                        "sum_ms": entry["sum_ms"],
                    }
                )

    return {"counters": counters, "histograms": histograms}
