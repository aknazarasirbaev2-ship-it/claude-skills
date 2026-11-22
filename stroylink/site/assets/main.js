/* StroyLink — общий скрипт сайта.
 * НАСТРОЙКА: замените номер WhatsApp ниже (только цифры, с кодом страны 7).
 * POSTHOG_KEY — необязательно: ключ проекта PostHog (phc_...), чтобы считать заявки с сайта.
 */
const CONFIG = {
  WA_NUMBER: "77000000000",          // TODO: ваш номер WhatsApp, напр. 77011234567
  POSTHOG_KEY: "",                   // TODO (необязательно): phc_...
  POSTHOG_HOST: "https://us.i.posthog.com",
};

(function () {
  "use strict";

  // ---------- Аналитика (работает, только если задан POSTHOG_KEY) ----------
  function track(event, props) {
    if (!CONFIG.POSTHOG_KEY) return;
    let id;
    try {
      id = localStorage.getItem("sl_id");
      if (!id) { id = "web-" + Math.random().toString(36).slice(2) + Date.now().toString(36); localStorage.setItem("sl_id", id); }
    } catch (e) { id = "web-anon"; }
    const body = JSON.stringify({
      api_key: CONFIG.POSTHOG_KEY,
      event: event,
      distinct_id: id,
      properties: Object.assign({ $current_url: location.href, source: "website", lang: document.documentElement.lang }, props || {}),
    });
    try {
      navigator.sendBeacon
        ? navigator.sendBeacon(CONFIG.POSTHOG_HOST + "/capture/", new Blob([body], { type: "application/json" }))
        : fetch(CONFIG.POSTHOG_HOST + "/capture/", { method: "POST", body: body, keepalive: true });
    } catch (e) { /* аналитика не должна ломать сайт */ }
  }

  function waLink(text) {
    return "https://wa.me/" + CONFIG.WA_NUMBER + (text ? "?text=" + encodeURIComponent(text) : "");
  }

  // ---------- Все ссылки WhatsApp: <a data-wa="текст сообщения"> ----------
  document.querySelectorAll("[data-wa]").forEach(function (a) {
    a.href = waLink(a.getAttribute("data-wa"));
    a.target = "_blank";
    a.rel = "noopener";
    a.addEventListener("click", function () { track("site_whatsapp_click", { place: a.getAttribute("data-place") || "" }); });
  });

  track("$pageview");

  // ---------- Квиз ----------
  const form = document.getElementById("quiz");
  if (!form) return;

  const steps = Array.prototype.slice.call(form.querySelectorAll(".step"));
  const bar = form.querySelector(".progress span");
  const counter = form.querySelector("[data-counter]");
  const btnBack = form.querySelector("[data-back]");
  const btnNext = form.querySelector("[data-next]");
  const errorBox = form.querySelector(".quiz-error");
  const tpl = function (s, n, total) { return s.replace("{n}", n).replace("{total}", total); };
  const counterText = form.getAttribute("data-counter-text") || "Шаг {n} из {total}";
  const nextText = btnNext.textContent;
  const sendText = form.getAttribute("data-send-text") || "Отправить в WhatsApp";
  let current = 0;
  let started = false;

  function show(i) {
    steps.forEach(function (s, k) { s.classList.toggle("active", k === i); });
    current = i;
    const total = steps.length;
    bar.style.width = ((i + 1) / total * 100) + "%";
    counter.textContent = tpl(counterText, i + 1, total);
    btnBack.disabled = i === 0;
    btnNext.textContent = i === total - 1 ? sendText : nextText;
    errorBox.textContent = "";
  }

  function stepValid(step) {
    const radios = step.querySelectorAll("input[type=radio]");
    if (radios.length && !step.querySelector("input[type=radio]:checked")) {
      return form.getAttribute("data-msg-choose") || "Выберите вариант";
    }
    const required = step.querySelectorAll("[required]");
    for (let i = 0; i < required.length; i++) {
      const el = required[i];
      if (el.type === "checkbox" && !el.checked) return form.getAttribute("data-msg-consent") || "Нужно согласие на передачу контактов";
      if (el.type !== "checkbox" && !el.value.trim()) return form.getAttribute("data-msg-fill") || "Заполните поле";
      if (el.type === "tel" && el.value.replace(/\D/g, "").length < 10) return form.getAttribute("data-msg-phone") || "Проверьте номер телефона";
    }
    return "";
  }

  function buildMessage() {
    const lines = [form.getAttribute("data-wa-intro") || "Здравствуйте! Заявка на подбор компании для ремонта:"];
    steps.forEach(function (step) {
      step.querySelectorAll("[data-label]").forEach(function (el) {
        let value = "";
        if (el.matches("fieldset")) {
          const checked = el.querySelector("input:checked");
          if (checked) value = checked.getAttribute("data-text") || checked.value;
        } else if (el.type === "checkbox") {
          value = el.checked ? (el.getAttribute("data-text") || "да") : "";
        } else {
          value = el.value.trim();
        }
        if (value) lines.push("• " + el.getAttribute("data-label") + ": " + value);
      });
    });
    return lines.join("\n");
  }

  form.addEventListener("change", function (e) {
    if (!started) { started = true; track("site_quiz_started"); }
    // автопереход для шагов с одним вопросом-выбором
    const step = steps[current];
    if (e.target.type === "radio" && step.querySelectorAll("fieldset").length === 1 && current < steps.length - 1) {
      setTimeout(function () { show(current + 1); }, 180);
    }
  });

  btnBack.addEventListener("click", function () { if (current > 0) show(current - 1); });

  btnNext.addEventListener("click", function () {
    const err = stepValid(steps[current]);
    if (err) { errorBox.textContent = err; return; }
    if (current < steps.length - 1) { show(current + 1); return; }
    // последний шаг: открыть WhatsApp с готовой заявкой
    const msg = buildMessage();
    track("site_lead_submitted", { type: (form.querySelector("[name=type]:checked") || {}).value || "" });
    window.open(waLink(msg), "_blank", "noopener");
    form.querySelector(".quiz-body").hidden = true;
    form.querySelector(".quiz-done").hidden = false;
    const again = form.querySelector(".quiz-done a");
    if (again) again.href = waLink(msg);
  });

  show(0);
})();
