"""Small deterministic checks for the propagation and geometry code."""

from datetime import UTC

from orbit_weather.catalog import SATELLITES, TLERepository
from orbit_weather.orbit import Observer, OrbitService, azimuth_to_compass, radio_horizon_circle


def test_meteor_position_and_observer_angles(tmp_path):
    repository = TLERepository(tmp_path, network_enabled=False)
    definition = SATELLITES["meteor_m2_4"]
    record = repository.get(definition.key)
    service = OrbitService(repository.timescale)
    satellite = service.satellite_from_record(record)
    epoch = satellite.epoch.utc_datetime().astimezone(UTC)

    state = service.current_state(record, definition, Observer(55.7558, 37.6173), at=epoch)

    assert -90 <= state["position"]["latitude_deg"] <= 90
    assert -180 <= state["position"]["longitude_deg"] <= 180
    assert state["position"]["altitude_km"] > 100
    assert 0 <= state["observer_view"]["azimuth_deg"] < 360


def test_radio_horizon_and_compass_labels():
    circle = radio_horizon_circle(10.0, 179.0, 820.0)

    assert len(circle["latitude_deg"]) >= 121
    assert len(circle["latitude_deg"]) == len(circle["longitude_deg"])
    assert azimuth_to_compass(0.0) == "N"
    assert azimuth_to_compass(90.0) == "E"
    assert azimuth_to_compass(225.0) == "SW"

