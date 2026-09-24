const state = { summary: null, sensors: [], readings: [], alerts: [], selectedKey: "" };
const $ = (selector) => document.querySelector(selector);

function showToast(message, isError = false) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.toggle("error", isError);
  toast.classList.add("visible");
  window.setTimeout(() => toast.classList.remove("visible"), 2800);
}

async function request(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  return response.json();
}

function seriesKey(sensor) { return `${sensor.sensor_id}::${sensor.metric}`; }
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
    return `<option value="${key}" ${key === state.selectedKey ? "selected" : ""}>${escapeHtml(item.sensor_id)} · ${escapeHtml(item.metric)}</option>`;
  }).join("");

  list.innerHTML = state.sensors.map((item) => {
    const key = seriesKey(item);
    const alertClass = item.anomaly_count ? "sensor-alert" : "";
    return `<div class="sensor-row ${key === state.selectedKey ? "active" : ""}" data-key="${key}">
      <div class="sensor-row-top">
        <span class="sensor-name">${escapeHtml(item.sensor_id)}</span>
        <span class="sensor-value">${number(item.last_value)} ${escapeHtml(item.unit)}</span>
      </div>
      <div class="sensor-meta">
        <span>${escapeHtml(item.metric)} · ${item.total_readings} samples</span>
        <span class="${alertClass}">${item.anomaly_count} anomalies</span>
      </div>
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
  const firstTime = new Date(points[0].recorded_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const lastTime = new Date(points.at(-1).recorded_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
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
  if (!state.selectedKey) { state.readings = []; drawChart(); return; }
  const [sensorId, metric] = state.selectedKey.split("::");
  state.readings = await request(`/api/v1/readings?sensor_id=${encodeURIComponent(sensorId)}&metric=${encodeURIComponent(metric)}&limit=120`);
  const sensor = state.sensors.find((item) => seriesKey(item) === state.selectedKey);
  $("#chart-title").textContent = sensor ? `${sensor.sensor_id} / ${sensor.metric}` : "Live telemetry";
  drawChart();
}

async function selectSeries(key) {
  state.selectedKey = key;
  renderSensors();
  await loadSelectedSeries();
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

window.addEventListener("resize", drawChart);
refresh();
window.setInterval(refresh, 10000);
