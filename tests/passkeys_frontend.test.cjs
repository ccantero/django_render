const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../static/profile/passkeys.js"), "utf8");

function element() {
  const listeners = {};
  return {
    dataset: {},
    disabled: false,
    hidden: false,
    value: "",
    textContent: "",
    customValidity: "",
    addEventListener(type, callback) { listeners[type] = callback; },
    async dispatch(type, event = {}) { return listeners[type]({ preventDefault() {}, ...event }); },
    querySelector() { return submitButton; },
    setCustomValidity(message) { this.customValidity = message; },
    reportValidity() { this.reportedValidity = true; return !this.customValidity; }
  };
}

let submitButton;
function setup({ hasCredentials = true, fetchResults = [] } = {}) {
  const ids = [
    "passkey-settings", "passkey-settings-status", "passkey-register", "passkey-name",
    "passkey-reauth-form", "reauth-password", "passkey-reauth-device"
  ];
  const elements = Object.fromEntries(ids.map((id) => [id, element()]));
  submitButton = element();
  elements["passkey-settings"].dataset = {
    hasCredentials: String(hasCredentials),
    reauthUrl: "/reauth/",
    stepUpBeginUrl: "/step-up/begin/",
    stepUpCompleteUrl: "/step-up/complete/",
    registerBeginUrl: "/register/begin/",
    registerCompleteUrl: "/register/complete/"
  };
  const requests = [];
  const context = {
    atob: (value) => Buffer.from(value, "base64").toString("binary"),
    btoa: (value) => Buffer.from(value, "binary").toString("base64"),
    Buffer,
    Uint8Array,
    URL,
    URLSearchParams,
    setTimeout,
    document: {
      getElementById: (id) => elements[id] || null,
      querySelector: () => null,
      cookie: ""
    },
    window: { PublicKeyCredential: function PublicKeyCredential() {}, location: { origin: "https://example.test" } },
    navigator: { credentials: { get: async () => ({
      id: "credential",
      rawId: new Uint8Array([1]).buffer,
      type: "public-key",
      response: {
        clientDataJSON: new Uint8Array([1]).buffer,
        authenticatorData: new Uint8Array([1]).buffer,
        signature: new Uint8Array([1]).buffer,
        userHandle: null
      },
      getClientExtensionResults: () => ({})
    }), create: async () => ({}) } },
    fetch: async (url, options) => {
      requests.push({ url, options });
      const result = fetchResults.shift() || { ok: true, body: {} };
      return { ok: result.ok, json: async () => result.body };
    }
  };
  vm.runInNewContext(source, context);
  return { elements, requests };
}

const ok = { ok: true, body: {} };
const stepUpOptions = { ok: true, body: { challenge: "AQ" } };
const failure = { ok: false, body: { detail: "Reauthentication failed." } };

test("failed reauthentication clears prior password and passkey proof state", async () => {
  const { elements } = setup({ hasCredentials: true, fetchResults: [ok, stepUpOptions, ok, failure] });
  const form = elements["passkey-reauth-form"];
  await form.dispatch("submit");
  assert.equal(elements["passkey-reauth-device"].disabled, false);
  await elements["passkey-reauth-device"].dispatch("click");
  assert.equal(elements["passkey-register"].disabled, false);

  await form.dispatch("submit");

  assert.equal(elements["passkey-name"].disabled, true);
  assert.equal(elements["passkey-register"].disabled, true);
  assert.equal(elements["passkey-reauth-device"].disabled, true);
  assert.match(elements["passkey-settings-status"].textContent, /contraseña/i);
});

test("whitespace-only credential names show an error and never start registration", async () => {
  const { elements, requests } = setup({ hasCredentials: false, fetchResults: [ok] });
  await elements["passkey-reauth-form"].dispatch("submit");
  const nameInput = elements["passkey-name"];
  nameInput.value = "   \t  ";

  await elements["passkey-register"].dispatch("click");

  assert.equal(nameInput.value, "");
  assert.match(nameInput.customValidity, /nombre/i);
  assert.equal(nameInput.reportedValidity, true);
  assert.equal(requests.length, 1, "only password reauthentication should be sent");
  assert.match(elements["passkey-settings-status"].textContent, /nombre/i);
});

test("credential names are trimmed in the field and submitted consistently", async () => {
  const { elements, requests } = setup({ hasCredentials: false, fetchResults: [ok, ok] });
  await elements["passkey-reauth-form"].dispatch("submit");
  const nameInput = elements["passkey-name"];
  nameInput.value = "  Llave del iPhone  ";

  await elements["passkey-register"].dispatch("click");

  assert.equal(nameInput.value, "Llave del iPhone");
  assert.equal(requests[1].options.body.get("name"), "Llave del iPhone");
});
