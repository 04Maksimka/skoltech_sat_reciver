"use strict";

const dom = {
  satelliteSelect: document.getElementById("satelliteSelect"),
  liveButton: document.getElementById("liveButton"),
  liveButtonLabel: document.getElementById("liveButtonLabel"),
  refreshTleButton: document.getElementById("refreshTleButton"),
  customTleButton: document.getElementById("customTleButton"),
  errorMessage: document.getElementById("errorMessage"),
  warningMessage: document.getElementById("warningMessage"),
  mapLoading: document.getElementById("mapLoading"),
  skyLoading: document.getElementById("skyLoading"),
  groundTrackPlot: document.getElementById("groundTrackPlot"),
  skyViewPlot: document.getElementById("skyViewPlot"),
  observerForm: document.getElementById("observerForm"),
  observerLatitude: document.getElementById("observerLatitude"),
  observerLongitude: document.getElementById("observerLongitude"),
  observerElevation: document.getElementById("observerElevation"),
  minimumElevation: document.getElementById("minimumElevation"),
  useLocationButton: document.getElementById("useLocationButton"),
  customTleDialog: document.getElementById("customTleDialog"),
  customTleForm: document.getElementById("customTleForm"),
  customTleName: document.getElementById("customTleName"),
  customTleLine1: document.getElementById("customTleLine1"),
  customTleLine2: document.getElementById("customTleLine2"),
  customTleError: document.getElementById("customTleError"),
  closeTleDialog: document.getElementById("closeTleDialog"),
  cancelTleDialog: document.getElementById("cancelTleDialog"),
};

const palette = {
  page: "#07111b",
  map: "#081723",
  land: "#183247",
  border: "#35536a",
  text: "#edf7ff",
  muted: "#92a8ba",
  cyan: "#45d1d3",
  violet: "#b19aff",
  amber: "#f4bd62",
  green: "#73dda8",
};

const application = {
  live: true,
  stateRequestActive: false,
  predictionRequestActive: false,
  mapReady: false,
  skyReady: false,
  state: null,
  prediction: null,
  pollTimer: null,
  predictionTimer: null,
};

const plotConfig = {
  responsive: true,
  displaylogo: false,
  scrollZoom: true,
  topojsonURL: "https://cdn.plot.ly/",
  modeBarButtonsToRemove: ["lasso2d", "select2d"],
};

function currentQuery() {
  return new URLSearchParams({
    satellite: dom.satelliteSelect.value || "meteor_m2_4",
    latitude: dom.observerLatitude.value,
    longitude: dom.observerLongitude.value,
    elevation_m: dom.observerElevation.value,
    minimum_elevation: dom.minimumElevation.value,
  });
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error(`The server returned HTTP ${response.status}`);
  }
  if (!response.ok) {
    throw new Error(payload.error || `The server returned HTTP ${response.status}`);
  }
  return payload;
}

async function loadSatellites() {
  const payload = await fetchJson("/api/satellites");
  dom.satelliteSelect.replaceChildren();
  const groups = new Map();
  for (const satellite of payload.satellites) {
    const groupName = satellite.country === "Russia" ? "Russian weather satellites" : "Other weather satellites";
    if (!groups.has(groupName)) {
      const group = document.createElement("optgroup");
      group.label = groupName;
      groups.set(groupName, group);
      dom.satelliteSelect.append(group);
    }
    const option = document.createElement("option");
    option.value = satellite.key;
    option.textContent = `${satellite.label} · ${satellite.orbit_type}`;
    groups.get(groupName).append(option);
  }
  dom.satelliteSelect.value = payload.default;
  dom.satelliteSelect.disabled = false;
}

async function updateState({ showErrors = true, force = false } = {}) {
  if ((!application.live && !force) || application.stateRequestActive || dom.satelliteSelect.disabled) return;
  application.stateRequestActive = true;
  const query = currentQuery().toString();
  try {
    const payload = await fetchJson(`/api/state?${query}`);
    if (query !== currentQuery().toString()) return;
    application.state = payload;
    renderState(payload);
    hideError();
  } catch (error) {
    if (showErrors) showError(error.message);
  } finally {
    application.stateRequestActive = false;
  }
}

async function loadPrediction({ showErrors = true } = {}) {
  if (application.predictionRequestActive || dom.satelliteSelect.disabled) return;
  application.predictionRequestActive = true;
  const query = currentQuery().toString();
  dom.mapLoading.classList.remove("done");
  dom.skyLoading.classList.remove("done");
  try {
    const payload = await fetchJson(`/api/prediction?${query}`);
    if (query !== currentQuery().toString()) return;
    application.prediction = payload;
    await Promise.all([renderGroundTrack(payload), renderSkyView(payload.next_pass)]);
    renderPass(payload.next_pass);
    dom.mapLoading.classList.add("done");
    dom.skyLoading.classList.add("done");
    hideError();
  } catch (error) {
    if (showErrors) showError(error.message);
    dom.mapLoading.textContent = "Could not draw the ground track";
    dom.skyLoading.textContent = "Could not calculate the pass";
  } finally {
    application.predictionRequestActive = false;
  }
}

function renderState(payload) {
  const { satellite, position, observer_view: view, orbit, tle } = payload;
  setText("satelliteName", satellite.label);
  setText("satelliteMission", satellite.mission);
  setText("satelliteMeta", `${satellite.country} · NORAD ${satellite.norad_id}`);
  setText("positionLatitude", formatCoordinate(position.latitude_deg, "N", "S"));
  setText("positionLongitude", formatCoordinate(position.longitude_deg, "E", "W"));
  setText("positionAltitude", `${formatNumber(position.altitude_km, 1)} km`);
  setText("positionSpeed", `${formatNumber(position.speed_km_s, 3)} km/s`);
  setText("stateTime", formatClock(payload.timestamp));

  setText("viewAzimuth", `${formatNumber(view.azimuth_deg, 1)}°`);
  setText("viewDirection", view.azimuth_direction);
  setText("viewElevation", `${formatNumber(view.elevation_deg, 1)}°`);
  setText("viewRange", `${formatNumber(view.range_km, 0)} km`);
  dom.compassNeedle.style.transform = `rotate(${view.azimuth_deg}deg)`;

  const badge = document.getElementById("visibilityBadge");
  badge.className = `visibility-badge ${view.above_minimum ? "visible" : "below"}`;
  badge.textContent = view.above_minimum ? "Receivable" : view.above_horizon ? "Low elevation" : "Below horizon";

  setText("tleSource", tle.source);
  setText("tleEpoch", formatDateTime(tle.epoch));
  setText("tleAge", `${formatNumber(Math.abs(tle.epoch_age_days), 2)} days ${tle.epoch_age_days >= 0 ? "old" : "ahead"}`);
  setText("orbitInclination", `${formatNumber(orbit.inclination_deg, 2)}°`);
  setText("orbitPeriod", `${formatNumber(orbit.period_minutes, 1)} min`);
  setText("tleLines", `${tle.line1}\n${tle.line2}`);

  if (tle.warning || tle.stale) {
    const staleText = tle.stale ? "The TLE epoch is more than 14 days from now; position accuracy may be poor." : "";
    showWarning([tle.warning, staleText].filter(Boolean).join(" "));
  } else {
    hideWarning();
  }

  updateLiveMarkers(payload);
}

function renderGroundTrack(payload) {
  const past = payload.ground_track.past;
  const future = payload.ground_track.future;
  const horizon = payload.radio_horizon;
  const statePosition = application.state?.position;
  const observer = payload.observer;
  const currentLatitude = statePosition?.latitude_deg ?? firstFinite(future.latitude_deg);
  const currentLongitude = statePosition?.longitude_deg ?? firstFinite(future.longitude_deg);

  const traces = [
    {
      type: "scattergeo",
      mode: "lines",
      name: "Past 100 min",
      lat: past.latitude_deg,
      lon: past.longitude_deg,
      text: trackHoverText(past),
      hovertemplate: "%{text}<extra>Past orbit</extra>",
      line: { color: palette.muted, width: 1.4, dash: "dot" },
    },
    {
      type: "scattergeo",
      mode: "lines",
      name: "Next 200 min",
      lat: future.latitude_deg,
      lon: future.longitude_deg,
      text: trackHoverText(future),
      hovertemplate: "%{text}<extra>Predicted orbit</extra>",
      line: { color: palette.violet, width: 2.4 },
    },
    {
      type: "scattergeo",
      mode: "lines",
      name: "Radio horizon",
      lat: horizon.latitude_deg,
      lon: horizon.longitude_deg,
      hoverinfo: "skip",
      line: { color: palette.cyan, width: 1.2, dash: "dash" },
      fill: "toself",
      fillcolor: "rgba(69, 209, 211, 0.08)",
    },
    {
      type: "scattergeo",
      mode: "markers+text",
      name: "Observer",
      lat: [observer.latitude_deg],
      lon: [observer.longitude_deg],
      text: ["Observer"],
      textposition: "top center",
      hovertemplate: `Observer<br>${observer.latitude_deg.toFixed(4)}°, ${observer.longitude_deg.toFixed(4)}°<extra></extra>`,
      marker: { color: palette.amber, size: 9, line: { color: palette.text, width: 1.5 } },
      textfont: { color: palette.amber, size: 12 },
    },
    {
      type: "scattergeo",
      mode: "markers+text",
      name: "Satellite",
      lat: [currentLatitude],
      lon: [currentLongitude],
      text: [payload.satellite.label],
      textposition: "top center",
      hovertemplate: `${payload.satellite.label}<br>%{lat:.3f}°, %{lon:.3f}°<extra>Live</extra>`,
      marker: { color: palette.cyan, size: 12, line: { color: palette.text, width: 2 } },
      textfont: { color: palette.text, size: 12 },
    },
  ];

  const layout = {
    autosize: true,
    margin: { l: 0, r: 0, t: 0, b: 0 },
    paper_bgcolor: palette.map,
    plot_bgcolor: palette.map,
    font: { color: palette.text, family: "Inter, system-ui, sans-serif" },
    showlegend: false,
    geo: {
      bgcolor: palette.map,
      projection: { type: "natural earth" },
      showland: true,
      landcolor: palette.land,
      showocean: true,
      oceancolor: palette.map,
      showlakes: true,
      lakecolor: palette.map,
      showcountries: true,
      countrycolor: palette.border,
      showcoastlines: true,
      coastlinecolor: palette.border,
      showframe: true,
      framecolor: palette.border,
      lonaxis: { showgrid: true, gridcolor: "rgba(146,168,186,0.16)", dtick: 30 },
      lataxis: { showgrid: true, gridcolor: "rgba(146,168,186,0.16)", dtick: 30 },
    },
    uirevision: "keep-map-view",
  };

  return Plotly.react(dom.groundTrackPlot, traces, layout, plotConfig).then(() => {
    application.mapReady = true;
  });
}

function renderSkyView(pass) {
  const hasPass = Boolean(pass);
  const elevation = hasPass ? pass.elevation_deg : [];
  const azimuth = hasPass ? pass.azimuth_deg : [];
  const radial = elevation.map((value) => 90 - value);
  const customData = hasPass
    ? pass.time.map((time, index) => [
        formatDateTime(time),
        elevation[index],
        azimuth[index],
        pass.range_km[index],
      ])
    : [];

  const currentView = application.state?.observer_view;
  const showCurrent = currentView && currentView.elevation_deg >= 0;
  const traces = [
    {
      type: "scatterpolar",
      mode: "lines",
      name: "Next pass",
      theta: azimuth,
      r: radial,
      customdata: customData,
      hovertemplate: "%{customdata[0]}<br>Azimuth %{customdata[2]:.1f}°<br>Elevation %{customdata[1]:.1f}°<br>Range %{customdata[3]:.0f} km<extra>Predicted path</extra>",
      line: { color: palette.violet, width: 4 },
    },
    {
      type: "scatterpolar",
      mode: "markers",
      name: "Current position",
      theta: showCurrent ? [currentView.azimuth_deg] : [],
      r: showCurrent ? [90 - currentView.elevation_deg] : [],
      hovertemplate: "Now<br>Azimuth %{theta:.1f}°<br>Elevation %{customdata:.1f}°<extra></extra>",
      customdata: showCurrent ? [currentView.elevation_deg] : [],
      marker: { color: palette.cyan, size: 13, line: { color: palette.text, width: 2 } },
    },
  ];

  const annotations = hasPass
    ? []
    : [{
        text: "No pass above the selected elevation in the next 48 hours",
        x: 0.5,
        y: 0.5,
        xref: "paper",
        yref: "paper",
        showarrow: false,
        font: { color: palette.muted, size: 14 },
      }];

  const layout = {
    autosize: true,
    margin: { l: 42, r: 42, t: 32, b: 32 },
    paper_bgcolor: palette.map,
    plot_bgcolor: palette.map,
    font: { color: palette.text, family: "Inter, system-ui, sans-serif" },
    showlegend: false,
    annotations,
    polar: {
      bgcolor: palette.map,
      radialaxis: {
        range: [0, 90],
        tickvals: [0, 30, 60, 90],
        ticktext: ["90°", "60°", "30°", "0°"],
        angle: 45,
        gridcolor: "rgba(146,168,186,0.24)",
        linecolor: palette.border,
        tickfont: { color: palette.muted },
      },
      angularaxis: {
        rotation: 90,
        direction: "clockwise",
        tickmode: "array",
        tickvals: [0, 45, 90, 135, 180, 225, 270, 315],
        ticktext: ["N · 0°", "NE", "E · 90°", "SE", "S · 180°", "SW", "W · 270°", "NW"],
        gridcolor: "rgba(146,168,186,0.20)",
        linecolor: palette.border,
        tickfont: { color: palette.muted, size: 12 },
      },
    },
    uirevision: `${dom.satelliteSelect.value}-${dom.minimumElevation.value}`,
  };

  return Plotly.react(dom.skyViewPlot, traces, layout, plotConfig).then(() => {
    application.skyReady = true;
  });
}

function updateLiveMarkers(payload) {
  if (application.mapReady) {
    const horizon = radioHorizonCircle(
      payload.position.latitude_deg,
      payload.position.longitude_deg,
      payload.position.altitude_km,
    );
    Plotly.restyle(
      dom.groundTrackPlot,
      { lat: [[payload.position.latitude_deg]], lon: [[payload.position.longitude_deg]] },
      [4],
    );
    Plotly.restyle(
      dom.groundTrackPlot,
      { lat: [horizon.latitude], lon: [horizon.longitude] },
      [2],
    );
  }
  if (application.skyReady) {
    const view = payload.observer_view;
    const visible = view.elevation_deg >= 0;
    Plotly.restyle(
      dom.skyViewPlot,
      {
        theta: [visible ? [view.azimuth_deg] : []],
        r: [visible ? [90 - view.elevation_deg] : []],
        customdata: [visible ? [view.elevation_deg] : []],
      },
      [1],
    );
  }
}

function radioHorizonCircle(latitudeDeg, longitudeDeg, altitudeKm) {
  const earthRadiusKm = 6371.0088;
  const angularDistance = Math.acos(earthRadiusKm / (earthRadiusKm + Math.max(0, altitudeKm)));
  const latitude1 = latitudeDeg * Math.PI / 180;
  const longitude1 = longitudeDeg * Math.PI / 180;
  const latitude = [];
  const longitude = [];
  let previousLongitude = null;

  for (let bearingDeg = 0; bearingDeg <= 360; bearingDeg += 3) {
    const bearing = bearingDeg * Math.PI / 180;
    const latitude2 = Math.asin(
      Math.sin(latitude1) * Math.cos(angularDistance)
      + Math.cos(latitude1) * Math.sin(angularDistance) * Math.cos(bearing),
    );
    const longitude2 = longitude1 + Math.atan2(
      Math.sin(bearing) * Math.sin(angularDistance) * Math.cos(latitude1),
      Math.cos(angularDistance) - Math.sin(latitude1) * Math.sin(latitude2),
    );
    const latitudeValue = latitude2 * 180 / Math.PI;
    const longitudeValue = ((longitude2 * 180 / Math.PI + 540) % 360) - 180;
    if (previousLongitude !== null && Math.abs(longitudeValue - previousLongitude) > 180) {
      latitude.push(null);
      longitude.push(null);
    }
    latitude.push(latitudeValue);
    longitude.push(longitudeValue);
    previousLongitude = longitudeValue;
  }
  return { latitude, longitude };
}

function renderPass(pass) {
  if (!pass) {
    setText("passStatus", "No pass");
    setText("passHeadline", `Nothing above ${dom.minimumElevation.value}° in the next 48 hours`);
    setText("passStart", "—");
    setText("passMaximum", "—");
    setText("passEnd", "—");
    setText("riseDirection", "—");
    setText("peakElevation", "—");
    setText("setDirection", "—");
    return;
  }

  const statusLabels = {
    upcoming: "Upcoming",
    in_progress: "In progress",
    continuous: "Continuous view",
  };
  setText("passStatus", statusLabels[pass.status] || pass.status);
  setText("passHeadline", `${formatNumber(pass.maximum_elevation_deg, 1)}° peak toward ${compassLabel(pass.maximum_azimuth_deg)}`);
  setText("passStart", formatPassMoment(pass.start_utc));
  setText("passMaximum", formatPassMoment(pass.maximum_utc));
  setText("passEnd", formatPassMoment(pass.end_utc));
  setText("riseDirection", `${pass.rise_direction} · ${formatNumber(pass.rise_azimuth_deg, 0)}°`);
  setText("peakElevation", `${formatNumber(pass.maximum_elevation_deg, 1)}°`);
  setText("setDirection", `${pass.set_direction} · ${formatNumber(pass.set_azimuth_deg, 0)}°`);
}

function trackHoverText(track) {
  return track.time.map((time, index) => {
    if (time === null) return null;
    return `${formatDateTime(time)}<br>${track.latitude_deg[index].toFixed(2)}°, ${track.longitude_deg[index].toFixed(2)}°<br>${track.altitude_km[index].toFixed(1)} km`;
  });
}

function firstFinite(values) {
  return values.find((value) => typeof value === "number" && Number.isFinite(value));
}

function formatCoordinate(value, positive, negative) {
  return `${Math.abs(value).toFixed(3)}° ${value >= 0 ? positive : negative}`;
}

function formatNumber(value, digits) {
  return new Intl.NumberFormat(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
}

function formatClock(isoTime) {
  return new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(new Date(isoTime));
}

function formatDateTime(isoTime) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZoneName: "short",
  }).format(new Date(isoTime));
}

function formatPassMoment(isoTime) {
  return new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(isoTime));
}

function compassLabel(azimuth) {
  const labels = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
  return labels[Math.round((azimuth % 360) / 45) % 8];
}

function setText(id, value) {
  document.getElementById(id).textContent = value;
}

function showError(message) {
  dom.errorMessage.textContent = message;
  dom.errorMessage.hidden = false;
}

function hideError() {
  dom.errorMessage.hidden = true;
}

function showWarning(message) {
  dom.warningMessage.textContent = message;
  dom.warningMessage.hidden = false;
}

function hideWarning() {
  dom.warningMessage.hidden = true;
}

async function reloadAll() {
  application.mapReady = false;
  application.skyReady = false;
  application.state = null;
  await updateState({ force: true });
  await loadPrediction();
}

dom.liveButton.addEventListener("click", () => {
  application.live = !application.live;
  dom.liveButton.setAttribute("aria-pressed", String(application.live));
  dom.liveButtonLabel.textContent = application.live ? "Live · 1 s" : "Paused";
  if (application.live) updateState();
});

dom.satelliteSelect.addEventListener("change", reloadAll);

dom.observerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!dom.observerForm.reportValidity()) return;
  await reloadAll();
});

dom.useLocationButton.addEventListener("click", () => {
  if (!navigator.geolocation) {
    showError("This browser does not provide geolocation.");
    return;
  }
  dom.useLocationButton.disabled = true;
  dom.useLocationButton.textContent = "Locating…";
  navigator.geolocation.getCurrentPosition(
    async (position) => {
      dom.observerLatitude.value = position.coords.latitude.toFixed(5);
      dom.observerLongitude.value = position.coords.longitude.toFixed(5);
      if (position.coords.altitude !== null) dom.observerElevation.value = Math.round(position.coords.altitude);
      dom.useLocationButton.disabled = false;
      dom.useLocationButton.textContent = "Use my location";
      await reloadAll();
    },
    (error) => {
      dom.useLocationButton.disabled = false;
      dom.useLocationButton.textContent = "Use my location";
      showError(`Location was not available: ${error.message}`);
    },
    { enableHighAccuracy: true, timeout: 10_000, maximumAge: 300_000 },
  );
});

dom.refreshTleButton.addEventListener("click", async () => {
  dom.refreshTleButton.disabled = true;
  dom.refreshTleButton.textContent = "Checking…";
  try {
    const payload = await fetchJson("/api/tle/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ satellite: dom.satelliteSelect.value }),
    });
    if (payload.tle.warning) showWarning(payload.tle.warning);
    await reloadAll();
  } catch (error) {
    showError(error.message);
  } finally {
    dom.refreshTleButton.disabled = false;
    dom.refreshTleButton.textContent = "Refresh TLE";
  }
});

dom.customTleButton.addEventListener("click", () => {
  dom.customTleError.hidden = true;
  dom.customTleDialog.showModal();
});

function closeCustomDialog() {
  dom.customTleDialog.close();
  dom.customTleError.hidden = true;
}

dom.closeTleDialog.addEventListener("click", closeCustomDialog);
dom.cancelTleDialog.addEventListener("click", closeCustomDialog);
dom.customTleDialog.addEventListener("click", (event) => {
  if (event.target === dom.customTleDialog) closeCustomDialog();
});

dom.customTleForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  dom.customTleError.hidden = true;
  try {
    const payload = await fetchJson("/api/custom-tle", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: dom.customTleName.value,
        line1: dom.customTleLine1.value,
        line2: dom.customTleLine2.value,
      }),
    });
    const option = document.createElement("option");
    option.value = payload.satellite.key;
    option.textContent = `${payload.satellite.label} · Custom TLE`;
    dom.satelliteSelect.append(option);
    dom.satelliteSelect.value = payload.satellite.key;
    closeCustomDialog();
    await reloadAll();
  } catch (error) {
    dom.customTleError.textContent = error.message;
    dom.customTleError.hidden = false;
  }
});

document.addEventListener("visibilitychange", () => {
  if (!document.hidden && application.live) updateState({ showErrors: false });
});

async function start() {
  try {
    await loadSatellites();
    await reloadAll();
    application.pollTimer = window.setInterval(() => {
      if (!document.hidden) updateState({ showErrors: false });
    }, 1_000);
    application.predictionTimer = window.setInterval(() => {
      if (!document.hidden) loadPrediction({ showErrors: false });
    }, 60_000);
  } catch (error) {
    showError(error.message);
    dom.mapLoading.textContent = "The app could not start";
    dom.skyLoading.textContent = "The app could not start";
  }
}

start();
