"""Weather-satellite catalog and responsibly cached TLE retrieval."""

from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import requests
from skyfield.api import EarthSatellite, load

CELESTRAK_GP_URL = "https://celestrak.org/NORAD/elements/gp.php"
USER_AGENT = "OrbitWeather-Flask/0.1 (educational local satellite tracker)"


@dataclass(frozen=True)
class SatelliteDefinition:
    """Human-readable information and a fallback TLE for one satellite."""

    key: str
    label: str
    norad_id: int
    country: str
    mission: str
    orbit_type: str
    products: str
    fallback_name: str
    fallback_line1: str
    fallback_line2: str


@dataclass(frozen=True)
class TLERecord:
    """A resolved two-line element set plus provenance."""

    key: str
    name: str
    line1: str
    line2: str
    source: str
    fetched_at: str | None
    from_cache: bool
    warning: str | None = None


SATELLITES: dict[str, SatelliteDefinition] = {
    "meteor_m2_4": SatelliteDefinition(
        key="meteor_m2_4",
        label="Meteor-M2 4",
        norad_id=59051,
        country="Russia",
        mission="Operational meteorology",
        orbit_type="Sun-synchronous polar orbit",
        products="LRPT/HRPT weather imagery and atmospheric observations",
        fallback_name="METEOR-M2 4",
        fallback_line1="1 59051U 24039A   26246.19248264  .00000002  00000+0  20707-4 0  9995",
        fallback_line2="2 59051  98.7091 204.5375 0006221 311.4828  48.5815 14.22436420130351",
    ),
    "meteor_m2_3": SatelliteDefinition(
        key="meteor_m2_3",
        label="Meteor-M2 3",
        norad_id=57166,
        country="Russia",
        mission="Operational meteorology",
        orbit_type="Sun-synchronous polar orbit",
        products="LRPT/HRPT weather imagery and atmospheric observations",
        fallback_name="METEOR-M2 3",
        fallback_line1="1 57166U 23091A   26246.22995899 -.00000029  00000+0  63750-5 0  9990",
        fallback_line2="2 57166  98.6015 299.5836 0003006 315.3259  44.7677 14.24051905165621",
    ),
    "elektro_l2": SatelliteDefinition(
        key="elektro_l2",
        label="Elektro-L 2",
        norad_id=41105,
        country="Russia",
        mission="Geostationary meteorology",
        orbit_type="Geostationary orbit",
        products="Full-disk weather imagery",
        fallback_name="ELEKTRO-L 2",
        fallback_line1="1 41105U 15074A   26245.31205905 -.00000117  00000+0  00000+0 0  9990",
        fallback_line2="2 41105   6.8806  69.5443 0001749 183.6271 186.1092  1.00270385 39286",
    ),
    "noaa_20": SatelliteDefinition(
        key="noaa_20",
        label="NOAA-20 (JPSS-1)",
        norad_id=43013,
        country="United States",
        mission="Operational polar meteorology",
        orbit_type="Sun-synchronous polar orbit",
        products="Cloud, infrared, temperature, and atmospheric sounding data",
        fallback_name="NOAA 20 (JPSS-1)",
        fallback_line1="1 43013U 17073A   26246.09989350  .00000039  00000+0  39287-4 0  9996",
        fallback_line2="2 43013  98.7800 184.8791 0001852  63.7305 296.4061 14.19524080455526",
    ),
    "noaa_21": SatelliteDefinition(
        key="noaa_21",
        label="NOAA-21 (JPSS-2)",
        norad_id=54234,
        country="United States",
        mission="Operational polar meteorology",
        orbit_type="Sun-synchronous polar orbit",
        products="Cloud, infrared, temperature, and atmospheric sounding data",
        fallback_name="NOAA 21 (JPSS-2)",
        fallback_line1="1 54234U 22150A   26246.13139410  .00000023  00000+0  31343-4 0  9992",
        fallback_line2="2 54234  98.7084 183.6168 0001741  11.6305 348.4911 14.19547750197604",
    ),
    "metop_c": SatelliteDefinition(
        key="metop_c",
        label="MetOp-C",
        norad_id=43689,
        country="Europe",
        mission="Operational polar meteorology",
        orbit_type="Sun-synchronous polar orbit",
        products="Temperature, humidity, wind, ozone, and cloud observations",
        fallback_name="METOP-C",
        fallback_line1="1 43689U 18087A   26245.49424735  .00000043  00000+0  39329-4 0  9997",
        fallback_line2="2 43689  98.6573 303.6569 0000612  44.9821 315.1406 14.21512996405817",
    ),
    "goes_19": SatelliteDefinition(
        key="goes_19",
        label="GOES-19",
        norad_id=60133,
        country="United States",
        mission="Geostationary meteorology",
        orbit_type="Geostationary orbit",
        products="Full-disk weather, storm, and lightning observations",
        fallback_name="GOES 19",
        fallback_line1="1 60133U 24119A   26246.18923036 -.00000250  00000+0  00000+0 0  9998",
        fallback_line2="2 60133   0.0310 316.9267 0000747 292.0312  86.3102  1.00271225  7748",
    ),
}


class TLERepository:
    """Load CelesTrak TLEs, retaining a two-hour on-disk cache.

    CelesTrak publishes GP updates roughly every two hours. The minimum refresh
    interval here deliberately matches that cadence, while one-second UI motion
    is produced locally by SGP4 propagation rather than repeated downloads.
    """

    def __init__(
        self,
        cache_dir: Path,
        cache_seconds: int = 2 * 60 * 60,
        network_enabled: bool = True,
    ) -> None:
        self.cache_dir = cache_dir
        self.cache_seconds = max(cache_seconds, 2 * 60 * 60)
        self.network_enabled = network_enabled
        self.timescale = load.timescale(builtin=True)
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT})
        self._custom: dict[str, tuple[SatelliteDefinition, TLERecord]] = {}
        self._retry_after: dict[str, datetime] = {}
        self._lock = threading.RLock()

    def list_satellites(self) -> list[dict]:
        """Return built-in and in-memory custom satellites for the selector."""
        items = [self._definition_dict(item) for item in SATELLITES.values()]
        items.extend(self._definition_dict(item[0]) for item in self._custom.values())
        return items

    def get_definition(self, key: str) -> SatelliteDefinition:
        if key in SATELLITES:
            return SATELLITES[key]
        if key in self._custom:
            return self._custom[key][0]
        raise KeyError(key)

    def get(self, key: str, request_refresh: bool = False) -> TLERecord:
        """Resolve a current record, using cache and fallback data safely."""
        if key in self._custom:
            return self._custom[key][1]

        definition = self.get_definition(key)
        now = datetime.now(UTC)
        with self._lock:
            cached = self._read_cache(definition)
            if cached and self._cache_is_fresh(cached, now):
                return cached

            retry_after = self._retry_after.get(key)
            may_fetch = self.network_enabled and (retry_after is None or now >= retry_after)
            if may_fetch:
                try:
                    fresh = self._download(definition, now)
                except (requests.RequestException, ValueError) as error:
                    self._retry_after[key] = now + timedelta(seconds=self.cache_seconds)
                    warning = f"TLE refresh failed; using stored data ({error})"
                    if cached:
                        return TLERecord(**{**asdict(cached), "warning": warning})
                    return self._fallback(definition, warning)
                self._retry_after.pop(key, None)
                self._write_cache(definition, fresh)
                return fresh

            if cached:
                message = None
                if request_refresh and not self.network_enabled:
                    message = "Network TLE refresh is disabled"
                elif retry_after and now < retry_after:
                    message = "Previous refresh failed; waiting before another request"
                return TLERecord(**{**asdict(cached), "warning": message})
            return self._fallback(definition, "Using bundled fallback TLE")

    def add_custom(self, name: str, line1: str, line2: str) -> dict:
        """Validate and retain a custom TLE for this local server process."""
        clean_name = name.strip() or "Custom satellite"
        clean_line1 = line1.strip()
        clean_line2 = line2.strip()
        if not clean_line1.startswith("1 ") or not clean_line2.startswith("2 "):
            raise ValueError("TLE lines must begin with '1 ' and '2 '")
        if len(clean_line1) < 60 or len(clean_line2) < 60:
            raise ValueError("The TLE lines appear incomplete")

        satellite = EarthSatellite(clean_line1, clean_line2, clean_name, self.timescale)
        catalog_number = int(satellite.model.satnum)
        key = f"custom_{uuid.uuid4().hex[:10]}"
        definition = SatelliteDefinition(
            key=key,
            label=clean_name,
            norad_id=catalog_number,
            country="Custom",
            mission="User-supplied TLE",
            orbit_type="Derived from TLE",
            products="Not specified",
            fallback_name=clean_name,
            fallback_line1=clean_line1,
            fallback_line2=clean_line2,
        )
        record = TLERecord(
            key=key,
            name=clean_name,
            line1=clean_line1,
            line2=clean_line2,
            source="Custom TLE",
            fetched_at=datetime.now(UTC).isoformat(),
            from_cache=False,
        )
        with self._lock:
            self._custom[key] = (definition, record)
        return self._definition_dict(definition)

    @staticmethod
    def _definition_dict(definition: SatelliteDefinition) -> dict:
        return {
            "key": definition.key,
            "label": definition.label,
            "norad_id": definition.norad_id,
            "country": definition.country,
            "mission": definition.mission,
            "orbit_type": definition.orbit_type,
            "products": definition.products,
        }

    def _download(self, definition: SatelliteDefinition, now: datetime) -> TLERecord:
        response = self._session.get(
            CELESTRAK_GP_URL,
            params={"CATNR": str(definition.norad_id), "FORMAT": "TLE"},
            timeout=(4, 10),
            allow_redirects=False,
        )
        if response.status_code != 200:
            raise ValueError(f"CelesTrak returned HTTP {response.status_code}")
        name, line1, line2 = self._parse_tle(response.text, definition)
        return TLERecord(
            key=definition.key,
            name=name,
            line1=line1,
            line2=line2,
            source="CelesTrak GP",
            fetched_at=now.isoformat(),
            from_cache=False,
        )

    def _cache_path(self, definition: SatelliteDefinition) -> Path:
        return self.cache_dir / f"tle-{definition.norad_id}.json"

    def _read_cache(self, definition: SatelliteDefinition) -> TLERecord | None:
        path = self._cache_path(definition)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            record = TLERecord(**payload)
            self._validate_record(record, definition)
            return TLERecord(**{**asdict(record), "from_cache": True})
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def _write_cache(self, definition: SatelliteDefinition, record: TLERecord) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self._cache_path(definition)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(record), indent=2), encoding="utf-8")
        temporary.replace(path)

    def _cache_is_fresh(self, record: TLERecord, now: datetime) -> bool:
        if not record.fetched_at:
            return False
        try:
            fetched_at = datetime.fromisoformat(record.fetched_at)
        except ValueError:
            return False
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=UTC)
        return (now - fetched_at).total_seconds() < self.cache_seconds

    def _fallback(self, definition: SatelliteDefinition, warning: str) -> TLERecord:
        return TLERecord(
            key=definition.key,
            name=definition.fallback_name,
            line1=definition.fallback_line1,
            line2=definition.fallback_line2,
            source="Bundled fallback (2026-09-03)",
            fetched_at=None,
            from_cache=False,
            warning=warning,
        )

    @staticmethod
    def _parse_tle(text: str, definition: SatelliteDefinition) -> tuple[str, str, str]:
        lines = [line.rstrip() for line in text.splitlines() if line.strip()]
        line1_index = next((index for index, line in enumerate(lines) if line.startswith("1 ")), -1)
        if line1_index < 0 or line1_index + 1 >= len(lines):
            raise ValueError("CelesTrak response did not contain a TLE")
        line1 = lines[line1_index]
        line2 = lines[line1_index + 1]
        if not line2.startswith("2 "):
            raise ValueError("CelesTrak response contained an invalid second TLE line")
        name = lines[line1_index - 1].strip() if line1_index > 0 else definition.label
        record = TLERecord(definition.key, name, line1, line2, "CelesTrak GP", None, False)
        TLERepository._validate_record(record, definition)
        return name, line1, line2

    @staticmethod
    def _validate_record(record: TLERecord, definition: SatelliteDefinition) -> None:
        match1 = re.match(r"^1\s+(\d+)", record.line1)
        match2 = re.match(r"^2\s+(\d+)", record.line2)
        if not match1 or not match2 or match1.group(1) != match2.group(1):
            raise ValueError("TLE catalog numbers do not match")
        if int(match1.group(1)) != definition.norad_id:
            raise ValueError("TLE does not match the requested satellite")

