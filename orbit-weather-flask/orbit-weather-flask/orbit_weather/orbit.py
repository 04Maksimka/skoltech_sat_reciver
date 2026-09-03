"""SGP4 orbit propagation and observer pass calculations."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import numpy as np
from skyfield.api import EarthSatellite, Timescale, wgs84

from .catalog import SatelliteDefinition, TLERecord

EARTH_MEAN_RADIUS_KM = 6371.0088


@dataclass(frozen=True)
class Observer:
    """A ground observer in WGS84 coordinates."""

    latitude_deg: float
    longitude_deg: float
    elevation_m: float = 0.0
    minimum_elevation_deg: float = 5.0

    def validate(self) -> None:
        if not -90.0 <= self.latitude_deg <= 90.0:
            raise ValueError("Observer latitude must be between -90 and 90 degrees")
        if not -180.0 <= self.longitude_deg <= 180.0:
            raise ValueError("Observer longitude must be between -180 and 180 degrees")
        if not -500.0 <= self.elevation_m <= 10_000.0:
            raise ValueError("Observer elevation must be between -500 and 10000 metres")
        if not 0.0 <= self.minimum_elevation_deg <= 89.0:
            raise ValueError("Minimum elevation must be between 0 and 89 degrees")


class OrbitService:
    """Calculate live positions, ground tracks, and receiver pointing paths."""

    def __init__(self, timescale: Timescale) -> None:
        self.timescale = timescale

    def satellite_from_record(self, record: TLERecord) -> EarthSatellite:
        return EarthSatellite(record.line1, record.line2, record.name, self.timescale)

    def current_state(
        self,
        record: TLERecord,
        definition: SatelliteDefinition,
        observer: Observer,
        at: datetime | None = None,
    ) -> dict:
        observer.validate()
        moment = self._normalise_datetime(at or datetime.now(UTC))
        satellite = self.satellite_from_record(record)
        time = self.timescale.from_datetime(moment)
        geocentric = satellite.at(time)
        latitude, longitude = wgs84.latlon_of(geocentric)
        height = wgs84.height_of(geocentric)
        speed = float(np.linalg.norm(geocentric.velocity.km_per_s))

        ground_observer = wgs84.latlon(
            observer.latitude_deg,
            observer.longitude_deg,
            elevation_m=observer.elevation_m,
        )
        topocentric = (satellite - ground_observer).at(time)
        altitude_angle, azimuth, distance = topocentric.altaz()
        epoch = satellite.epoch.utc_datetime().astimezone(UTC)
        epoch_age_days = (moment - epoch).total_seconds() / 86_400.0
        orbit_period_minutes = 2.0 * math.pi / float(satellite.model.no_kozai)

        return {
            "timestamp": moment.isoformat(),
            "satellite": self._satellite_metadata(definition, satellite),
            "position": {
                "latitude_deg": round(float(latitude.degrees), 6),
                "longitude_deg": round(float(longitude.degrees), 6),
                "altitude_km": round(float(height.km), 3),
                "speed_km_s": round(speed, 4),
            },
            "observer_view": {
                "azimuth_deg": round(float(azimuth.degrees) % 360.0, 3),
                "azimuth_direction": azimuth_to_compass(float(azimuth.degrees)),
                "elevation_deg": round(float(altitude_angle.degrees), 3),
                "range_km": round(float(distance.km), 2),
                "above_horizon": bool(altitude_angle.degrees >= 0.0),
                "above_minimum": bool(
                    altitude_angle.degrees >= observer.minimum_elevation_deg
                ),
            },
            "orbit": {
                "inclination_deg": round(math.degrees(float(satellite.model.inclo)), 4),
                "period_minutes": round(orbit_period_minutes, 3),
            },
            "tle": {
                "name": record.name,
                "line1": record.line1,
                "line2": record.line2,
                "source": record.source,
                "fetched_at": record.fetched_at,
                "epoch": epoch.isoformat(),
                "epoch_age_days": round(epoch_age_days, 3),
                "stale": abs(epoch_age_days) > 14.0,
                "warning": record.warning,
            },
        }

    def prediction(
        self,
        record: TLERecord,
        definition: SatelliteDefinition,
        observer: Observer,
        at: datetime | None = None,
    ) -> dict:
        observer.validate()
        moment = self._normalise_datetime(at or datetime.now(UTC))
        satellite = self.satellite_from_record(record)
        ground_track = self._ground_track(satellite, moment)
        current_geocentric = satellite.at(self.timescale.from_datetime(moment))
        current_latitude, current_longitude = wgs84.latlon_of(current_geocentric)
        current_height = wgs84.height_of(current_geocentric)
        footprint = radio_horizon_circle(
            float(current_latitude.degrees),
            float(current_longitude.degrees),
            max(0.0, float(current_height.km)),
        )
        next_pass = self._next_pass(satellite, observer, moment)
        return {
            "generated_at": moment.isoformat(),
            "satellite": self._satellite_metadata(definition, satellite),
            "observer": {
                "latitude_deg": observer.latitude_deg,
                "longitude_deg": observer.longitude_deg,
                "elevation_m": observer.elevation_m,
                "minimum_elevation_deg": observer.minimum_elevation_deg,
            },
            "ground_track": ground_track,
            "radio_horizon": footprint,
            "next_pass": next_pass,
        }

    def _ground_track(self, satellite: EarthSatellite, moment: datetime) -> dict:
        past_datetimes = [moment + timedelta(minutes=minute) for minute in range(-100, 1)]
        future_datetimes = [moment + timedelta(minutes=minute) for minute in range(0, 201)]
        return {
            "past": self._ground_points(satellite, past_datetimes),
            "future": self._ground_points(satellite, future_datetimes),
        }

    def _ground_points(
        self, satellite: EarthSatellite, datetimes: list[datetime]
    ) -> dict[str, list]:
        times = self.timescale.from_datetimes(datetimes)
        geocentric = satellite.at(times)
        latitudes, longitudes = wgs84.latlon_of(geocentric)
        heights = wgs84.height_of(geocentric).km
        longitude_values = np.asarray(longitudes.degrees, dtype=float)
        latitude_values = np.asarray(latitudes.degrees, dtype=float)
        height_values = np.asarray(heights, dtype=float)

        output_latitudes: list[float | None] = []
        output_longitudes: list[float | None] = []
        output_heights: list[float | None] = []
        output_times: list[str | None] = []
        previous_longitude: float | None = None
        for dt_value, latitude, longitude, height in zip(
            datetimes, latitude_values, longitude_values, height_values, strict=True
        ):
            longitude = wrap_longitude(float(longitude))
            if previous_longitude is not None and abs(longitude - previous_longitude) > 180.0:
                output_latitudes.append(None)
                output_longitudes.append(None)
                output_heights.append(None)
                output_times.append(None)
            output_latitudes.append(round(float(latitude), 5))
            output_longitudes.append(round(longitude, 5))
            output_heights.append(round(float(height), 2))
            output_times.append(dt_value.isoformat())
            previous_longitude = longitude
        return {
            "latitude_deg": output_latitudes,
            "longitude_deg": output_longitudes,
            "altitude_km": output_heights,
            "time": output_times,
        }

    def _next_pass(
        self, satellite: EarthSatellite, observer: Observer, moment: datetime
    ) -> dict | None:
        ground_observer = wgs84.latlon(
            observer.latitude_deg,
            observer.longitude_deg,
            elevation_m=observer.elevation_m,
        )
        start_time = self.timescale.from_datetime(moment)
        search_end = moment + timedelta(hours=48)
        end_time = self.timescale.from_datetime(search_end)
        event_times, events = satellite.find_events(
            ground_observer,
            start_time,
            end_time,
            altitude_degrees=observer.minimum_elevation_deg,
        )

        current_altitude, _, _ = (satellite - ground_observer).at(start_time).altaz()
        above_now = float(current_altitude.degrees) >= observer.minimum_elevation_deg
        event_rows = [
            (time.utc_datetime().astimezone(UTC), int(event))
            for time, event in zip(event_times, events, strict=True)
        ]

        status = "upcoming"
        if above_now:
            pass_start = moment
            status = "in_progress"
            pass_end = next((time for time, event in event_rows if event == 2), None)
            if pass_end is None:
                return self._continuous_view(satellite, ground_observer, moment)
        else:
            rise_index = next((index for index, row in enumerate(event_rows) if row[1] == 0), None)
            if rise_index is None:
                return None
            pass_start = event_rows[rise_index][0]
            pass_end = next(
                (time for time, event in event_rows[rise_index + 1 :] if event == 2),
                None,
            )
            if pass_end is None:
                return None

        duration_seconds = max(1.0, (pass_end - pass_start).total_seconds())
        step_seconds = max(5.0, min(20.0, duration_seconds / 90.0))
        samples = max(2, int(math.ceil(duration_seconds / step_seconds)) + 1)
        sample_datetimes = [
            pass_start + timedelta(seconds=index * duration_seconds / (samples - 1))
            for index in range(samples)
        ]
        return self._sky_path(
            satellite,
            ground_observer,
            sample_datetimes,
            observer.minimum_elevation_deg,
            status,
        )

    def _continuous_view(
        self, satellite: EarthSatellite, ground_observer, moment: datetime
    ) -> dict:
        sample_datetimes = [moment + timedelta(minutes=5 * index) for index in range(73)]
        return self._sky_path(
            satellite,
            ground_observer,
            sample_datetimes,
            0.0,
            "continuous",
        )

    def _sky_path(
        self,
        satellite: EarthSatellite,
        ground_observer,
        datetimes: list[datetime],
        minimum_elevation_deg: float,
        status: str,
    ) -> dict:
        times = self.timescale.from_datetimes(datetimes)
        topocentric = (satellite - ground_observer).at(times)
        altitudes, azimuths, distances = topocentric.altaz()
        elevation_values = np.asarray(altitudes.degrees, dtype=float)
        azimuth_values = np.mod(np.asarray(azimuths.degrees, dtype=float), 360.0)
        distance_values = np.asarray(distances.km, dtype=float)
        max_index = int(np.nanargmax(elevation_values))

        return {
            "status": status,
            "start_utc": datetimes[0].isoformat(),
            "maximum_utc": datetimes[max_index].isoformat(),
            "end_utc": datetimes[-1].isoformat(),
            "duration_seconds": round((datetimes[-1] - datetimes[0]).total_seconds(), 1),
            "maximum_elevation_deg": round(float(elevation_values[max_index]), 2),
            "maximum_azimuth_deg": round(float(azimuth_values[max_index]), 2),
            "rise_azimuth_deg": round(float(azimuth_values[0]), 2),
            "rise_direction": azimuth_to_compass(float(azimuth_values[0])),
            "set_azimuth_deg": round(float(azimuth_values[-1]), 2),
            "set_direction": azimuth_to_compass(float(azimuth_values[-1])),
            "minimum_elevation_deg": minimum_elevation_deg,
            "time": [value.isoformat() for value in datetimes],
            "azimuth_deg": np.round(azimuth_values, 3).tolist(),
            "elevation_deg": np.round(elevation_values, 3).tolist(),
            "range_km": np.round(distance_values, 2).tolist(),
        }

    @staticmethod
    def _satellite_metadata(
        definition: SatelliteDefinition, satellite: EarthSatellite
    ) -> dict:
        return {
            "key": definition.key,
            "label": definition.label,
            "norad_id": int(satellite.model.satnum),
            "country": definition.country,
            "mission": definition.mission,
            "orbit_type": definition.orbit_type,
            "products": definition.products,
        }

    @staticmethod
    def _normalise_datetime(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def azimuth_to_compass(azimuth_deg: float) -> str:
    """Convert clockwise azimuth degrees into a 16-point compass label."""
    labels = (
        "N",
        "NNE",
        "NE",
        "ENE",
        "E",
        "ESE",
        "SE",
        "SSE",
        "S",
        "SSW",
        "SW",
        "WSW",
        "W",
        "WNW",
        "NW",
        "NNW",
    )
    index = int((azimuth_deg % 360.0 + 11.25) // 22.5) % 16
    return labels[index]


def wrap_longitude(longitude_deg: float) -> float:
    return (longitude_deg + 180.0) % 360.0 - 180.0


def radio_horizon_circle(
    latitude_deg: float,
    longitude_deg: float,
    altitude_km: float,
    bearings: Iterable[float] | None = None,
) -> dict[str, list[float | None]]:
    """Return the theoretical zero-elevation radio-horizon circle."""
    if bearings is None:
        bearings = np.linspace(0.0, 360.0, 121)
    angular_distance = math.acos(
        EARTH_MEAN_RADIUS_KM / (EARTH_MEAN_RADIUS_KM + max(0.0, altitude_km))
    )
    latitude1 = math.radians(latitude_deg)
    longitude1 = math.radians(longitude_deg)
    latitude_values: list[float | None] = []
    longitude_values: list[float | None] = []
    previous_longitude: float | None = None

    for bearing_deg in bearings:
        bearing = math.radians(float(bearing_deg))
        latitude2 = math.asin(
            math.sin(latitude1) * math.cos(angular_distance)
            + math.cos(latitude1) * math.sin(angular_distance) * math.cos(bearing)
        )
        longitude2 = longitude1 + math.atan2(
            math.sin(bearing) * math.sin(angular_distance) * math.cos(latitude1),
            math.cos(angular_distance) - math.sin(latitude1) * math.sin(latitude2),
        )
        latitude = math.degrees(latitude2)
        longitude = wrap_longitude(math.degrees(longitude2))
        if previous_longitude is not None and abs(longitude - previous_longitude) > 180.0:
            latitude_values.append(None)
            longitude_values.append(None)
        latitude_values.append(round(latitude, 5))
        longitude_values.append(round(longitude, 5))
        previous_longitude = longitude

    return {"latitude_deg": latitude_values, "longitude_deg": longitude_values}
