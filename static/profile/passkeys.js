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
    try { result = await response.json(); } catch (_) { /* use a localized fallback below */ }
    if (!response.ok) throw new Error(result.detail || "operation-failed");
    return result;
  }

  const errorMessages = {
    "Too many attempts. Try again later.": "Hubo demasiados intentos. Probá de nuevo más tarde.",
    "Authentication required.": "Volvé a iniciar sesión para continuar.",
    "Re-enter your password before adding a passkey.": "Confirmá tu contraseña actual antes de agregar una passkey.",
    "Enter a passkey name of 1 to 80 characters.": "Ingresá un nombre de entre 1 y 80 caracteres.",
    "Verify with an existing passkey before adding another.": "Verificá una passkey existente antes de agregar otra.",
    "Reauthentication expired. Verify again before adding a passkey.": "La verificación venció. Confirmá de nuevo tu contraseña y tu passkey.",
    "Passkey registration could not be completed.": "No pudimos completar el registro. Intentá de nuevo.",
    "Passkey verification could not be completed.": "No pudimos verificar la passkey. Intentá de nuevo.",
    "Register your first passkey with your password.": "Confirmá tu contraseña para registrar la primera passkey.",
    "Sign-in could not be completed.": "No pudimos iniciar sesión con la passkey. Podés usar tu contraseña.",
    "Reauthentication failed.": "La contraseña no coincide. Probá de nuevo.",
    "Reauthentication could not be completed.": "No pudimos verificar la contraseña. Intentá de nuevo.",
    "operation-failed": "No pudimos completar la operación. Intentá de nuevo."
  };

  function localizedError(error, fallback) {
    return errorMessages[error.message] || fallback;
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
    if (window.PublicKeyCredential && navigator.credentials) loginButton.hidden = false;
    loginButton.addEventListener("click", async () => {
      const status = document.getElementById("passkey-login-status");
      loginButton.disabled = true;
      status.textContent = "Preparando la verificación del dispositivo…";
      try {
        const options = await post(loginButton.dataset.beginUrl, {}, true);
        const credential = await navigator.credentials.get({ publicKey: requestOptions(options) });
        if (!credential) throw new Error("Sin passkey seleccionada.");
        const completeUrl = new URL(loginButton.dataset.completeUrl, window.location.origin);
        if (loginButton.dataset.next) completeUrl.searchParams.set("next", loginButton.dataset.next);
        const result = await post(completeUrl.toString(), serializeCredential(credential, false), true);
        window.location.assign(result.redirect_url || "/dashboard/");
      } catch (error) {
        status.textContent = error.name === "NotAllowedError"
          ? "La solicitud se canceló o no está disponible. Podés iniciar sesión con tu contraseña."
          : localizedError(error, "No pudimos iniciar sesión con la passkey. Podés usar tu contraseña.");
        loginButton.disabled = false;
      }
    });
  }

  const settings = document.getElementById("passkey-settings");
  if (!settings) return;
  const status = document.getElementById("passkey-settings-status");
  const registerButton = document.getElementById("passkey-register");
  const nameInput = document.getElementById("passkey-name");
  const reauthForm = document.getElementById("passkey-reauth-form");
  const reauthPassword = document.getElementById("reauth-password");
  const deviceReauth = document.getElementById("passkey-reauth-device");
  const hasCredentials = settings.dataset.hasCredentials === "true";
  const webAuthnAvailable = Boolean(window.PublicKeyCredential && navigator.credentials);
  let passwordVerified = false;
  let passkeyVerified = !hasCredentials;

  function updateEnrollmentControls() {
    const proofsVerified = passwordVerified && passkeyVerified;
    nameInput.disabled = !proofsVerified || !webAuthnAvailable;
    registerButton.disabled = !proofsVerified || !webAuthnAvailable;
    if (deviceReauth) deviceReauth.disabled = !passwordVerified || !webAuthnAvailable;
    if (!webAuthnAvailable) {
      status.textContent = "Este navegador no permite registrar passkeys. Podés seguir usando tu contraseña.";
    }
  }

  updateEnrollmentControls();

  if (deviceReauth) {
    deviceReauth.addEventListener("click", async () => {
      deviceReauth.disabled = true;
      status.textContent = "Confirmá con Face ID, huella, el bloqueo del dispositivo o una llave de seguridad…";
      try {
        const options = await post(settings.dataset.stepUpBeginUrl, {}, true);
        const credential = await navigator.credentials.get({ publicKey: requestOptions(options) });
        if (!credential) throw new Error("Sin passkey seleccionada.");
        await post(settings.dataset.stepUpCompleteUrl, serializeCredential(credential, false), true);
        passkeyVerified = true;
        status.textContent = "Passkey verificada. Ahora elegí un nombre para la nueva passkey.";
      } catch (error) {
        passkeyVerified = false;
        status.textContent = error.name === "NotAllowedError"
          ? "La verificación se canceló o no está disponible. Podés intentarlo de nuevo."
          : localizedError(error, "No pudimos verificar la passkey. Intentá de nuevo.");
      } finally {
        updateEnrollmentControls();
      }
    });
  }

  reauthForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submitButton = reauthForm.querySelector("button[type=submit]");
    submitButton.disabled = true;
    status.textContent = "Verificando tu contraseña…";
    try {
      await post(settings.dataset.reauthUrl, { password: reauthPassword.value }, false);
      passwordVerified = true;
      reauthPassword.value = "";
      status.textContent = hasCredentials
        ? "Contraseña confirmada. Ahora verificá una passkey existente."
        : "Contraseña confirmada. Ahora elegí un nombre para tu passkey.";
    } catch (error) {
      status.textContent = localizedError(error, "No pudimos verificar la contraseña. Intentá de nuevo.");
    } finally {
      submitButton.disabled = false;
      updateEnrollmentControls();
    }
  });

  registerButton.addEventListener("click", async () => {
    if (!nameInput.value.trim()) {
      nameInput.reportValidity();
      return;
    }
    registerButton.disabled = true;
    status.textContent = "Seguí las indicaciones de tu dispositivo para registrar la passkey…";
    try {
      const name = nameInput.value.trim();
      const options = await post(settings.dataset.registerBeginUrl, { name }, false);
      // The server consumes both one-use proofs when registration begins.
      passwordVerified = false;
      passkeyVerified = !hasCredentials;
      const credential = await navigator.credentials.create({ publicKey: creationOptions(options) });
      if (!credential) throw new Error("No se creó la passkey.");
      await post(settings.dataset.registerCompleteUrl, serializeCredential(credential, true), true);
      status.textContent = "Passkey registrada correctamente.";
      window.setTimeout(() => window.location.reload(), 2000);
    } catch (error) {
      passwordVerified = false;
      passkeyVerified = !hasCredentials;
      const message = error.name === "NotAllowedError"
        ? "El registro se canceló."
        : localizedError(error, "No pudimos completar el registro.");
      const retryGuidance = hasCredentials
        ? "Volvé a confirmar tu contraseña y una passkey antes de intentarlo otra vez."
        : "Volvé a confirmar tu contraseña antes de intentarlo otra vez.";
      status.textContent = `${message} ${retryGuidance}`;
    } finally {
      updateEnrollmentControls();
    }
  });
})();
