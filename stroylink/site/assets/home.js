/* StroyLink — анимации главной страницы.
   Принципы:
   • Контент никогда не прячется «навсегда»: всё, что скрыто до появления, скрыто только классом,
     который ставит этот скрипт, и только если браузер умеет показать это обратно (IntersectionObserver + WAAPI).
   • Появления, слайдер «до/после», вкладки, FAQ работают без GSAP. GSAP нужен только для
     закреплённого горизонтального «пути», параллакса и курсора; если CDN не загрузился — этих эффектов просто нет.
   • «Уменьшить движение» — без перемещений; действия с клавиатуры — без анимации. */
(function () {
  "use strict";
  var root = document.documentElement;
  var mq = function (q) { return !!(window.matchMedia && window.matchMedia(q).matches); };
  var reduce = mq("(prefers-reduced-motion: reduce)");
  var finePointer = mq("(hover: hover) and (pointer: fine)");
  var hasGsap = typeof window.gsap !== "undefined" && typeof window.ScrollTrigger !== "undefined";
  var gsapOn = hasGsap && !reduce;
  var canAnimate = !reduce && typeof Element.prototype.animate === "function";
  var hasIO = "IntersectionObserver" in window;
  var EASE_OUT = "cubic-bezier(0.23, 1, 0.32, 1)";
  var EASE_IN_OUT = "cubic-bezier(0.77, 0, 0.175, 1)";
  var each = function (list, fn) { Array.prototype.forEach.call(list, fn); };
  // одна ошибка в одном блоке не должна ломать остальные (и не должна оставить контент скрытым)
  var safe = function (name, fn) { try { fn(); } catch (err) { if (window.console) console.warn("[home] " + name, err); } };
  if (gsapOn) { try { gsap.registerPlugin(ScrollTrigger); } catch (err) { gsapOn = false; } }

  // ---------- Шапка: фон при прокрутке, прячется при скролле вниз; полоска прогресса ----------
  safe("header", function () {
    var header = document.querySelector(".site-header");
    var bar = document.querySelector(".progress-top");
    var lastY = window.scrollY, maxScroll = 1, ticking = false;
    var measure = function () { maxScroll = Math.max(1, root.scrollHeight - window.innerHeight); };
    var update = function () {
      ticking = false;
      var y = window.scrollY;
      if (header) {
        header.classList.toggle("scrolled", y > 40);
        if (y < 500 || y < lastY - 4) header.classList.remove("hide");
        else if (y > lastY + 4 && !header.contains(document.activeElement)) header.classList.add("hide");
      }
      lastY = y;
      if (bar) bar.style.transform = "scaleX(" + Math.min(1, y / maxScroll) + ")";
    };
    window.addEventListener("scroll", function () { if (!ticking) { ticking = true; requestAnimationFrame(update); } }, { passive: true });
    window.addEventListener("resize", function () { measure(); update(); });
    window.addEventListener("load", function () { measure(); update(); });
    if ("ResizeObserver" in window) new ResizeObserver(function () { measure(); }).observe(document.body);
    measure(); update();
  });

  // ---------- До / после: палец ведёт линию 1:1, вертикальный свайп остаётся прокруткой страницы ----------
  safe("before-after", function () {
    var ba = document.querySelector(".ba");
    if (!ba) return;
    var knob = ba.querySelector(".ba-knob");
    var line = ba.querySelector(".ba-line");
    var after = ba.querySelector(".after");
    var hint = document.querySelector(".drag-hint");
    if (!knob || !line || !after) return;
    var pos = 50, width = 1, left = 0, intro = null, drag = null;

    // линию двигаем transform'ом, картинку режем clip-path — без CSS-переменной на родителе
    line.style.left = "0px";
    var measure = function () { var r = ba.getBoundingClientRect(); width = r.width || 1; left = r.left; };
    var render = function () {
      after.style.clipPath = "inset(0 0 0 " + pos + "%)";
      line.style.transform = "translate3d(" + (pos / 100 * width).toFixed(2) + "px,0,0)";
    };
    var setPos = function (p) {
      pos = Math.max(2, Math.min(98, p));
      render();
      knob.setAttribute("aria-valuenow", Math.round(pos));
    };
    var stopIntro = function () {
      if (!intro) return;
      var m = getComputedStyle(line).transform;
      var x = 0;
      if (m && m !== "none") { try { x = new DOMMatrixReadOnly(m).m41; } catch (err) { x = pos / 100 * width; } }
      intro.forEach(function (a) { a.cancel(); });
      intro = null;
      setPos(x / width * 100);
    };
    var touched = function () {
      stopIntro();
      if (!ba.classList.contains("touched")) {
        ba.classList.add("touched");
        if (hint) hint.style.opacity = "0";
      }
    };

    ba.addEventListener("pointerdown", function (e) {
      if (drag || (e.pointerType === "mouse" && e.button !== 0)) return; // второй палец игнорируем
      if (e.target.closest("a, button:not(.ba-knob)")) return;
      measure();
      drag = { id: e.pointerId, x: e.clientX, y: e.clientY, start: pos, active: false };
      if (e.pointerType === "mouse") {
        // мышь: клик ставит линию под курсор и сразу тянет
        touched();
        setPos((e.clientX - left) / width * 100);
        drag.start = pos; drag.active = true;
        try { ba.setPointerCapture(e.pointerId); } catch (err) {}
      }
      // палец: ничего не делаем, пока не станет ясно, что жест горизонтальный (иначе это прокрутка страницы)
    });
    ba.addEventListener("pointermove", function (e) {
      if (!drag || e.pointerId !== drag.id) return;
      var dx = e.clientX - drag.x;
      if (!drag.active) {
        var dy = e.clientY - drag.y;
        if (Math.abs(dx) < 6 || Math.abs(dx) <= Math.abs(dy)) return;
        touched();
        drag.start = pos; drag.active = true;
        try { ba.setPointerCapture(e.pointerId); } catch (err) {}
      }
      setPos(drag.start + dx / width * 100);
    });
    var end = function (e) {
      // lostpointercapture всплывает и с дочернего элемента, когда захват переходит к .ba, — его пропускаем
      if (e.type === "lostpointercapture" && e.target !== ba) return;
      if (drag && e.pointerId === drag.id) drag = null;
    };
    ["pointerup", "pointercancel", "lostpointercapture"].forEach(function (t) { ba.addEventListener(t, end); });

    // клавиатура: мгновенно, без анимации
    knob.addEventListener("keydown", function (e) {
      var map = { ArrowLeft: -5, ArrowDown: -5, ArrowRight: 5, ArrowUp: 5, PageDown: -20, PageUp: 20 };
      if (e.key in map) { touched(); setPos(pos + map[e.key]); e.preventDefault(); }
      else if (e.key === "Home" || e.key === "End") { touched(); setPos(e.key === "Home" ? 2 : 98); e.preventDefault(); }
    });

    if ("ResizeObserver" in window) {
      new ResizeObserver(function () {
        var w = width;
        measure();
        if (Math.abs(width - w) < 1) return; // первый вызов наблюдателя приходит сразу — размер тот же
        if (intro) intro.forEach(function (a) { a.finish(); });
        render();
      }).observe(ba);
    } else {
      window.addEventListener("resize", function () { measure(); render(); });
    }

    measure();
    setPos(50);
    // интро: шторка уезжает от «черновой» к середине — показывает, что фото можно тянуть.
    // WAAPI (не rAF): играет во время загрузки страницы и не должно ждать занятый main thread.
    if (canAnimate) {
      var opts = { duration: 1400, delay: 500, easing: EASE_IN_OUT, fill: "backwards" };
      intro = [
        after.animate([{ clipPath: "inset(0 0 0 98%)" }, { clipPath: "inset(0 0 0 50%)" }], opts),
        line.animate([{ transform: "translate3d(" + (.98 * width) + "px,0,0)" }, { transform: "translate3d(" + (.5 * width) + "px,0,0)" }], opts)
      ];
      intro[0].onfinish = function () { intro = null; };
    }
  });

  // ---------- Вкладки «7 вопросов / 6 флагов» (стрелки ←/→ по ARIA) ----------
  safe("tabs", function () {
    each(document.querySelectorAll("[role=tablist]"), function (list) {
      var tabs = Array.prototype.slice.call(list.querySelectorAll("[role=tab]"));
      var select = function (tab, animateIt) {
        tabs.forEach(function (t) {
          var on = t === tab;
          t.setAttribute("aria-selected", on ? "true" : "false");
          t.tabIndex = on ? 0 : -1;
          var panel = document.getElementById(t.getAttribute("aria-controls"));
          if (!panel) return;
          var wasHidden = panel.hidden;
          panel.hidden = !on;
          // один короткий вход для всей панели, без стаггера по карточкам: вкладку переключают много раз
          if (on && wasHidden && animateIt && canAnimate) {
            panel.animate([{ opacity: 0, transform: "translate3d(0,6px,0)" }, { opacity: 1, transform: "none" }], { duration: 220, easing: EASE_OUT });
          }
        });
      };
      tabs.forEach(function (tab, i) {
        tab.tabIndex = tab.getAttribute("aria-selected") === "true" ? 0 : -1;
        tab.addEventListener("click", function (e) { select(tab, e.detail !== 0); });
        tab.addEventListener("keydown", function (e) {
          var n = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
          if (!n) return;
          e.preventDefault();
          var next = tabs[(i + n + tabs.length) % tabs.length];
          select(next, false);
          next.focus();
        });
      });
    });
  });

  // ---------- FAQ: высота по замеру, прерываемо, без GSAP ----------
  safe("faq", function () {
    if (!canAnimate) return; // нативное <details> — мгновенно
    each(document.querySelectorAll(".faq details"), function (d) {
      var summary = d.querySelector("summary");
      var body = d.querySelector(".faq-body");
      if (!summary || !body) return;
      var anim = null, target = d.open;
      summary.addEventListener("click", function (e) {
        e.preventDefault();
        if (!anim) target = d.open; // браузер мог открыть сам (поиск по странице)
        target = !target;
        var from = d.open ? body.getBoundingClientRect().height : 0;
        var fromOp = d.open ? parseFloat(getComputedStyle(body).opacity) : 0;
        if (anim) { anim.onfinish = null; anim.cancel(); anim = null; }
        d.classList.toggle("is-closing", !target);
        if (e.detail === 0) { d.open = target; d.classList.remove("is-closing"); return; } // Enter/пробел — без анимации
        if (target) d.open = true;
        var to = target ? body.scrollHeight : 0;
        anim = body.animate(
          [{ height: from + "px", opacity: fromOp }, { height: to + "px", opacity: target ? 1 : 0 }],
          { duration: target ? 280 : 200, easing: EASE_OUT }
        );
        anim.onfinish = function () {
          anim = null;
          if (!target) d.open = false;
          d.classList.remove("is-closing");
        };
      });
    });
  });

  // ---------- Этапы ремонта: смена фото при прокрутке ----------
  safe("scope", function () {
    var items = document.querySelectorAll(".scope-item");
    var imgs = document.querySelectorAll(".scope-media img");
    var counter = document.querySelector(".scope-counter b");
    var counterName = document.querySelector(".scope-counter span");
    if (!items.length) return;
    if (!hasIO) { each(items, function (it) { it.classList.add("on"); }); return; }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        var i = Array.prototype.indexOf.call(items, en.target);
        each(items, function (it, k) { it.classList.toggle("on", k === i); });
        each(imgs, function (im, k) { im.classList.toggle("on", k === i); });
        if (counter) counter.textContent = "0" + (i + 1);
        var h = en.target.querySelector("h3");
        if (counterName && h) counterName.textContent = h.textContent;
      });
    }, { rootMargin: "-45% 0px -45% 0px" });
    each(items, function (it) { io.observe(it); });
  });

  // ---------- Появление блоков при прокрутке (IntersectionObserver + WAAPI, без GSAP) ----------
  safe("reveal", function () {
    var els = Array.prototype.slice.call(document.querySelectorAll(".rv"));
    var bigH = document.querySelector(".big-cta h2");
    var bigWords = bigH ? bigH.querySelectorAll(".w") : [];
    if (bigWords.length) els.push(bigH);
    if (!els.length || !canAnimate || !hasIO) return;
    // задержки внутри одной «пачки» сокращаются: волна, а не метроном
    var DELAYS = [0, 80, 140, 185, 220, 245, 260];
    var rise = function (el, dist, dur, delay) {
      el.animate([{ opacity: 0, transform: "translate3d(0," + dist + ",0)" }, { opacity: 1, transform: "none" }],
        { duration: dur, delay: delay, easing: EASE_OUT, fill: "backwards" });
    };
    var io = new IntersectionObserver(function (entries) {
      var batch = entries.filter(function (en) { return en.isIntersecting; }).map(function (en) { return en.target; });
      batch.sort(function (a, b) { return a.compareDocumentPosition(b) & 4 ? -1 : 1; });
      batch.forEach(function (el, i) {
        io.unobserve(el);
        var delay = DELAYS[Math.min(i, DELAYS.length - 1)];
        el.classList.add("in");
        if (el === bigH) {
          each(bigWords, function (w, k) { rise(w, "40%", 700, k * 90); });
        } else {
          // заголовок — главный, проходит больше; остальное — короче
          rise(el, /^H[12]$/.test(el.tagName) ? "20px" : "12px", 600, delay);
        }
      });
    }, { rootMargin: "0px 0px -10% 0px" });
    els.forEach(function (el) { io.observe(el); });
    root.classList.add("rv-on"); // прячем только после того, как наблюдатель точно подключён
    // быстрый переход по якорю может «перепрыгнуть» блок, и наблюдатель его не заметит.
    // Всё, что уже выше экрана, показываем сразу, без анимации — пустых мест над экраном не бывает.
    var pending = els.slice(), sweepT = 0;
    var sweep = function () {
      pending = pending.filter(function (el) {
        if (el.classList.contains("in")) return false;
        if (el.getBoundingClientRect().bottom < 0) { io.unobserve(el); el.classList.add("in"); return false; }
        return true;
      });
      if (!pending.length) window.removeEventListener("scroll", onSweep);
    };
    var onSweep = function () { clearTimeout(sweepT); sweepT = setTimeout(sweep, 150); };
    window.addEventListener("scroll", onSweep, { passive: true });
    sweep();
  });

  // ---------- Курсор и «магнитные» кнопки (только мышь, только с GSAP) ----------
  safe("cursor", function () {
    var cursor = document.querySelector(".cursor");
    if (!cursor) return;
    if (!(gsapOn && finePointer)) { cursor.remove(); return; }
    var SMALL = 10 / 64; // кружок 64px, уменьшенный до 10px: масштаб вниз остаётся чётким
    gsap.set(cursor, { scale: SMALL, opacity: 0 });
    var cx = gsap.quickTo(cursor, "x", { duration: .25, ease: "power3" });
    var cy = gsap.quickTo(cursor, "y", { duration: .25, ease: "power3" });
    var shown = false, big = false;
    window.addEventListener("pointermove", function (e) {
      if (e.pointerType !== "mouse") return;
      if (!shown) { shown = true; gsap.set(cursor, { x: e.clientX, y: e.clientY }); gsap.to(cursor, { opacity: 1, duration: .2 }); }
      cx(e.clientX); cy(e.clientY);
    }, { passive: true });
    document.addEventListener("mouseleave", function () { shown = false; gsap.to(cursor, { opacity: 0, duration: .15 }); });
    document.addEventListener("pointerover", function (e) {
      var on = !!(e.target.closest && e.target.closest("a, button, .ba, label.option, summary, [role=tab]"));
      if (on === big) return;
      big = on;
      gsap.to(cursor, { scale: on ? 1 : SMALL, duration: .25, ease: "power3.out", overwrite: "auto" });
    });
    each(document.querySelectorAll(".magnetic"), function (btn) {
      var mx = gsap.quickTo(btn, "x", { duration: .35, ease: "power3" });
      var my = gsap.quickTo(btn, "y", { duration: .35, ease: "power3" });
      btn.addEventListener("pointermove", function (e) {
        if (e.pointerType !== "mouse") return;
        // считаем от исходного положения кнопки, а не от уже сдвинутого
        var r = btn.getBoundingClientRect();
        var ox = r.left - gsap.getProperty(btn, "x"), oy = r.top - gsap.getProperty(btn, "y");
        mx((e.clientX - ox - r.width / 2) * .15);
        my((e.clientY - oy - r.height / 2) * .25);
      });
      btn.addEventListener("pointerleave", function () { mx(0); my(0); });
    });
  });

  // ---------- Два пути: «Ищу сам / Через StroyLink» ----------
  // Без JS оба списка видны друг под другом. С JS — переключатель (мышь, палец, Tab + Enter/пробел, стрелки).
  safe("two-paths", function () {
    var vs = document.querySelector(".vs");
    if (!vs) return;
    var vsOpts = vs.querySelectorAll(".vs-opt");
    var vsPanels = vs.querySelectorAll(".vs-panel");
    var vsLive = vs.querySelector("[data-vs-live]");
    var vsState = vs.getAttribute("data-state") || "self";
    var vsTl = null;
    var vsTouched = false;
    var vsPanel = function (side) { return vs.querySelector('.vs-panel[data-side="' + side + '"]'); };
    var vsSync = function () {
      each(vsOpts, function (b) { b.setAttribute("aria-pressed", b.getAttribute("data-side") === vsState ? "true" : "false"); });
      each(vsPanels, function (p) {
        var on = p.getAttribute("data-side") === vsState;
        p.classList.toggle("on", on);
        p.setAttribute("aria-hidden", on ? "false" : "true");
      });
    };
    var vsPlay = function (side, instant) {
      if (vsTl) { vsTl.progress(1).kill(); vsTl = null; }
      if (!gsapOn || instant) return;
      var p = vsPanel(side);
      if (!p) return;
      var its = p.querySelectorAll(".vs-item");
      var route = p.querySelector(".vs-route path");
      var wave = { amount: .24, ease: "power1.out" }; // сокращающиеся интервалы
      vsTl = gsap.timeline();
      if (route) vsTl.fromTo(route, { strokeDashoffset: 1 }, { strokeDashoffset: 0, duration: side === "self" ? .9 : .45, ease: side === "self" ? "power1.inOut" : "power3.out" }, 0);
      if (side === "self") {
        // «запутанный» путь: карточки приходят вразнобой по горизонтали и ложатся с лёгким перелётом
        // (без наклона — в покое список ровный)
        vsTl.fromTo(its, { y: -14, x: function () { return gsap.utils.random(-10, 10); }, opacity: 0 },
          { y: 0, x: 0, opacity: 1, duration: .45, stagger: wave, ease: "back.out(1.6)" }, 0);
      } else {
        // прямой путь: карточки ровно встают одна за другой, галочки «щёлкают» вместе с ними
        vsTl.fromTo(its, { x: 20, opacity: 0 }, { x: 0, opacity: 1, duration: .4, stagger: wave, ease: "power3.out" }, 0);
        vsTl.fromTo(p.querySelectorAll(".vs-ico"), { scale: .5, opacity: 0 }, { scale: 1, opacity: 1, duration: .35, stagger: wave, ease: "back.out(2)" }, .1);
      }
      // сменившиеся цифры: короткий подъём, без 3D-переворота
      vsTl.fromTo(vs.querySelectorAll(".vs-stats dd, .vs-meter-top b, .vs-verdict"), { y: 6, opacity: 0 },
        { y: 0, opacity: 1, duration: .3, stagger: .04, ease: "power3.out" }, 0);
    };
    var vsSet = function (side, byUser, instant) {
      if (byUser) {
        vsTouched = true;
        each(vs.querySelectorAll(".vs-opt.nudge"), function (b) { b.classList.remove("nudge"); });
      }
      if (side === vsState) return;
      vsState = side;
      vs.setAttribute("data-state", side);
      vsSync();
      if (vsLive) vsLive.textContent = side === "link"
        ? (vsLive.getAttribute("data-live-link") || "Показан путь через StroyLink")
        : (vsLive.getAttribute("data-live-self") || "Показан путь, если искать самому");
      vsPlay(side, instant);
    };
    each(vsOpts, function (b) {
      // e.detail === 0 — нажатие с клавиатуры: переключаем мгновенно
      b.addEventListener("click", function (e) { vsSet(b.getAttribute("data-side"), true, e.detail === 0); });
      b.addEventListener("keydown", function (e) {
        if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
        e.preventDefault();
        var next = e.key === "ArrowRight" ? "link" : "self";
        vsSet(next, true, true);
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
    if (hasIO) {
      var vsStage = vs.querySelector(".vs-stage");
      var selfItems = vsPanel("self") ? vsPanel("self").querySelectorAll(".vs-item") : [];
      var played = false;
      var playFirst = function () {
        if (played) return;
        played = true;
        if (vsState === "self") vsPlay("self");
        else if (gsapOn) gsap.set(selfItems, { opacity: 1 });
      };
      // карточки прячем до первого показа, только если точно сможем их показать
      if (gsapOn && vsState === "self" && vsStage) gsap.set(selfItems, { opacity: 0 });
      var vsIo = new IntersectionObserver(function (en) {
        if (!en[0].isIntersecting) return;
        vsIo.disconnect();
        playFirst();
        // подсказка: «нажмите» на второй вариант, если человек сам не попробовал
        setTimeout(function () {
          if (!vsTouched && vsState === "self") { var l = vs.querySelector('.vs-opt[data-side="link"]'); if (l) l.classList.add("nudge"); }
        }, 2500);
      }, { threshold: .15 });
      if (vsStage) vsIo.observe(vsStage); else playFirst();
    }
  });

  // ---------- Мини-кнопка заявки: после блока «Почему через нас», прячется у формы и внизу ----------
  safe("mini-cta", function () {
    var mini = document.querySelector(".mini-cta");
    var benefits = document.getElementById("vygoda");
    if (!mini || !benefits) return;
    var zones = [document.getElementById("zayavka"), document.querySelector(".big-cta"), document.querySelector(".site-footer")].filter(Boolean);
    var tick = false;
    var upd = function () {
      tick = false;
      var vh = window.innerHeight;
      var past = benefits.getBoundingClientRect().bottom < vh * .5;
      var inZone = zones.some(function (z) { var r = z.getBoundingClientRect(); return r.top < vh && r.bottom > 0; });
      mini.classList.toggle("show", past && !inZone);
    };
    window.addEventListener("scroll", function () { if (!tick) { tick = true; requestAnimationFrame(upd); } }, { passive: true });
    window.addEventListener("resize", upd);
    upd();
  });

  // ---------- Путь заявки на телефоне: полоска показывает, сколько карточек пролистано ----------
  safe("path-mobile", function () {
    var vp = document.querySelector(".path-viewport");
    var bar = document.querySelector(".path-bar span");
    if (!vp || !bar) return;
    var tick = false;
    vp.addEventListener("scroll", function () {
      if (tick || window.innerWidth >= 900) return;
      tick = true;
      requestAnimationFrame(function () {
        tick = false;
        var m = vp.scrollWidth - vp.clientWidth;
        bar.style.transform = "scaleX(" + (m > 0 ? vp.scrollLeft / m : 0) + ")";
      });
    }, { passive: true });
  });

  // ---------- Бесконечная «бегущая» стрелка в карточке 03 работает, только когда карточку видно ----------
  safe("pc-pass", function () {
    var pass = document.querySelectorAll(".pc-pass");
    if (!pass.length || !hasIO) return;
    root.classList.add("pc-io");
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) { en.target.classList.toggle("is-live", en.isIntersecting); });
    });
    each(pass, function (p) { io.observe(p); });
  });

  if (!gsapOn) return;

  // ---------- Горизонтальный путь заявки (закрепляется на десктопе) ----------
  safe("path-pin", function () {
    var mm = gsap.matchMedia();
    mm.add("(min-width: 900px)", function () {
      var track = document.querySelector(".path-track");
      var vp = document.querySelector(".path-viewport");
      if (!track || !vp) return;
      var dist = function () { return Math.max(0, track.scrollWidth - vp.clientWidth); };
      // небольшой scrub — сглаживает шаги колеса, но почти не отстаёт от трекпада
      var pathTween = gsap.to(track, {
        x: function () { return -dist(); },
        ease: "none",
        scrollTrigger: { trigger: ".path", start: "top top", end: function () { return "+=" + dist(); }, pin: true, scrub: .35, invalidateOnRefresh: true, anticipatePin: 1 },
      });
      gsap.to(".path-bar span", { scaleX: 1, ease: "none", scrollTrigger: { trigger: ".path", start: "top top", end: function () { return "+=" + dist(); }, scrub: .35 } });
      // большие цифры на карточках плывут медленнее карточек — глубина при прокрутке
      gsap.utils.toArray(".path-card .num").forEach(function (n) {
        gsap.fromTo(n, { xPercent: 24 }, { xPercent: -12, ease: "none", scrollTrigger: { trigger: n.parentNode, containerAnimation: pathTween, start: "left right", end: "right left", scrub: true } });
      });
    });
  });

  // ---------- Подвал: слово-логотип слегка плывёт ----------
  safe("wordmark", function () {
    if (!document.querySelector(".wordmark")) return;
    gsap.fromTo(".wordmark", { xPercent: -8 }, { xPercent: 4, ease: "none", scrollTrigger: { trigger: ".site-footer", start: "top bottom", end: "bottom bottom", scrub: true } });
  });

  window.addEventListener("load", function () { ScrollTrigger.refresh(); });
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () { ScrollTrigger.refresh(); });
})();
