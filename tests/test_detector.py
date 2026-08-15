from sensorwatch.detector import RollingMadDetector


def test_detector_warms_up_before_classifying() -> None:
    detector = RollingMadDetector(window=20, min_samples=6, threshold=3.5)

    result = detector.detect(100.0, [99.8, 100.1, 100.0])

    assert result.status == "warming-up"
    assert result.is_anomaly is False
    assert result.score == 0.0


def test_detector_accepts_normal_noise() -> None:
    detector = RollingMadDetector(window=20, min_samples=6, threshold=3.5)
    history = [9.8, 10.1, 10.0, 10.2, 9.9, 10.1, 9.95, 10.05]

    result = detector.detect(10.12, history)

    assert result.status == "normal"
    assert result.is_anomaly is False
    assert result.center is not None
    assert result.scale is not None


def test_detector_flags_large_spike() -> None:
    detector = RollingMadDetector(window=20, min_samples=6, threshold=3.5)
    history = [20.0, 20.2, 19.9, 20.1, 20.0, 19.8, 20.1, 20.05]

    result = detector.detect(31.0, history)

    assert result.status == "anomaly"
    assert result.is_anomaly is True
    assert result.score > 20


def test_detector_handles_flat_sensor_baseline() -> None:
    detector = RollingMadDetector(window=20, min_samples=6, threshold=3.5)

    normal = detector.detect(50.05, [50.0] * 8)
    anomaly = detector.detect(55.0, [50.0] * 8)

    assert normal.is_anomaly is False
    assert anomaly.is_anomaly is True
