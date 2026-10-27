class ConnectivityHistory {
  constructor(request) {
    this.request = request;
    this.filters = new URLSearchParams();
    this.offset = 0;
    this.limit = 50;
    this.version = 0;
    this.busy = false;
    this.previous = document.querySelector("#incident-previous");
    this.next = document.querySelector("#incident-next");
    this.status = document.querySelector("#incident-status");
    document.querySelector("#incident-filters").addEventListener("submit", (event) => {
      event.preventDefault();
      const from = document.querySelector("#incident-from").value;
      const to = document.querySelector("#incident-to").value;
      if (from && to && new Date(from) > new Date(to)) {
        this.message("Start time must not be after end time.", true);
        return;
      }
      const filters = new URLSearchParams();
      const sensor = document.querySelector("#incident-sensor").value.trim();
      const status = document.querySelector("#incident-state").value;
      if (sensor) filters.set("sensor_id", sensor);
      if (status) filters.set("status", status);
      if (from) filters.set("started_from", new Date(from).toISOString());
      if (to) filters.set("started_to", new Date(to).toISOString());
      this.filters = filters;
      this.offset = 0;
      this.load();
    });
    document.querySelector("#reload-incidents").addEventListener("click", () => this.load());
    this.previous.addEventListener("click", () => {
      this.offset = Math.max(0, this.offset - this.limit);
      this.load();
    });
    this.next.addEventListener("click", () => {
      this.offset += this.limit;
      this.load();
    });
  }

  message(text, error = false) {
    this.status.textContent = text;
    this.status.classList.toggle("rule-error", error);
  }

  async load(automatic = false) {
    if (automatic && this.busy) return;
    const version = ++this.version;
    const params = new URLSearchParams(this.filters);
    params.set("limit", this.limit);
    params.set("offset", this.offset);
    this.busy = true;
    this.previous.disabled = true;
    this.next.disabled = true;
    document.querySelector("#incident-table").setAttribute("aria-busy", "true");
    try {
      const rows = await this.request(`/api/v1/connectivity/incidents?${params}`);
      if (version !== this.version) return;
      this.render(rows);
      this.previous.disabled = this.offset === 0;
      this.next.disabled = rows.length < this.limit;
      this.message(rows.length ? `Showing incidents ${this.offset + 1}–${this.offset + rows.length}.`
        : "No incidents match these filters. The monitor must be running to record outages.");
    } catch (error) {
      if (version !== this.version) return;
      this.message(`Could not load history: ${error.message}`, true);
      this.previous.disabled = this.offset === 0;
    } finally {
      if (version === this.version) {
        this.busy = false;
        document.querySelector("#incident-table").setAttribute("aria-busy", "false");
      }
    }
  }

  render(rows) {
    document.querySelector("#incident-table").innerHTML = rows.length ? rows.map((row) => {
      const open = row.status === "open";
      const status = open ? "Open" : row.recovery_reason === "timeout_changed"
        ? "Timeout changed" : "Recovered";
      const seconds = Math.floor(row.duration_seconds);
      const duration = seconds < 60 ? `${seconds} s` : seconds < 3600
        ? `${Math.floor(seconds / 60)} min ${seconds % 60} s`
        : `${Math.floor(seconds / 3600)} h ${Math.floor((seconds % 3600) / 60)} min`;
      return `<tr>
        <td><strong>${escapeHtml(row.sensor_id)}</strong><br><small>${escapeHtml(row.metric)}</small></td>
        <td><span class="stream-status ${open ? "stale" : "online"}">${status}</span></td>
        <td>${dateTime(row.started_at)}</td>
        <td>${row.recovered_at ? dateTime(row.recovered_at) : "Awaiting recovery"}</td>
        <td>${duration}${open ? " (ongoing)" : ""}</td>
      </tr>`;
    }).join("") : '<tr><td colspan="5" class="table-empty">No connectivity incidents.</td></tr>';
  }
}
