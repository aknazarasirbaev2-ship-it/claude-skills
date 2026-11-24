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

  // ---------- Два пути: «Ищу сам / Через StroyLink» ----------
  // Без JS оба списка видны друг под другом. С JS — переключатель (мышь, палец, Tab + Enter/пробел, стрелки).
  var vs = document.querySelector(".vs");
  if (vs) {
    var vsOpts = vs.querySelectorAll(".vs-opt");
    var vsPanels = vs.querySelectorAll(".vs-panel");
    var vsLive = vs.querySelector("[data-vs-live]");
    var vsState = vs.getAttribute("data-state") || "self";
    var vsTl = null;
    var vsTouched = false;
    var vsPanel = function (side) { return vs.querySelector('.vs-panel[data-side="' + side + '"]'); };
    var vsSync = function () {
      vsOpts.forEach(function (b) { b.setAttribute("aria-pressed", b.getAttribute("data-side") === vsState ? "true" : "false"); });
      vsPanels.forEach(function (p) {
        var on = p.getAttribute("data-side") === vsState;
        p.classList.toggle("on", on);
        p.setAttribute("aria-hidden", on ? "false" : "true");
      });
    };
    var vsPlay = function (side) {
      if (!animate) return;
      var p = vsPanel(side);
      if (!p) return;
      var its = p.querySelectorAll(".vs-item");
      var route = p.querySelector(".vs-route path");
      if (vsTl) vsTl.progress(1).kill();
      vsTl = gsap.timeline();
      if (route) vsTl.fromTo(route, { strokeDashoffset: 1 }, { strokeDashoffset: 0, duration: side === "self" ? 1.2 : .55, ease: side === "self" ? "power1.inOut" : "power3.out" }, 0);
      if (side === "self") {
        // «запутанный» путь: карточки падают вразнобой
        vsTl.fromTo(its, { y: -34, opacity: 0, rotation: function () { return gsap.utils.random(-9, 9); } },
          { y: 0, opacity: 1, rotation: 0, duration: .6, stagger: .09, ease: "back.out(2.2)" }, .05);
      } else {
        // прямой путь: карточки ровно встают одна за другой, галочки «щёлкают»
        vsTl.fromTo(its, { x: 46, opacity: 0 }, { x: 0, opacity: 1, duration: .5, stagger: .07, ease: "power3.out" }, .05);
        vsTl.fromTo(p.querySelectorAll(".vs-ico"), { scale: 0 }, { scale: 1, duration: .45, stagger: .07, ease: "back.out(3)" }, .2);
      }
      vsTl.fromTo(vs.querySelectorAll(".vs-stats dd, .vs-meter-top b, .vs-verdict"), { rotationX: -80, opacity: 0, transformPerspective: 400 },
        { rotationX: 0, opacity: 1, duration: .5, stagger: .06, ease: "power2.out" }, 0);
    };
    var vsSet = function (side, byUser) {
      if (byUser) {
        vsTouched = true;
        vs.querySelectorAll(".vs-opt.nudge").forEach(function (b) { b.classList.remove("nudge"); });
      }
      if (side === vsState) return;
      vsState = side;
      vs.setAttribute("data-state", side);
      vsSync();
      if (vsLive) vsLive.textContent = side === "link"
        ? (vsLive.getAttribute("data-live-link") || "Показан путь через StroyLink")
        : (vsLive.getAttribute("data-live-self") || "Показан путь, если искать самому");
      vsPlay(side);
    };
    vsOpts.forEach(function (b) {
      b.addEventListener("click", function () { vsSet(b.getAttribute("data-side"), true); });
      b.addEventListener("keydown", function (e) {
        if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
        e.preventDefault();
        var next = e.key === "ArrowRight" ? "link" : "self";
        vsSet(next, true);
        vs.querySelector('.vs-opt[data-side="' + next + '"]').focus();
      });
    });
    // подпись-подсказка «Нажмите» задана в CSS; на других языках берём текст из data-nudge-text
    var vsNudgeText = vs.getAttribute("data-nudge-text");
    if (vsNudgeText) {
      var vsNudgeCss = document.createElement("style");
      vsNudgeCss.textContent = ".vs-opt.nudge::before{content:" + JSON.stringify(vsNudgeText) + "}";
      document.head.appendChild(vsNudgeCss);
    }
    vs.classList.add("is-ready");
    vsSync();
    if ("IntersectionObserver" in window) {
      var vsStage = vs.querySelector(".vs-stage");
      if (animate && vsState === "self") gsap.set(vsPanel("self").querySelectorAll(".vs-item"), { opacity: 0 });
      var vsIo = new IntersectionObserver(function (en) {
        if (!en[0].isIntersecting) return;
        vsIo.disconnect();
        if (vsState === "self") vsPlay("self");
        // подсказка: «нажмите» на второй вариант, если человек сам не попробовал
        setTimeout(function () {
          if (!vsTouched && vsState === "self") { var l = vs.querySelector('.vs-opt[data-side="link"]'); if (l) l.classList.add("nudge"); }
        }, 2000);
      }, { threshold: .15 });
      vsIo.observe(vsStage);
    }
  }

  // ---------- Мини-кнопка заявки: после блока «Почему через нас», прячется у формы и внизу ----------
  var mini = document.querySelector(".mini-cta");
  var benefits = document.getElementById("vygoda");
  if (mini && benefits) {
    var miniZones = [document.getElementById("zayavka"), document.querySelector(".big-cta"), document.querySelector(".site-footer")].filter(Boolean);
    var miniTick = false;
    var miniUpd = function () {
      miniTick = false;
      var vh = window.innerHeight;
      var past = benefits.getBoundingClientRect().bottom < vh * .5;
      var inZone = miniZones.some(function (z) { var r = z.getBoundingClientRect(); return r.top < vh && r.bottom > 0; });
      mini.classList.toggle("show", past && !inZone);
    };
    window.addEventListener("scroll", function () { if (!miniTick) { miniTick = true; requestAnimationFrame(miniUpd); } }, { passive: true });
    window.addEventListener("resize", miniUpd);
    miniUpd();
  }

  // ---------- Путь заявки на телефоне: полоска показывает, сколько карточек пролистано ----------
  var pathVp = document.querySelector(".path-viewport");
  var pathBar = document.querySelector(".path-bar span");
  if (pathVp && pathBar) {
    pathVp.addEventListener("scroll", function () {
      if (window.innerWidth >= 900) return;
      var m = pathVp.scrollWidth - pathVp.clientWidth;
      pathBar.style.transform = "scaleX(" + (m > 0 ? pathVp.scrollLeft / m : 0) + ")";
    }, { passive: true });
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
    var pathTween = gsap.to(track, {
      x: function () { return -dist(); },
      ease: "none",
      scrollTrigger: { trigger: ".path", start: "top top", end: function () { return "+=" + dist(); }, pin: true, scrub: .6, invalidateOnRefresh: true, anticipatePin: 1 },
    });
    gsap.to(".path-bar span", { scaleX: 1, ease: "none", scrollTrigger: { trigger: ".path", start: "top top", end: function () { return "+=" + dist(); }, scrub: .6 } });
    // большие цифры на карточках плывут медленнее карточек — глубина при прокрутке
    gsap.utils.toArray(".path-card .num").forEach(function (n) {
      gsap.fromTo(n, { xPercent: 24 }, { xPercent: -12, ease: "none", scrollTrigger: { trigger: n.parentNode, containerAnimation: pathTween, start: "left right", end: "right left", scrub: true } });
    });
  });

  // ---------- Большой CTA: слова собираются ----------
  gsap.from(".big-cta h2 .w", { yPercent: 100, opacity: 0, stagger: .08, duration: .9, ease: "power4.out", scrollTrigger: { trigger: ".big-cta", start: "top 70%", once: true } });
  gsap.fromTo(".wordmark", { xPercent: -8 }, { xPercent: 4, ease: "none", scrollTrigger: { trigger: ".site-footer", start: "top bottom", end: "bottom bottom", scrub: true } });

  window.addEventListener("load", function () { ScrollTrigger.refresh(); });
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () { ScrollTrigger.refresh(); });
})();
