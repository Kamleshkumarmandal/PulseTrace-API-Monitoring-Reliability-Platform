"""PulseTrace monitoring math and reliability primitives.

These helpers are deliberately framework-independent so both the API and tests
can use exactly the same reliability calculations.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import mean
from typing import Iterable


def percentile(values: Iterable[float], quantile: float) -> float:
    """Linear-interpolated percentile. quantile must be between 0 and 1."""
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    if not 0 <= quantile <= 1:
        raise ValueError("quantile must be between 0 and 1")
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


@dataclass(frozen=True)
class ProbeResult:
    target: str
    status_code: int | None
    latency_ms: float
    success: bool
    error: str | None = None
    checked_at: str | None = None

    @classmethod
    def create(
        cls,
        target: str,
        status_code: int | None,
        latency_ms: float,
        success: bool,
        error: str | None = None,
    ) -> "ProbeResult":
        return cls(
            target=target,
            status_code=status_code,
            latency_ms=round(max(0.0, latency_ms), 2),
            success=success,
            error=error,
            checked_at=datetime.now(timezone.utc).isoformat(),
        )


class RollingMetrics:
    """Fixed-size in-memory metric window for recent probe outcomes."""

    def __init__(self, max_samples: int = 500) -> None:
        if max_samples < 1:
            raise ValueError("max_samples must be at least 1")
        self._samples: deque[ProbeResult] = deque(maxlen=max_samples)

    def add(self, result: ProbeResult) -> None:
        self._samples.append(result)

    @property
    def samples(self) -> list[ProbeResult]:
        return list(self._samples)

    def summary(self) -> dict[str, float | int]:
        values = self.samples
        if not values:
            return {
                "checks": 0, "availability": 0.0, "avg_latency_ms": 0.0,
                "p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0,
                "error_rate": 0.0,
            }
        latencies = [sample.latency_ms for sample in values]
        successes = sum(sample.success for sample in values)
        count = len(values)
        return {
            "checks": count,
            "availability": round(successes / count * 100, 2),
            "avg_latency_ms": round(mean(latencies), 2),
            "p50_ms": round(percentile(latencies, 0.50), 2),
            "p95_ms": round(percentile(latencies, 0.95), 2),
            "p99_ms": round(percentile(latencies, 0.99), 2),
            "error_rate": round((count - successes) / count * 100, 2),
        }


class CircuitBreaker:
    """Small state machine with CLOSED, OPEN and HALF_OPEN states."""

    def __init__(self, failure_threshold: int = 3, recovery_seconds: float = 30.0) -> None:
        if failure_threshold < 1 or recovery_seconds < 0:
            raise ValueError("invalid circuit breaker configuration")
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self.failures = 0
        self.state = "CLOSED"
        self.opened_at: float | None = None
        self._half_open_in_flight = False

    def allow_request(self, now: float) -> bool:
        if self.state == "CLOSED":
            return True
        if self.state == "OPEN":
            if self.opened_at is not None and now - self.opened_at >= self.recovery_seconds:
                self.state = "HALF_OPEN"
                self._half_open_in_flight = False
            else:
                return False
        if self.state == "HALF_OPEN":
            if self._half_open_in_flight:
                return False
            self._half_open_in_flight = True
            return True
        return False

    def record_success(self) -> None:
        self.failures = 0
        self.state = "CLOSED"
        self.opened_at = None
        self._half_open_in_flight = False

    def record_failure(self, now: float) -> None:
        self.failures += 1
        self._half_open_in_flight = False
        if self.state == "HALF_OPEN" or self.failures >= self.failure_threshold:
            self.state = "OPEN"
            self.opened_at = now


def detect_latency_anomaly(current_ms: float, baseline_ms: float, multiplier: float = 2.0) -> bool:
    """Flag a simple latency regression against a positive baseline."""
    if current_ms < 0 or baseline_ms < 0 or multiplier <= 0:
        raise ValueError("latencies must be non-negative and multiplier positive")
    return baseline_ms > 0 and current_ms > baseline_ms * multiplier
