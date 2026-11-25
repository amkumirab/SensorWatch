const state = { summary: null, sensors: [], readings: [], alerts: [], selectedKey: "" };
const $ = (selector) => document.querySelector(selector);
const chartLimit = 120;
let chartRange = {};
let chartRequest = 0;

function showToast(message, isError = false) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.toggle("error", isError);
  toast.classList.add("visible");
  window.setTimeout(() => toast.classList.remove("visible"), 2800);
}

async function request(url, options = {}) {
  const { allowMissing = false, allowUnhealthy = false, ...fetchOptions } = options;
  const apiKey = $("#api-key").value;
  const response = await fetch(url, {
    ...fetchOptions,
    headers: {
      "Content-Type": "application/json",
      ...(fetchOptions.method && apiKey ? { "X-API-Key": apiKey } : {}),
      ...(fetchOptions.headers || {}),
    },
  });
  if (response.status === 204 || (allowMissing && response.status === 404)) return null;
  if (!response.ok && !(allowUnhealthy && response.status === 503)) {
    const body = await response.json().catch(() => ({}));
    if (response.status === 401) throw new Error("Enter a valid API key and try again.");
    const detail = Array.isArray(body.detail)
      ? body.detail.map((item) => item.msg).join("; ") : body.detail;
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return response.json();
}

function seriesKey(sensor) { return JSON.stringify([sensor.sensor_id, sensor.metric]); }
function number(value, digits = 2) { return Number(value).toLocaleString(undefined, { maximumFractionDigits: digits }); }
function dateTime(value) { return value ? new Date(value).toLocaleString() : "—"; }
function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[character]);
}

function renderSummary() {
  const summary = state.summary;
  $("#total-readings").textContent = number(summary.total_readings, 0);
  $("#total-anomalies").textContent = number(summary.total_anomalies, 0);
  $("#active-series").textContent = number(summary.active_series, 0);
  $("#anomaly-rate").textContent = `${(summary.anomaly_rate * 100).toFixed(1)}% anomaly rate`;
  $("#last-refresh").textContent = new Date().toLocaleTimeString();
  const stale = summary.stale_series;
  $("#stale-series-count").textContent = `${number(stale, 0)} stale streams`;
  $("#fleet-status-label").textContent = !summary.active_series
    ? "No streams" : stale ? "Attention needed" : "All streams online";
  $("#fleet-status").classList.toggle("stale", stale > 0);
}

function renderSensors() {
  const select = $("#series-select");
  const list = $("#sensor-list");
  $("#series-count").textContent = state.sensors.length;

  if (!state.sensors.length) {
    select.innerHTML = '<option value="">No series available</option>';
    list.innerHTML = '<div class="empty-list">No sensors registered.</div>';
    return;
  }

  if (!state.selectedKey || !state.sensors.some((item) => seriesKey(item) === state.selectedKey)) {
    state.selectedKey = seriesKey(state.sensors[0]);
  }

  select.innerHTML = state.sensors.map((item) => {
    const key = seriesKey(item);
    return `<option value="${escapeHtml(key)}" ${key === state.selectedKey ? "selected" : ""}>${escapeHtml(item.sensor_id)} · ${escapeHtml(item.metric)}</option>`;
  }).join("");

  list.innerHTML = state.sensors.map((item) => {
    const key = seriesKey(item);
    const alertClass = item.anomaly_count ? "sensor-alert" : "";
    const stale = item.connectivity_status === "stale";
    return `<div class="sensor-row ${key === state.selectedKey ? "active" : ""}" data-key="${escapeHtml(key)}">
      <div class="sensor-row-top">
        <span class="sensor-name">${escapeHtml(item.sensor_id)}</span>
        <span class="sensor-value">${number(item.last_value)} ${escapeHtml(item.unit)}</span>
      </div>
      <div class="sensor-meta">
        <span>${escapeHtml(item.metric)} · ${item.total_readings} samples</span>
        <span class="${alertClass}">${item.anomaly_count} anomalies</span>
      </div>
      <div class="stream-meta">
        <span class="stream-status ${stale ? "stale" : "online"}">${stale ? "Stale" : "Online"}</span>
        <span>Last received ${dateTime(item.last_received_at)}</span>
      </div>
      <small class="stream-timeout">Stale after ${number(item.stale_after_seconds, 0)} s without data</small>
    </div>`;
  }).join("");

  list.querySelectorAll(".sensor-row").forEach((row) => {
    row.addEventListener("click", () => selectSeries(row.dataset.key));
  });
}

function drawChart() {
  const canvas = $("#telemetry-chart");
  const empty = $("#chart-empty");
  const parent = canvas.parentElement;
  const width = parent.clientWidth;
  const height = parent.clientHeight;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  const context = canvas.getContext("2d");
  context.scale(ratio, ratio);
  context.clearRect(0, 0, width, height);

  if (!state.readings.length) {
    empty.classList.remove("hidden");
    return;
  }
  empty.classList.add("hidden");

  const points = [...state.readings].reverse();
  const values = points.map((item) => item.value);
  let minimum = Math.min(...values);
  let maximum = Math.max(...values);
  const paddingValue = Math.max((maximum - minimum) * 0.12, Math.abs(maximum) * 0.02, 0.1);
  minimum -= paddingValue;
  maximum += paddingValue;
  const left = 48, right = 14, top = 12, bottom = 28;
  const chartWidth = width - left - right;
  const chartHeight = height - top - bottom;
  const x = (index) => left + (index / Math.max(points.length - 1, 1)) * chartWidth;
  const y = (value) => top + ((maximum - value) / (maximum - minimum)) * chartHeight;

  context.lineWidth = 1;
  context.strokeStyle = "rgba(139, 164, 157, 0.14)";
  context.fillStyle = "#789189";
  context.font = "11px system-ui";
  for (let index = 0; index <= 4; index += 1) {
    const lineY = top + (chartHeight / 4) * index;
    const label = maximum - ((maximum - minimum) / 4) * index;
    context.beginPath(); context.moveTo(left, lineY); context.lineTo(width - right, lineY); context.stroke();
    context.fillText(number(label), 2, lineY + 4);
  }

  const gradient = context.createLinearGradient(0, top, 0, height - bottom);
  gradient.addColorStop(0, "rgba(67, 230, 168, 0.18)");
  gradient.addColorStop(1, "rgba(67, 230, 168, 0)");
  context.beginPath();
  points.forEach((item, index) => index ? context.lineTo(x(index), y(item.value)) : context.moveTo(x(index), y(item.value)));
  context.lineTo(x(points.length - 1), height - bottom);
  context.lineTo(x(0), height - bottom);
  context.closePath(); context.fillStyle = gradient; context.fill();

  context.beginPath();
  points.forEach((item, index) => index ? context.lineTo(x(index), y(item.value)) : context.moveTo(x(index), y(item.value)));
  context.strokeStyle = "#43e6a8"; context.lineWidth = 2; context.stroke();

  points.filter((item) => item.is_anomaly).forEach((item) => {
    const index = points.indexOf(item);
    context.beginPath(); context.arc(x(index), y(item.value), 4.5, 0, Math.PI * 2);
    context.fillStyle = "#ff6b72"; context.fill();
    context.strokeStyle = "#07100f"; context.lineWidth = 2; context.stroke();
  });

  context.fillStyle = "#789189";
  const chartDate = (value) => new Date(/(Z|[+-]\d{2}:\d{2})$/.test(value) ? value : value + "Z");
  const first = chartDate(points[0].recorded_at);
  const last = chartDate(points.at(-1).recorded_at);
  const timeFormat = { hour: "2-digit", minute: "2-digit" };
  if (first.toDateString() !== last.toDateString()) {
    Object.assign(timeFormat, { month: "short", day: "numeric" });
  }
  const firstTime = first.toLocaleString([], timeFormat);
  const lastTime = last.toLocaleString([], timeFormat);
  context.fillText(firstTime, left, height - 6);
  context.textAlign = "right"; context.fillText(lastTime, width - right, height - 6); context.textAlign = "left";
}

function renderAnomalies(anomalies) {
  const table = $("#anomaly-table");
  if (!anomalies.length) {
    table.innerHTML = '<tr><td colspan="6" class="table-empty">No anomalies detected.</td></tr>';
    return;
  }
  table.innerHTML = anomalies.map((item) => `<tr>
    <td>${dateTime(item.recorded_at)}</td>
    <td>${escapeHtml(item.sensor_id)}</td>
    <td>${escapeHtml(item.metric)}</td>
    <td>${number(item.value)} ${escapeHtml(item.unit)}</td>
    <td>${item.baseline_center == null ? "—" : number(item.baseline_center)}</td>
    <td class="score">${number(item.anomaly_score)}σ</td>
  </tr>`).join("");
}

function renderAlerts() {
  const table = $("#alert-table");
  $("#active-alert-count").textContent = state.alerts.length;
  if (!state.alerts.length) {
    table.innerHTML = '<tr><td colspan="6" class="table-empty">No active alerts.</td></tr>';
    return;
  }
  table.innerHTML = state.alerts.map((alert) => {
    const action = alert.status === "open" ? "acknowledge" : "resolve";
    const actionLabel = alert.status === "open" ? "Acknowledge" : "Resolve";
    return `<tr>
      <td><span class="status-badge ${alert.status}">${escapeHtml(alert.status)}</span></td>
      <td><span class="severity-badge ${alert.severity}">${escapeHtml(alert.severity)}</span></td>
      <td><strong>${escapeHtml(alert.reading.sensor_id)}</strong><br><small>${escapeHtml(alert.reading.metric)}</small></td>
      <td class="alert-message">${escapeHtml(alert.message)}</td>
      <td>${dateTime(alert.created_at)}</td>
      <td><button class="button compact alert-action" type="button" data-alert-id="${alert.id}" data-action="${action}">${actionLabel}</button></td>
    </tr>`;
  }).join("");
}

async function loadSelectedSeries() {
  const requestId = ++chartRequest;
  const status = $("#telemetry-chart-status");
  if (!state.selectedKey) {
    state.readings = [];
    status.textContent = "";
    drawChart();
    return;
  }
  const [sensorId, metric] = JSON.parse(state.selectedKey);
  const filtered = Boolean(chartRange.recorded_from || chartRange.recorded_to);
  const params = new URLSearchParams({
    sensor_id: sensorId, metric, limit: filtered ? chartLimit + 1 : chartLimit, ...chartRange,
  });
  let readings;
  try {
    readings = await request(`/api/v1/readings?${params}`);
  } catch (error) {
    if (requestId === chartRequest) {
      status.textContent = "Could not update the chart. Displayed readings may be out of date.";
      throw error;
    }
    return;
  }
  if (requestId !== chartRequest) return;
  state.readings = readings.slice(0, chartLimit);
  $("#chart-title").textContent = `${sensorId} / ${metric}`;
  $("#chart-empty-title").textContent = filtered ? "No readings in this range" : "No telemetry yet";
  $("#chart-empty-help").textContent = filtered
    ? "Choose a different time range."
    : "Generate demo data or send readings through the API.";
  status.textContent = readings.length > chartLimit
    ? `Showing the latest ${chartLimit} readings. Earlier readings in this range are hidden.`
    : "";
  drawChart();
}

function setChartRange(range) {
  chartRange = range;
  $("#telemetry-range-error").hidden = true;
  loadSelectedSeries().catch((error) => showToast(error.message, true));
}

async function selectSeries(key) {
  state.selectedKey = key;
  renderSensors();
  ruleEditor.setSeries(state.sensors.find((sensor) => seriesKey(sensor) === state.selectedKey));
  try { await loadSelectedSeries(); }
  catch (error) { showToast(error.message, true); }
}

async function refresh() {
  try {
    const [summary, sensors, anomalies, alerts] = await Promise.all([
      request("/api/v1/summary"),
      request("/api/v1/sensors"),
      request("/api/v1/readings?anomalies_only=true&limit=12"),
      request("/api/v1/alerts?active_only=true&limit=12"),
    ]);
    state.summary = summary; state.sensors = sensors; state.alerts = alerts;
    renderSummary(); renderSensors(); renderAnomalies(anomalies); renderAlerts();
    ruleEditor.setSeries(state.sensors.find((sensor) => seriesKey(sensor) === state.selectedKey));
    await loadSelectedSeries();
    $("#connection").classList.remove("offline");
    $("#connection").lastChild.textContent = " API connected";
  } catch (error) {
    $("#connection").classList.add("offline");
    $("#connection").lastChild.textContent = " API unavailable";
    showToast(error.message, true);
  }
}

$("#series-select").addEventListener("change", (event) => selectSeries(event.target.value));
$("#telemetry-range").addEventListener("submit", (event) => {
  event.preventDefault();
  const fromInput = $("#telemetry-from").value;
  const toInput = $("#telemetry-to").value;
  const from = fromInput ? new Date(fromInput) : null;
  const to = toInput ? new Date(toInput) : null;
  const error = $("#telemetry-range-error");
  if ((from && !Number.isFinite(+from)) || (to && !Number.isFinite(+to))) {
    error.textContent = "Enter valid start and end times.";
  } else if (from && to && from > to) {
    error.textContent = "Start time must be before or equal to end time.";
  } else {
    const range = {};
    if (from) range.recorded_from = from.toISOString();
    if (to) range.recorded_to = to.toISOString();
    setChartRange(range);
    return;
  }
  error.hidden = false;
});
$("#clear-telemetry-range").addEventListener("click", () => {
  $("#telemetry-range").reset();
  setChartRange({});
});
$("#alert-table").addEventListener("click", async (event) => {
  const button = event.target.closest(".alert-action");
  if (!button) return;
  const operator = $("#operator-name").value.trim();
  if (!operator) {
    showToast("Enter an operator name before updating an alert", true);
    $("#operator-name").focus();
    return;
  }
  button.disabled = true;
  try {
    await request(`/api/v1/alerts/${button.dataset.alertId}/${button.dataset.action}`, {
      method: "POST",
      body: JSON.stringify({ operator }),
    });
    showToast(`Alert ${button.dataset.action}d`);
    await refresh();
  } catch (error) {
    showToast(error.message, true);
    button.disabled = false;
  }
});
$("#generate-demo").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true; button.textContent = "Generating…";
  try {
    const result = await request("/api/v1/demo/generate", { method: "POST", body: JSON.stringify({ count: 240, seed: Date.now() % 1000000, spike_every: 37 }) });
    showToast(`${result.accepted} readings added · ${result.anomalies} anomalies detected`);
    await refresh();
  } catch (error) { showToast(error.message, true); }
  finally { button.disabled = false; button.textContent = "Generate demo data"; }
});

const ruleEditor = new RuleEditor(request);
const connectivityHistory = new ConnectivityHistory(request);
window.addEventListener("resize", drawChart);
refresh();
connectivityHistory.load();
connectivityHistory.loadHealth();
window.setInterval(() => {
  refresh(); connectivityHistory.load(true); connectivityHistory.loadHealth();
}, 10000);
