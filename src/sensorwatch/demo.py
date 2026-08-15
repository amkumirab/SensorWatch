from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

from sensorwatch.schemas import ReadingCreate


def generate_demo_readings(
    *, count: int = 180, seed: int = 42, spike_every: int = 37
) -> list[ReadingCreate]:
    randomizer = random.Random(seed)
    definitions = (
        ("boiler-01", "temperature", "°C", 71.0, 1.1, 13.0),
        ("pump-07", "vibration", "mm/s", 2.6, 0.16, 2.8),
        ("line-03", "pressure", "bar", 6.2, 0.09, -1.1),
    )
    start = datetime.now(timezone.utc) - timedelta(seconds=count * 5)
    readings: list[ReadingCreate] = []

    for index in range(count):
        sensor_id, metric, unit, baseline, noise, spike = definitions[index % len(definitions)]
        wave = math.sin(index / 12) * noise * 0.8
        value = baseline + wave + randomizer.gauss(0, noise)
        if index > 20 and index % spike_every == 0:
            value += spike
        readings.append(
            ReadingCreate(
                sensor_id=sensor_id,
                metric=metric,
                unit=unit,
                value=round(value, 4),
                recorded_at=start + timedelta(seconds=index * 5),
            )
        )
    return readings
