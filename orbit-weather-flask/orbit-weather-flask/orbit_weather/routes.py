"""Flask routes for the tracker page and JSON API."""

from __future__ import annotations

from functools import lru_cache

from flask import Blueprint, Response, current_app, jsonify, render_template, request
from plotly.offline import get_plotlyjs

from .catalog import TLERepository
from .orbit import Observer, OrbitService

bp = Blueprint("orbit_weather", __name__)


def repository() -> TLERepository:
    return current_app.extensions["tle_repository"]


def orbit_service() -> OrbitService:
    return current_app.extensions["orbit_service"]


@bp.get("/")
def index():
    return render_template("index.html")


@bp.get("/assets/plotly.min.js")
def plotly_javascript():
    response = Response(plotly_bundle(), mimetype="application/javascript")
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


@lru_cache(maxsize=1)
def plotly_bundle() -> str:
    return get_plotlyjs()


@bp.get("/api/satellites")
def satellites():
    return jsonify(satellites=repository().list_satellites(), default="meteor_m2_4")


@bp.get("/api/state")
def state():
    satellite_key = request.args.get("satellite", "meteor_m2_4")
    observer = observer_from_request()
    record = repository().get(satellite_key)
    definition = repository().get_definition(satellite_key)
    return jsonify(orbit_service().current_state(record, definition, observer))


@bp.get("/api/prediction")
def prediction():
    satellite_key = request.args.get("satellite", "meteor_m2_4")
    observer = observer_from_request()
    record = repository().get(satellite_key)
    definition = repository().get_definition(satellite_key)
    return jsonify(orbit_service().prediction(record, definition, observer))


@bp.post("/api/tle/refresh")
def refresh_tle():
    payload = request.get_json(silent=True) or {}
    satellite_key = str(payload.get("satellite", "meteor_m2_4"))
    record = repository().get(satellite_key, request_refresh=True)
    definition = repository().get_definition(satellite_key)
    observer = Observer(55.7558, 37.6173)
    state_payload = orbit_service().current_state(record, definition, observer)
    return jsonify(tle=state_payload["tle"])


@bp.post("/api/custom-tle")
def custom_tle():
    payload = request.get_json(silent=True) or {}
    satellite = repository().add_custom(
        str(payload.get("name", "")),
        str(payload.get("line1", "")),
        str(payload.get("line2", "")),
    )
    return jsonify(satellite=satellite), 201


def observer_from_request() -> Observer:
    return Observer(
        latitude_deg=parse_float("latitude", 55.7558),
        longitude_deg=parse_float("longitude", 37.6173),
        elevation_m=parse_float("elevation_m", 156.0),
        minimum_elevation_deg=parse_float("minimum_elevation", 5.0),
    )


def parse_float(name: str, default: float) -> float:
    raw_value = request.args.get(name)
    if raw_value in (None, ""):
        return default
    try:
        return float(raw_value)
    except ValueError as error:
        raise ValueError(f"{name} must be a number") from error
