class RuleEditor {
  constructor(request) {
    this.request = request;
    this.path = "";
    this.version = 0;
    this.hasRule = false;
    this.busy = false;
    this.fields = document.querySelector("#rule-fields");
    this.status = document.querySelector("#rule-status");
    this.remove = document.querySelector("#delete-rule");
    this.reload = document.querySelector("#reload-rule");
    this.inputs = ["lower", "upper", "threshold"].map(
      (name) => document.querySelector(`#rule-${name}`)
    );
    document.querySelector("#rule-form").addEventListener("submit", (event) => {
      event.preventDefault();
      this.save();
    });
    this.remove.addEventListener("click", () => {
      if (window.confirm("Delete this rule and restore global detection settings?")) {
        this.mutate("DELETE");
      }
    });
    this.reload.addEventListener("click", () => this.load());
    document.querySelector("#clear-api-key").addEventListener("click", () => {
      document.querySelector("#api-key").value = "";
    });
    window.addEventListener("pagehide", () => {
      document.querySelector("#api-key").value = "";
    });
  }

  message(text, error = false) {
    this.status.textContent = text;
    this.status.classList.toggle("rule-error", error);
  }

  setBusy(busy) {
    this.busy = busy;
    this.fields.disabled = busy || !this.path;
    this.reload.disabled = busy || !this.path;
    this.remove.disabled = busy || !this.hasRule;
    this.fields.setAttribute("aria-busy", String(busy));
  }

  populate(rule) {
    this.hasRule = rule !== null;
    this.inputs.forEach((input, index) => {
      input.value = rule?.[["lower_bound", "upper_bound", "detector_threshold"][index]] ?? "";
    });
  }

  setSeries(sensor) {
    const path = sensor
      ? `/api/v1/rules/${encodeURIComponent(sensor.sensor_id)}/${encodeURIComponent(sensor.metric)}`
      : "";
    if (path === this.path) return;
    this.path = path;
    document.querySelector("#rule-series").textContent = sensor
      ? `${sensor.sensor_id} / ${sensor.metric}` : "Select a sensor series above.";
    this.load();
  }

  async load() {
    const version = ++this.version;
    this.populate(null);
    if (!this.path) {
      this.setBusy(false);
      this.message("Select a sensor series to configure its rule.");
      return;
    }
    this.setBusy(true);
    this.message("Loading rule…");
    try {
      const rule = await this.request(this.path, { allowMissing: true });
      if (version !== this.version) return;
      this.populate(rule);
      this.message(rule ? "Custom rule loaded." : "No custom rule. Global detection settings apply.");
      this.setBusy(false);
    } catch (error) {
      if (version !== this.version) return;
      this.message(error.message, true);
      // Require a successful reload before replacing an unknown rule.
      this.busy = false;
      this.reload.disabled = false;
    }
  }

  save() {
    if (this.busy || !this.path) return;
    const values = this.inputs.map((input) => input.value === "" ? null : input.valueAsNumber);
    const [lower, upper, threshold] = values;
    if (values.some((value) => value !== null && !Number.isFinite(value))) {
      this.message("Enter finite numbers or leave the fields blank.", true);
      return;
    }
    if (lower !== null && upper !== null && lower >= upper) {
      this.message("Lower bound must be less than upper bound.", true);
      this.inputs[1].focus();
      return;
    }
    if (threshold !== null && threshold <= 0) {
      this.message("Detection threshold must be greater than zero.", true);
      this.inputs[2].focus();
      return;
    }
    this.mutate("PUT", { lower_bound: lower, upper_bound: upper, detector_threshold: threshold });
  }

  async mutate(method, payload) {
    if (this.busy || !this.path) return;
    const version = this.version;
    this.setBusy(true);
    this.message(method === "PUT" ? "Saving rule…" : "Deleting rule…");
    try {
      const rule = await this.request(this.path, {
        method, ...(payload ? { body: JSON.stringify(payload) } : {}),
      });
      if (version !== this.version) return;
      this.populate(rule);
      this.message(method === "PUT" ? "Rule saved." : "Rule deleted. Global detection settings apply.");
    } catch (error) {
      if (version !== this.version) return;
      this.message(error.message, true);
    } finally {
      if (version === this.version) this.setBusy(false);
    }
  }
}
