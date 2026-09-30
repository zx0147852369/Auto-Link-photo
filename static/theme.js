/* ============================================================
   theme.js — สลับโหมดสว่าง / มืด

   จำค่าที่ผู้ใช้เลือกไว้ในเครื่อง ถ้ายังไม่เคยเลือกจะตามระบบปฏิบัติการ
   ปุ่มสลับคือแท็กใดก็ได้ที่มีแอตทริบิวต์ data-theme-toggle
   ============================================================ */
(function () {
  "use strict";

  var KEY = "alp-theme";           // ค่าที่เก็บ: light | dark | auto
  var media = window.matchMedia ? matchMedia("(prefers-color-scheme: dark)") : null;

  function saved() {
    try { return localStorage.getItem(KEY) || "auto"; } catch (e) { return "auto"; }
  }
  function store(v) {
    try { localStorage.setItem(KEY, v); } catch (e) {}
  }
  function systemDark() {
    return !!(media && media.matches);
  }
  function resolve(mode) {
    return mode === "dark" || (mode !== "light" && systemDark()) ? "dark" : "light";
  }

  function paintButtons(mode, actual) {
    var label = actual === "dark" ? "เปลี่ยนเป็นโหมดสว่าง" : "เปลี่ยนเป็นโหมดมืด";
    var word = mode === "auto" ? "ตามระบบ" : (actual === "dark" ? "มืด" : "สว่าง");
    document.querySelectorAll("[data-theme-toggle]").forEach(function (b) {
      b.setAttribute("title", label);
      b.setAttribute("aria-label", label);
      var tag = b.querySelector(".thnow");
      if (tag) tag.textContent = word;
    });
  }

  function apply(mode, animate) {
    var actual = resolve(mode);
    var root = document.documentElement;
    if (animate) {
      root.classList.add("thswap");
      clearTimeout(apply._t);
      apply._t = setTimeout(function () { root.classList.remove("thswap"); }, 320);
    }
    root.dataset.theme = actual;
    root.style.colorScheme = actual;
    paintButtons(mode, actual);
  }

  // สลับระหว่างสว่างกับมืดโดยยึดจากสิ่งที่เห็นอยู่ตอนนี้
  function toggle() {
    var next = resolve(saved()) === "dark" ? "light" : "dark";
    store(next);
    apply(next, true);
  }

  function bind() {
    document.querySelectorAll("[data-theme-toggle]").forEach(function (b) {
      if (b._thBound) return;
      b._thBound = true;
      b.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        toggle();
      });
    });
    apply(saved(), false);
  }

  // ถ้าผู้ใช้ยังไม่เคยเลือกเอง ให้เปลี่ยนตามระบบทันทีเมื่อระบบเปลี่ยน
  if (media) {
    var onChange = function () { if (saved() === "auto") apply("auto", true); };
    if (media.addEventListener) media.addEventListener("change", onChange);
    else if (media.addListener) media.addListener(onChange);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }

  window.ALPTheme = { toggle: toggle, apply: apply, current: function () { return saved(); } };
})();
