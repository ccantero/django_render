(function () {
  if (!window.fetch || !window.FormData) {
    return;
  }

  var panel = document.getElementById("control-seguro");
  if (!panel) {
    return;
  }

  var requestSeq = 0;
  var inFlight = false;
  var lastForm = null;
  var statusUrl = panel.getAttribute("data-status-url") || "/bot/status/";
  var UNCERTAIN_MESSAGE = "Resultado incierto. No se reenvió el pedido.";

  function controls() {
    return panel.querySelectorAll("input, button, textarea, select");
  }

  function setDisabled(disabled) {
    var nodes = controls();
    for (var i = 0; i < nodes.length; i += 1) {
      nodes[i].disabled = disabled;
    }
  }

  function showFlash(text, kind) {
    var flash = panel.querySelector("[data-bot-control-flash]");
    if (!flash) {
      return;
    }
    flash.textContent = text;
    flash.className = "alert alert-" + (kind === "success" ? "success" : "warning") + " py-2 mt-2 mb-3";
  }

  function formatArt(iso) {
    if (!iso) {
      return "sin registro";
    }
    var date = new Date(iso);
    if (isNaN(date.getTime())) {
      return iso;
    }
    var zones = ["America/Buenos_Aires", "America/Argentina/Buenos_Aires"];
    for (var z = 0; z < zones.length; z += 1) {
      try {
        var parts = new Intl.DateTimeFormat("en-GB", {
          timeZone: zones[z],
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
          hourCycle: "h23"
        }).formatToParts(date);
        function value(type) {
          for (var i = 0; i < parts.length; i += 1) {
            if (parts[i].type === type) {
              return parts[i].value;
            }
          }
          return "";
        }
        return value("day") + "/" + value("month") + "/" + value("year") + " " + value("hour") + ":" + value("minute") + " ART";
      } catch (error) {}
    }
    var shifted = new Date(date.getTime() - (3 * 60 * 60 * 1000));
    function pad(number) {
      return (number < 10 ? "0" : "") + number;
    }
    return pad(shifted.getUTCDate()) + "/" + pad(shifted.getUTCMonth() + 1) + "/" + shifted.getUTCFullYear() + " " + pad(shifted.getUTCHours()) + ":" + pad(shifted.getUTCMinutes()) + " ART";
  }

  function applyIfCurrent(seq, payload) {
    if (seq !== requestSeq || !payload) {
      return false;
    }
    var paused = payload.is_paused === true;
    var state = panel.querySelector("[data-bot-control-state]");
    if (state) {
      state.textContent = "Estado solicitado: " + (paused ? "pausado" : "en ejecución");
      state.setAttribute("data-status", paused ? "paused" : "running");
    }
    var when = panel.querySelector("[data-bot-control-updated]");
    if (when) {
      when.textContent = formatArt(payload.updated_at);
      if (payload.updated_at) {
        when.setAttribute("datetime", payload.updated_at);
      }
    }
    var who = panel.querySelector("[data-bot-control-updated-by]");
    if (who) {
      who.textContent = payload.updated_by || "—";
    }
    var reason = panel.querySelector("[data-bot-control-reason]");
    if (reason) {
      reason.textContent = payload.reason || "—";
    }
    return true;
  }

  function successMessage(form) {
    return form.getAttribute("data-bot-control-action") === "resume"
      ? "Reanudación solicitada"
      : "Pausa solicitada";
  }

  function finish(seq, uncertain) {
    if (seq !== requestSeq) {
      return;
    }
    inFlight = false;
    setDisabled(false);
    var retry = panel.querySelector("[data-bot-control-retry]");
    if (retry) {
      retry.hidden = !uncertain;
      retry.disabled = false;
    }
  }

  function refreshStatus(seq) {
    return fetch(statusUrl, {
      method: "GET",
      credentials: "same-origin",
      headers: { "Accept": "application/json" }
    }).then(function (response) {
      var type = (response.headers && response.headers.get("Content-Type")) || "";
      if (!response.ok || type.indexOf("application/json") === -1) {
        throw new Error("status-unread");
      }
      return response.json();
    }).then(function (payload) {
      if (seq !== requestSeq) {
        return;
      }
      applyIfCurrent(seq, payload);
      showFlash(UNCERTAIN_MESSAGE, "warning");
    }).catch(function () {
      if (seq !== requestSeq) {
        return;
      }
      showFlash(UNCERTAIN_MESSAGE + " No se pudo volver a leer el estado guardado.", "warning");
    });
  }

  function send(form) {
    if (inFlight || !form) {
      return Promise.resolve();
    }
    inFlight = true;
    var seq = ++requestSeq;
    lastForm = form;
    var data = new FormData(form);
    var uncertain = false;
    setDisabled(true);
    var retry = panel.querySelector("[data-bot-control-retry]");
    if (retry) {
      retry.hidden = true;
    }
    return fetch(form.action, {
      method: "POST",
      body: data,
      credentials: "same-origin",
      headers: {
        "Accept": "application/json",
        "X-CSRFToken": data.get("csrfmiddlewaretoken") || ""
      }
    }).then(function (response) {
      var type = (response.headers && response.headers.get("Content-Type")) || "";
      if (!response.ok || type.indexOf("application/json") === -1) {
        throw new Error("uncertain");
      }
      return response.json();
    }).then(function (payload) {
      if (!applyIfCurrent(seq, payload)) {
        return;
      }
      showFlash(successMessage(form), "success");
    }).catch(function () {
      if (seq !== requestSeq) {
        return;
      }
      uncertain = true;
      showFlash(UNCERTAIN_MESSAGE, "warning");
      return refreshStatus(seq);
    }).then(function () {
      finish(seq, uncertain);
    });
  }

  panel.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form || !form.classList || !form.classList.contains("bot-control-form")) {
      return;
    }
    event.preventDefault();
    if (typeof form.reportValidity === "function" && !form.reportValidity()) {
      return;
    }
    if (inFlight) {
      return;
    }
    return send(form);
  });

  var retryButton = panel.querySelector("[data-bot-control-retry]");
  if (retryButton) {
    retryButton.addEventListener("click", function () {
      if (inFlight || !lastForm) {
        return;
      }
      return send(lastForm);
    });
  }

  panel.__botControl = {
    applyIfCurrent: applyIfCurrent,
    currentSeq: function () { return requestSeq; }
  };
})();
