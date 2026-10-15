(function () {
  "use strict";

  function bytesFromBase64Url(value) {
    const padded = value.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((value.length + 3) % 4);
    const binary = atob(padded);
    return Uint8Array.from(binary, (character) => character.charCodeAt(0));
  }

  function base64UrlFromBytes(value) {
    const bytes = new Uint8Array(value);
    let binary = "";
    for (const byte of bytes) binary += String.fromCharCode(byte);
    return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
  }

  function csrfToken() {
    return document.querySelector("[name=csrfmiddlewaretoken]")?.value ||
      document.cookie.split(";").map((part) => part.trim()).find((part) => part.startsWith("csrftoken="))?.split("=").slice(1).join("=") || "";
  }

  async function post(url, data, json) {
    const headers = { "X-CSRFToken": csrfToken() };
    if (json) headers["Content-Type"] = "application/json";
    const response = await fetch(url, {
      method: "POST", credentials: "same-origin", headers,
      body: json ? JSON.stringify(data) : new URLSearchParams(data)
    });
    let result = {};
    try { result = await response.json(); } catch (_) { /* controlled fallback below */ }
    if (!response.ok) throw new Error(result.detail || "The passkey operation could not be completed.");
    return result;
  }

  function serializeCredential(credential, registering) {
    const response = credential.response;
    const payload = {
      id: credential.id,
      rawId: base64UrlFromBytes(credential.rawId),
      type: credential.type,
      response: {
        clientDataJSON: base64UrlFromBytes(response.clientDataJSON)
      },
      clientExtensionResults: credential.getClientExtensionResults()
    };
    if (registering) {
      payload.response.attestationObject = base64UrlFromBytes(response.attestationObject);
      if (typeof response.getTransports === "function") payload.response.transports = response.getTransports();
    } else {
      payload.response.authenticatorData = base64UrlFromBytes(response.authenticatorData);
      payload.response.signature = base64UrlFromBytes(response.signature);
      payload.response.userHandle = response.userHandle ? base64UrlFromBytes(response.userHandle) : null;
    }
    return payload;
  }

  function requestOptions(options) {
    const converted = { ...options, challenge: bytesFromBase64Url(options.challenge) };
    if (options.allowCredentials) {
      converted.allowCredentials = options.allowCredentials.map((item) => ({ ...item, id: bytesFromBase64Url(item.id) }));
    }
    return converted;
  }

  function creationOptions(options) {
    const publicKey = requestOptions(options);
    publicKey.user = { ...options.user, id: bytesFromBase64Url(options.user.id) };
    if (options.excludeCredentials) {
      publicKey.excludeCredentials = options.excludeCredentials.map((item) => ({ ...item, id: bytesFromBase64Url(item.id) }));
    }
    return publicKey;
  }

  const loginButton = document.getElementById("passkey-login");
  if (loginButton) {
    if (window.PublicKeyCredential) loginButton.hidden = false;
    loginButton.addEventListener("click", async () => {
      const status = document.getElementById("passkey-login-status");
      loginButton.disabled = true;
      status.textContent = "Waiting for your authenticator…";
      try {
        const options = await post(loginButton.dataset.beginUrl, {}, true);
        const credential = await navigator.credentials.get({ publicKey: requestOptions(options) });
        if (!credential) throw new Error("No passkey was selected.");
        const completeUrl = new URL(loginButton.dataset.completeUrl, window.location.origin);
        if (loginButton.dataset.next) completeUrl.searchParams.set("next", loginButton.dataset.next);
        const result = await post(completeUrl.toString(), serializeCredential(credential, false), true);
        window.location.assign(result.redirect_url || "/dashboard/");
      } catch (error) {
        status.textContent = error.name === "NotAllowedError" ? "Passkey sign-in was cancelled or unavailable. You can use your password instead." : error.message;
        loginButton.disabled = false;
      }
    });
  }

  const settings = document.getElementById("passkey-settings");
  if (!settings) return;
  const status = document.getElementById("passkey-settings-status");
  const registerButton = document.getElementById("passkey-register");
  if (window.PublicKeyCredential) registerButton.disabled = false;
  const deviceReauth = document.getElementById("passkey-reauth-device");
  if (deviceReauth) {
    deviceReauth.addEventListener("click", async () => {
      deviceReauth.disabled = true;
      status.textContent = "Verify with one of your registered passkeys…";
      try {
        const options = await post(settings.dataset.authBeginUrl, {}, true);
        const credential = await navigator.credentials.get({ publicKey: requestOptions(options) });
        if (!credential) throw new Error("No passkey was selected.");
        await post(settings.dataset.authCompleteUrl, serializeCredential(credential, false), true);
        status.textContent = "Passkey verified. Enter your current password to authorize enrollment.";
      } catch (error) { status.textContent = error.message; }
      finally { deviceReauth.disabled = false; }
    });
  }
  document.getElementById("passkey-reauth-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const password = document.getElementById("reauth-password").value;
    try {
      await post(settings.dataset.reauthUrl, { password }, false);
      status.textContent = "Password verified. You can register one passkey in the next five minutes.";
      document.getElementById("reauth-password").value = "";
    } catch (error) { status.textContent = error.message; }
  });
  document.getElementById("passkey-register-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    registerButton.disabled = true;
    status.textContent = "Waiting for your authenticator…";
    try {
      const name = document.getElementById("passkey-name").value.trim();
      const options = await post(settings.dataset.registerBeginUrl, { name }, false);
      const credential = await navigator.credentials.create({ publicKey: creationOptions(options) });
      if (!credential) throw new Error("No passkey was created.");
      await post(settings.dataset.registerCompleteUrl, serializeCredential(credential, true), true);
      status.textContent = "Passkey registered.";
      window.location.reload();
    } catch (error) { status.textContent = error.name === "NotAllowedError" ? "Passkey registration was cancelled or unavailable." : error.message; }
    finally { registerButton.disabled = !window.PublicKeyCredential; }
  });
})();
