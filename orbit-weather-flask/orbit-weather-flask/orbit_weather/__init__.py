"""OrbitWeather Flask application factory."""

from pathlib import Path

from flask import Flask, jsonify

from .catalog import TLERepository
from .orbit import OrbitService
from .routes import bp


def create_app(test_config: dict | None = None) -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)
    project_root = Path(__file__).resolve().parent.parent
    app.config.from_mapping(
        CACHE_DIR=project_root / ".cache",
        TLE_CACHE_SECONDS=2 * 60 * 60,
        TLE_NETWORK_ENABLED=True,
        JSON_SORT_KEYS=False,
    )
    if test_config:
        app.config.update(test_config)

    repository = TLERepository(
        cache_dir=Path(app.config["CACHE_DIR"]),
        cache_seconds=int(app.config["TLE_CACHE_SECONDS"]),
        network_enabled=bool(app.config["TLE_NETWORK_ENABLED"]),
    )
    app.extensions["tle_repository"] = repository
    app.extensions["orbit_service"] = OrbitService(repository.timescale)
    app.register_blueprint(bp)

    @app.errorhandler(ValueError)
    def handle_value_error(error: ValueError):
        return jsonify(error=str(error)), 400

    @app.errorhandler(KeyError)
    def handle_key_error(error: KeyError):
        return jsonify(error=f"Unknown satellite: {error.args[0]}"), 404

    return app

