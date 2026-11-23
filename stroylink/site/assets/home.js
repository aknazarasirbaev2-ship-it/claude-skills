/* StroyLink — анимации главной страницы (GSAP + ScrollTrigger).
   Если библиотека не загрузилась или включено «уменьшить движение», страница работает без анимаций. */
(function () {
  "use strict";
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var hasGsap = typeof window.gsap !== "undefined" && typeof window.ScrollTrigger !== "undefined";
  var animate = hasGsap && !reduce;
  var root = document.documentElement;
  if (animate) { root.classList.add("js-anim"); gsap.registerPlugin(ScrollTrigger); }

  // ---------- Шапка: фон при прокрутке, прячется при скролле вниз ----------
  var header = document.querySelector(".site-header");
  var bar = document.querySelector(".progress-top");
  var lastY = 0;
  function onScroll() {
    var y = window.scrollY;
    header.classList.toggle("scrolled", y > 40);
    header.classList.toggle("hide", y > 500 && y > lastY + 4);
    if (y < lastY - 4 || y < 500) header.classList.remove("hide");
    lastY = y;
    if (bar) {
      var max = document.documentElement.scrollHeight - window.innerHeight;
      bar.style.transform = "scaleX(" + (max > 0 ? y / max : 0) + ")";
    }
  }
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  // ---------- До / после ----------
  var ba = document.querySelector(".ba");
  if (ba) {
    var knob = ba.querySelector(".ba-knob");
    var hint = document.querySelector(".drag-hint");
    var dragging = false;
    var setPos = function (p) { p = Math.max(2, Math.min(98, p)); ba.style.setProperty("--pos", p + "%"); knob.setAttribute("aria-valuenow", Math.round(p)); };
    var fromEvent = function (e) { var r = ba.getBoundingClientRect(); return (e.clientX - r.left) / r.width * 100; };
    var touched = function () { ba.classList.add("touched"); if (hint) hint.style.opacity = "0"; };
    ba.addEventListener("pointerdown", function (e) {
      if (e.target.closest("a, button:not(.ba-knob)")) return;
      dragging = true; touched(); setPos(fromEvent(e));
      try { ba.setPointerCapture(e.pointerId); } catch (err) {}
    });
    ba.addEventListener("pointermove", function (e) { if (dragging) setPos(fromEvent(e)); });
    ["pointerup", "pointercancel"].forEach(function (t) { ba.addEventListener(t, function () { dragging = false; }); });
    knob.addEventListener("keydown", function (e) {
      var cur = parseFloat(getComputedStyle(ba).getPropertyValue("--pos")) || 50;
      if (e.key === "ArrowLeft") { setPos(cur - 5); touched(); e.preventDefault(); }
      if (e.key === "ArrowRight") { setPos(cur + 5); touched(); e.preventDefault(); }
    });
    if (animate) {
      // интро: от «черновой» к «после ремонта»
      var o = { p: 98 };
      setPos(98);
      gsap.to(o, { p: 50, duration: 2.2, delay: .5, ease: "power3.inOut", onUpdate: function () { if (!ba.classList.contains("touched")) setPos(o.p); } });
    }
  }

  // ---------- Вкладки «7 вопросов / 6 флагов» ----------
  document.querySelectorAll("[role=tablist]").forEach(function (list) {
    var tabs = list.querySelectorAll("[role=tab]");
    tabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        tabs.forEach(function (t) {
          var on = t === tab;
          t.setAttribute("aria-selected", on);
          var panel = document.getElementById(t.getAttribute("aria-controls"));
          panel.hidden = !on;
          if (on && animate) gsap.fromTo(panel.querySelectorAll("li"), { y: 30, opacity: 0 }, { y: 0, opacity: 1, stagger: .06, duration: .5, ease: "power3.out" });
        });
      });
    });
  });

  // ---------- FAQ: плавное раскрытие ----------
  document.querySelectorAll(".faq details").forEach(function (d) {
    var summary = d.querySelector("summary");
    var body = d.querySelector(".faq-body");
    if (!body || !animate) return;
    summary.addEventListener("click", function (e) {
      e.preventDefault();
      if (d.open) {
        gsap.to(body, { height: 0, duration: .35, ease: "power2.inOut", onComplete: function () { d.open = false; body.style.height = ""; } });
      } else {
        d.open = true;
        gsap.fromTo(body, { height: 0 }, { height: "auto", duration: .45, ease: "power2.out" });
      }
    });
  });

  // ---------- Этапы ремонта: смена фото при прокрутке ----------
  var items = document.querySelectorAll(".scope-item");
  var imgs = document.querySelectorAll(".scope-media img");
  var counter = document.querySelector(".scope-counter b");
  var counterName = document.querySelector(".scope-counter span");
  if (items.length && "IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        var i = Array.prototype.indexOf.call(items, en.target);
        items.forEach(function (it, k) { it.classList.toggle("on", k === i); });
        imgs.forEach(function (im, k) { im.classList.toggle("on", k === i); });
        if (counter) counter.textContent = "0" + (i + 1);
        if (counterName) counterName.textContent = en.target.querySelector("h3").textContent;
      });
    }, { rootMargin: "-45% 0px -45% 0px" });
    items.forEach(function (it) { io.observe(it); });
  } else {
    items.forEach(function (it) { it.classList.add("on"); });
  }

  // ---------- Курсор (только мышь) ----------
  var cursor = document.querySelector(".cursor");
  if (cursor && animate && window.matchMedia("(hover: hover) and (pointer: fine)").matches) {
    var cx = gsap.quickTo(cursor, "x", { duration: .25, ease: "power3" });
    var cy = gsap.quickTo(cursor, "y", { duration: .25, ease: "power3" });
    window.addEventListener("pointermove", function (e) { cx(e.clientX); cy(e.clientY); });
    document.querySelectorAll("a, button, .ba, label.option").forEach(function (el) {
      el.addEventListener("pointerenter", function () { cursor.classList.add("big"); });
      el.addEventListener("pointerleave", function () { cursor.classList.remove("big"); });
    });
    // «магнитные» кнопки
    document.querySelectorAll(".magnetic").forEach(function (btn) {
      btn.addEventListener("pointermove", function (e) {
        var r = btn.getBoundingClientRect();
        gsap.to(btn, { x: (e.clientX - r.left - r.width / 2) * .25, y: (e.clientY - r.top - r.height / 2) * .35, duration: .3 });
      });
      btn.addEventListener("pointerleave", function () { gsap.to(btn, { x: 0, y: 0, duration: .5, ease: "elastic.out(1, .4)" }); });
    });
  } else if (cursor) {
    cursor.remove();
  }

  if (!animate) return;

  // ---------- Заголовок первого экрана ----------
  gsap.from(".hero-x .line > span", { yPercent: 110, duration: 1.1, stagger: .09, ease: "power4.out", delay: .15 });
  gsap.from(".hero-x .lead, .hero-x .hero-cta, .hero-meta", { y: 24, opacity: 0, duration: .9, stagger: .1, delay: .6, ease: "power3.out" });

  // ---------- Появление блоков ----------
  ScrollTrigger.batch(".rv", {
    start: "top 88%",
    once: true,
    onEnter: function (els) { gsap.to(els, { opacity: 1, y: 0, duration: 1, stagger: .1, ease: "power3.out" }); },
  });
  gsap.utils.toArray(".rv-img").forEach(function (el) {
    gsap.to(el, { clipPath: "inset(0% 0% 0% 0% round 26px)", duration: 1.3, ease: "power3.out", scrollTrigger: { trigger: el, start: "top 85%", once: true } });
    var img = el.querySelector("img");
    if (img) gsap.fromTo(img, { yPercent: -6, scale: 1.12 }, { yPercent: 6, scale: 1.12, ease: "none", scrollTrigger: { trigger: el, start: "top bottom", end: "bottom top", scrub: true } });
  });

  // ---------- Горизонтальный путь заявки (закрепляется на десктопе) ----------
  var mm = gsap.matchMedia();
  mm.add("(min-width: 900px)", function () {
    var track = document.querySelector(".path-track");
    var vp = document.querySelector(".path-viewport");
    if (!track) return;
    var dist = function () { return Math.max(0, track.scrollWidth - vp.clientWidth); };
    gsap.to(track, {
      x: function () { return -dist(); },
      ease: "none",
      scrollTrigger: { trigger: ".path", start: "top top", end: function () { return "+=" + dist(); }, pin: true, scrub: .6, invalidateOnRefresh: true, anticipatePin: 1 },
    });
    gsap.to(".path-bar span", { scaleX: 1, ease: "none", scrollTrigger: { trigger: ".path", start: "top top", end: function () { return "+=" + dist(); }, scrub: .6 } });
  });

  // ---------- Большой CTA: слова собираются ----------
  gsap.from(".big-cta h2 .w", { yPercent: 100, opacity: 0, stagger: .08, duration: .9, ease: "power4.out", scrollTrigger: { trigger: ".big-cta", start: "top 70%", once: true } });
  gsap.fromTo(".wordmark", { xPercent: -8 }, { xPercent: 4, ease: "none", scrollTrigger: { trigger: ".site-footer", start: "top bottom", end: "bottom bottom", scrub: true } });

  window.addEventListener("load", function () { ScrollTrigger.refresh(); });
})();
