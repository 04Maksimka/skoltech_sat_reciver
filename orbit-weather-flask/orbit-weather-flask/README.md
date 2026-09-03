# OrbitWeather Flask

A local Flask dashboard that propagates weather-satellite TLEs with Skyfield/SGP4. It shows:

- a live satellite position that moves once per second;
- the previous 100 minutes and next 200 minutes of the ground track;
- the theoretical radio-horizon footprint;
- azimuth, elevation, and range from an editable observer location;
- a polar sky plot for the next receivable pass;
- Russian Meteor-M2 4 and Meteor-M2 3 weather satellites, plus several comparison satellites;
- custom TLE input.

Meteor-M2 4 is the default. The WMO describes it as a Russian operational, sun-synchronous meteorological satellite with LRPT and HRPT data availability.

## Requirements

- Python 3.12 or later
- [uv](https://docs.astral.sh/uv/)
- Internet access for fresh CelesTrak TLE data and Plotly's world-map geometry

Plotly JavaScript is served from the installed Python package, so no separate npm installation is needed.

## Run

From this directory:

```bash
uv sync
uv run flask --app app run --debug
```

Then open <http://127.0.0.1:5000>.

You can also run:

```bash
uv run python app.py
```

The dependencies are already declared in `pyproject.toml`, and `uv.lock` pins the resolved versions. If you prefer to create the dependency list yourself in a new project, the equivalent command is:

```bash
uv add flask numpy plotly requests skyfield
```

## Use your receiving location

Enter the observer latitude, longitude, height above sea level, and minimum useful elevation. The default coordinates are central Moscow. You can press **Use my location** to ask the browser for your current position.

The polar sky plot uses:

- angle around the circle: azimuth, clockwise from north;
- distance from the centre: `90° − elevation`;
- centre: zenith (`90°` elevation);
- outside edge: horizon (`0°` elevation).

Hover over the next-pass path to see its time, azimuth, elevation, and slant range. The cyan point moves once per second when the satellite is above your horizon.

## TLE refresh behaviour

The app downloads only the selected satellite's GP element set from CelesTrak and caches it for at least two hours. The one-second animation uses local SGP4 propagation of that cached TLE; it does **not** make a network request every second. This follows CelesTrak's published two-hour GP update cadence.

If CelesTrak is unavailable, the app uses the last cached TLE. A bundled snapshot dated 2026-09-03 is the final fallback, and the interface clearly warns when the TLE epoch is stale.

## Test and lint

```bash
uv run pytest
uv run ruff check .
```

## Project structure

```text
app.py                         Flask development entry point
orbit_weather/__init__.py      Application factory
orbit_weather/catalog.py       Satellite catalog, TLE download, and cache
orbit_weather/orbit.py         SGP4 position and pass calculations
orbit_weather/routes.py        Page and JSON API routes
orbit_weather/templates/       Dashboard HTML
orbit_weather/static/          CSS and live Plotly interaction
tests/                         Deterministic geometry/propagation checks
```

## Accuracy and reception limits

- A TLE is an orbit estimate, not precision ephemeris. Predictions degrade as the requested time moves away from the TLE epoch.
- The sky plot is geometric. It does not model terrain, buildings, trees, refraction, antenna gain, receiver sensitivity, Doppler correction, or transmitter availability.
- Being above the horizon does not guarantee that a satellite is transmitting a signal you can legally or technically receive. Verify the current downlink mode, frequency, polarization, bandwidth, equipment, and local rules separately.
- The radio-horizon footprint is the zero-degree geometric visibility limit, not the imaging swath of a weather instrument.

## Data and method references

- [CelesTrak GP data formats](https://celestrak.org/NORAD/documentation/gp-data-formats.php)
- [CelesTrak usage policy](https://celestrak.org/usage-policy.php)
- [Skyfield Earth-satellite documentation](https://rhodesmill.org/skyfield/earth-satellites.html)
- [WMO OSCAR: Meteor-M N2-4](https://space.oscar.wmo.int/satellites/view/meteor_m_n2_4)

