const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const sourcePath = path.join(__dirname, "../static/core/js/bot_control.js");
const source = fs.readFileSync(sourcePath, "utf8");

function classList(names) {
  const items = new Set(names);
  return { contains(name) { return items.has(name); } };
}

function control(attrs = {}) {
  return {
    name: attrs.name || "",
    value: attrs.value || "",
    type: attrs.type || "text",
    checked: Boolean(attrs.checked),
    disabled: false,
    hidden: Boolean(attrs.hidden),
    textContent: attrs.textContent || "",
    className: attrs.className || "",
    classList: classList(attrs.classes || []),
    action: attrs.action || "",
    elements: attrs.elements || [],
    attributes: { ...(attrs.attributes || {}) },
    listeners: {},
    submitCalls: 0,
    getAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : null; },
    setAttribute(name, value) { this.attributes[name] = String(value); },
    addEventListener(type, callback) { this.listeners[type] = callback; },
    dispatch(type, event = {}) {
      const listener = this.listeners[type];
      return listener ? listener(event) : undefined;
    },
    reportValidity() { return attrs.valid !== false; },
    submit() { this.submitCalls += 1; }
  };
}

function FakeFormData(form) {
  const entries = [];
  const elements = form.elements || [];
  for (const element of elements) {
    if (!element.name || element.disabled) continue;
    if (element.type === "checkbox" && !element.checked) continue;
    entries.push([element.name, element.value]);
  }
  this.entries = entries;
  this.get = (name) => {
    const found = entries.find(([key]) => key === name);
    return found ? found[1] : null;
  };
}

function jsonResponse(body, { ok = true, contentType = "application/json" } = {}) {
  return {
    ok,
    headers: { get: (name) => (name === "Content-Type" ? contentType : null) },
    json: async () => body
  };
}

function harness() {
  const csrf = control({ name: "csrfmiddlewaretoken", value: "csrf-token", type: "hidden" });
  const reason = control({ name: "reason", value: "motivo", type: "text" });
  const confirm = control({ name: "confirm", value: "yes", type: "checkbox", checked: true });
  const next = control({ name: "next", value: "/dashboard/", type: "hidden" });
  const pauseButton = control({ type: "submit" });
  const pauseForm = control({
    classes: ["bot-control-form"],
    action: "/bot/stop/",
    elements: [csrf, reason, confirm, next, pauseButton],
    attributes: { "data-bot-control-action": "pause" }
  });
  const resumeReason = control({ name: "reason", value: "continuar", type: "text" });
  const resumeButton = control({ type: "submit" });
  const resumeForm = control({
    classes: ["bot-control-form"],
    action: "/bot/resume/",
    elements: [control({ name: "csrfmiddlewaretoken", value: "csrf-token", type: "hidden" }), resumeReason, resumeButton],
    attributes: { "data-bot-control-action": "resume" }
  });
  const state = control({ textContent: "Estado solicitado: en ejecución", attributes: { "data-status": "running" } });
  const updated = control({ textContent: "sin registro" });
  const updatedBy = control({ textContent: "—" });
  const reasonText = control({ textContent: "—" });
  const flash = control();
  const retry = control({ type: "button", hidden: true });
  const nodes = [csrf, reason, confirm, next, pauseButton, resumeReason, resumeButton, retry];
  const panel = control({ attributes: { "data-status-url": "/bot/status/" } });
  panel.querySelector = (selector) => {
    const found = {
      "[data-bot-control-flash]": flash,
      "[data-bot-control-state]": state,
      "[data-bot-control-updated]": updated,
      "[data-bot-control-updated-by]": updatedBy,
      "[data-bot-control-reason]": reasonText,
      "[data-bot-control-retry]": retry
    };
    return found[selector] || null;
  };
  panel.querySelectorAll = (selector) => (selector === "input, button, textarea, select" ? nodes : []);

  const requests = [];
  const queue = [];
  function fetch(url, options) {
    requests.push({ url, options });
    return new Promise((resolve, reject) => {
      queue.push({ resolve, reject });
    });
  }
  const windowObject = { FormData: FakeFormData };
  const context = {
    document: { getElementById: (id) => (id === "control-seguro" ? panel : null) },
    window: windowObject,
    FormData: FakeFormData,
    fetch,
    Intl,
    Date,
    Promise,
    Error,
    isNaN
  };
  windowObject.fetch = fetch;
  vm.runInNewContext(source, context);
  return { panel, pauseForm, resumeForm, pauseButton, resumeButton, retry, state, updated, updatedBy, reasonText, flash, requests, queue };
}

function respond(queue, index, response) {
  queue[index].resolve(response);
}

async function flush() {
  for (let i = 0; i < 8; i += 1) await Promise.resolve();
}

const pausedPayload = {
  is_paused: true,
  status: "paused",
  updated_at: "2026-10-25T18:16:56+00:00",
  updated_by: "owner@example.com",
  reason: "motivo"
};

test("the pause script never replays a form submission", () => {
  assert.doesNotMatch(source, /form\.submit\s*\(/);
  assert.doesNotMatch(source, /\.submit\s*\(/);
});

test("a successful pause updates the requested state and restores the controls", async () => {
  const ui = harness();
  const pending = ui.panel.dispatch("submit", { target: ui.pauseForm, preventDefault() {} });

  assert.equal(ui.requests.length, 1);
  assert.equal(ui.requests[0].url, "/bot/stop/");
  assert.equal(ui.requests[0].options.method, "POST");
  assert.equal(ui.requests[0].options.credentials, "same-origin");
  assert.equal(ui.requests[0].options.headers.Accept, "application/json");
  assert.equal(ui.requests[0].options.headers["X-CSRFToken"], "csrf-token");
  assert.equal(ui.requests[0].options.body.get("csrfmiddlewaretoken"), "csrf-token");
  assert.equal(ui.requests[0].options.body.get("confirm"), "yes");
  assert.equal(ui.pauseButton.disabled, true);
  assert.equal(ui.resumeButton.disabled, true);
  assert.equal(ui.retry.hidden, true);
  assert.equal(ui.pauseForm.submitCalls, 0);

  respond(ui.queue, 0, jsonResponse(pausedPayload));
  await pending;

  assert.equal(ui.state.textContent, "Estado solicitado: pausado");
  assert.equal(ui.state.getAttribute("data-status"), "paused");
  assert.equal(ui.updatedBy.textContent, "owner@example.com");
  assert.equal(ui.reasonText.textContent, "motivo");
  assert.match(ui.updated.textContent, /25\/10\/2026 15:16 ART/);
  assert.equal(ui.flash.textContent, "Pausa solicitada");
  assert.match(ui.flash.className, /alert-success/);
  assert.equal(ui.pauseButton.disabled, false);
  assert.equal(ui.resumeButton.disabled, false);
  assert.equal(ui.retry.hidden, true);
  assert.equal(ui.pauseForm.submitCalls, 0);
});

test("a committed pause with a failed response is not replayed and can be retried explicitly", async () => {
  const ui = harness();
  const prevented = { called: false };
  const pending = ui.panel.dispatch("submit", {
    target: ui.pauseForm,
    preventDefault() { prevented.called = true; }
  });
  await flush();
  assert.equal(prevented.called, true);
  assert.equal(ui.requests.length, 1);

  respond(ui.queue, 0, jsonResponse({ error: "gateway" }, { ok: false }));
  await flush();

  assert.equal(ui.pauseForm.submitCalls, 0);
  assert.equal(ui.requests.length, 2);
  assert.equal(ui.requests[1].url, "/bot/status/");
  assert.equal(ui.requests[1].options.method, "GET");
  assert.equal(ui.requests[1].options.headers.Accept, "application/json");
  assert.match(ui.flash.textContent, /resultado incierto/i);
  assert.match(ui.flash.textContent, /no se reenvió el pedido/i);

  respond(ui.queue, 1, jsonResponse({
    is_paused: true,
    status: "paused",
    updated_at: "2026-10-25T18:16:56+00:00",
    updated_by: "owner@example.com",
    reason: "committed"
  }));
  await pending;

  assert.equal(ui.requests.length, 2);
  assert.equal(ui.state.textContent, "Estado solicitado: pausado");
  assert.equal(ui.reasonText.textContent, "committed");
  assert.match(ui.updated.textContent, /15:16 ART/);
  assert.match(ui.flash.textContent, /resultado incierto/i);
  assert.doesNotMatch(ui.flash.textContent, /Pausa solicitada/);
  assert.equal(ui.retry.hidden, false);
  assert.equal(ui.pauseButton.disabled, false);
  assert.equal(ui.pauseForm.submitCalls, 0);

  const retryPending = ui.retry.dispatch("click");
  await flush();
  assert.equal(ui.requests.length, 3);
  assert.equal(ui.requests[2].url, "/bot/stop/");
  assert.equal(ui.requests[2].options.body.get("confirm"), "yes");
  respond(ui.queue, 2, jsonResponse(pausedPayload));
  await retryPending;
  assert.equal(ui.flash.textContent, "Pausa solicitada");
  assert.equal(ui.retry.hidden, true);
});

test("an aborted response also reads the saved state and does not submit the form", async () => {
  const ui = harness();
  const pending = ui.panel.dispatch("submit", { target: ui.pauseForm, preventDefault() {} });
  await flush();
  ui.queue[0].reject(new Error("aborted"));
  await flush();

  assert.equal(ui.pauseForm.submitCalls, 0);
  assert.equal(ui.requests[1].url, "/bot/status/");
  respond(ui.queue, 1, jsonResponse({ ok: false }, { ok: false, contentType: "text/html" }));
  await pending;

  assert.match(ui.flash.textContent, /resultado incierto/i);
  assert.match(ui.flash.textContent, /no se pudo volver a leer el estado guardado/i);
  assert.equal(ui.state.textContent, "Estado solicitado: en ejecución");
  assert.equal(ui.retry.hidden, false);
  assert.equal(ui.requests.length, 2);
});

test("a second submit while a request is pending does not start another write", async () => {
  const ui = harness();
  const first = ui.panel.dispatch("submit", { target: ui.pauseForm, preventDefault() {} });
  await flush();
  const secondPrevented = { called: false };
  const second = ui.panel.dispatch("submit", {
    target: ui.resumeForm,
    preventDefault() { secondPrevented.called = true; }
  });

  assert.equal(secondPrevented.called, true);
  assert.equal(ui.requests.length, 1);
  assert.equal(ui.pauseButton.disabled, true);
  assert.equal(ui.resumeButton.disabled, true);
  assert.equal(await second, undefined);

  respond(ui.queue, 0, jsonResponse(pausedPayload));
  await first;
  assert.equal(ui.requests.length, 1);
  assert.equal(ui.pauseButton.disabled, false);
  assert.equal(ui.state.textContent, "Estado solicitado: pausado");
});

test("an older response cannot overwrite a newer requested state", async () => {
  const ui = harness();
  const pause = ui.panel.dispatch("submit", { target: ui.pauseForm, preventDefault() {} });
  await flush();
  respond(ui.queue, 0, jsonResponse(pausedPayload));
  await pause;
  assert.equal(ui.panel.__botControl.currentSeq(), 1);
  assert.equal(ui.reasonText.textContent, "motivo");

  const resume = ui.panel.dispatch("submit", { target: ui.resumeForm, preventDefault() {} });
  await flush();
  assert.equal(ui.panel.__botControl.currentSeq(), 2);
  assert.equal(ui.panel.__botControl.applyIfCurrent(1, {
    is_paused: true,
    status: "paused",
    updated_at: "2026-10-25T18:16:56+00:00",
    updated_by: "stale@example.com",
    reason: "STALE"
  }), false);
  assert.equal(ui.reasonText.textContent, "motivo");
  assert.equal(ui.updatedBy.textContent, "owner@example.com");
  assert.equal(ui.state.textContent, "Estado solicitado: pausado");

  respond(ui.queue, 1, jsonResponse({
    is_paused: false,
    status: "running",
    updated_at: "2026-10-25T18:20:00+00:00",
    updated_by: "owner@example.com",
    reason: "continuar"
  }));
  await resume;

  assert.equal(ui.state.textContent, "Estado solicitado: en ejecución");
  assert.equal(ui.reasonText.textContent, "continuar");
  assert.equal(ui.flash.textContent, "Reanudación solicitada");
  assert.equal(ui.panel.__botControl.applyIfCurrent(1, {
    is_paused: true,
    reason: "STALE",
    updated_by: "stale@example.com",
    updated_at: "2026-10-25T18:16:56+00:00"
  }), false);
  assert.equal(ui.reasonText.textContent, "continuar");
});

test("invalid pause confirmation does not send a request", async () => {
  const ui = harness();
  ui.pauseForm.reportValidity = () => false;
  const prevented = { called: false };
  await ui.panel.dispatch("submit", {
    target: ui.pauseForm,
    preventDefault() { prevented.called = true; }
  });
  assert.equal(prevented.called, true);
  assert.equal(ui.requests.length, 0);
  assert.equal(ui.pauseButton.disabled, false);
});

test("without fetch the script leaves native form submission alone", () => {
  const panel = control({ attributes: { "data-status-url": "/bot/status/" } });
  const context = {
    document: { getElementById: () => panel },
    window: { FormData: FakeFormData },
    FormData: FakeFormData,
    Intl,
    Date,
    Promise,
    Error,
    isNaN
  };
  vm.runInNewContext(source, context);
  const form = control({ classes: ["bot-control-form"], action: "/bot/stop/" });
  const prevented = { called: false };
  assert.equal(panel.listeners.submit, undefined);
  form.dispatch("submit", { preventDefault() { prevented.called = true; } });
  assert.equal(prevented.called, false);
  assert.equal(form.submitCalls, 0);
});
