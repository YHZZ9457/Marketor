from __future__ import annotations

from collections.abc import Callable

import numpy as np

StatisticsMethod = Callable[[np.ndarray], dict[str, float]]
_METHODS: dict[str, StatisticsMethod] = {}


def register_statistics_method(name: str, method: StatisticsMethod, *, replace: bool = False) -> None:
    """Register a return-distribution summarizer for reuse by services and extensions."""
    key = name.strip().lower()
    if not key:
        raise ValueError("Statistics method name cannot be empty")
    if key in _METHODS and not replace:
        raise ValueError(f"Statistics method already registered: {key}")
    _METHODS[key] = method


def statistics_methods() -> list[str]:
    return sorted(_METHODS)


def summarize_returns(values: np.ndarray, method: str = "summary") -> dict[str, float]:
    key = method.strip().lower()
    try:
        summarizer = _METHODS[key]
    except KeyError as exc:
        raise ValueError(
            f"Unknown statistics method {method!r}; available: {', '.join(statistics_methods())}"
        ) from exc
    return summarizer(values)


def _summary(values: np.ndarray) -> dict[str, float]:
    return {
        "mean": float(np.mean(values)),
        "median": float(np.median(values)),
        "positive_rate": float(np.mean(values > 0)),
        "min": float(np.min(values)),
        "max": float(np.max(values)),
    }


def _distribution(values: np.ndarray) -> dict[str, float]:
    return {
        **_summary(values),
        "std": float(np.std(values, ddof=1)) if len(values) > 1 else 0.0,
        "p10": float(np.percentile(values, 10)),
        "p25": float(np.percentile(values, 25)),
        "p75": float(np.percentile(values, 75)),
        "p90": float(np.percentile(values, 90)),
    }


register_statistics_method("summary", _summary)
register_statistics_method("distribution", _distribution)
