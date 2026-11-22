import unittest

from pulsetrace.engine import CircuitBreaker, ProbeResult, RollingMetrics, detect_latency_anomaly, percentile


class ReliabilityEngineTests(unittest.TestCase):
    def test_percentiles_interpolate(self):
        self.assertEqual(percentile([10, 20, 30], 0.5), 20)
        self.assertAlmostEqual(percentile([10, 20, 30], 0.95), 29)
        self.assertEqual(percentile([], 0.95), 0)
        with self.assertRaises(ValueError):
            percentile([1, 2], 1.5)

    def test_rolling_metrics_summary(self):
        metrics = RollingMetrics(max_samples=3)
        metrics.add(ProbeResult.create("https://example.com", 200, 100, True))
        metrics.add(ProbeResult.create("https://example.com", 500, 300, False, "HTTP 500"))
        summary = metrics.summary()
        self.assertEqual(summary["checks"], 2)
        self.assertEqual(summary["availability"], 50.0)
        self.assertEqual(summary["error_rate"], 50.0)
        self.assertEqual(summary["p50_ms"], 200.0)

    def test_rolling_metrics_discards_old_samples(self):
        metrics = RollingMetrics(max_samples=2)
        for value in (100, 200, 300):
            metrics.add(ProbeResult.create("https://example.com", 200, value, True))
        self.assertEqual(metrics.summary()["checks"], 2)
        self.assertEqual(metrics.summary()["avg_latency_ms"], 250.0)

    def test_circuit_breaker_opens_and_recovers(self):
        breaker = CircuitBreaker(failure_threshold=2, recovery_seconds=10)
        self.assertTrue(breaker.allow_request(0))
        breaker.record_failure(1)
        self.assertEqual(breaker.state, "CLOSED")
        breaker.record_failure(2)
        self.assertEqual(breaker.state, "OPEN")
        self.assertFalse(breaker.allow_request(5))
        self.assertTrue(breaker.allow_request(12))
        self.assertEqual(breaker.state, "HALF_OPEN")
        self.assertFalse(breaker.allow_request(12))
        breaker.record_success()
        self.assertEqual(breaker.state, "CLOSED")

    def test_latency_anomaly(self):
        self.assertTrue(detect_latency_anomaly(500, 100, 2))
        self.assertFalse(detect_latency_anomaly(150, 100, 2))
        with self.assertRaises(ValueError):
            detect_latency_anomaly(-1, 100)


if __name__ == "__main__":
    unittest.main()
