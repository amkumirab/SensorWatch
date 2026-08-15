from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DetectionResult:
    score: float
    is_anomaly: bool
    status: str
    center: float | None
    scale: float | None


class RollingMadDetector:
    """Robust online detector based on a rolling median and MAD baseline."""

    def __init__(self, *, window: int = 40, min_samples: int = 12, threshold: float = 3.5):
        if window < min_samples:
            raise ValueError("window must be greater than or equal to min_samples")
        if min_samples < 3:
            raise ValueError("min_samples must be at least 3")
        if threshold <= 0:
            raise ValueError("threshold must be positive")
        self.window = window
        self.min_samples = min_samples
        self.threshold = threshold

    def detect(self, value: float, history: Sequence[float]) -> DetectionResult:
        values = [float(item) for item in history[-self.window :] if math.isfinite(item)]
        if len(values) < self.min_samples:
            return DetectionResult(
                score=0.0,
                is_anomaly=False,
                status="warming-up",
                center=statistics.median(values) if values else None,
                scale=None,
            )

        center = statistics.median(values)
        deviations = [abs(item - center) for item in values]
        mad = statistics.median(deviations)

        if mad > 1e-12:
            scale = mad / 0.6745
            score = abs(value - center) / scale
        else:
            # A flat baseline has no statistical spread. Use a small relative floor
            # so sensor quantization noise is tolerated while real jumps are flagged.
            scale = max(abs(center) * 0.01, 0.05)
            score = abs(value - center) / scale

        is_anomaly = score >= self.threshold
        return DetectionResult(
            score=round(score, 4),
            is_anomaly=is_anomaly,
            status="anomaly" if is_anomaly else "normal",
            center=center,
            scale=scale,
        )
