"use strict";
// Only a language code is stored. Never translate or persist data entered by the operator.
// Bilingual desk copy: every label lives in strings.json, the browser only picks a language.
const DeskLocale = (() => {
  const preference = "cyrusasha.desk.language";
  let language = "fa",
    catalog = {};
  const formats = { fa: new Intl.NumberFormat("fa-IR"), en: new Intl.NumberFormat("en-US") };
  // Keep a string as {key, vars} so it can be re-rendered after a language switch.
  const copy = (key, vars = {}) => ({ key, vars });
  // Render one value: nested messages, localized numbers, or untouched text.
  function text(value) {
    if (Array.isArray(value)) return value.map(text).join("");
    if (typeof value === "number") return formats[language].format(value);
    if (value == null || typeof value !== "object") return String(value ?? "");
    if (!Object.hasOwn(catalog, value.key)) return value.key;
    return catalog[value.key][language].replace(/\{(\w+)\}/g, (_, k) => text(value.vars?.[k]));
  }
  // Shorthand for rendering a key without keeping it.
  const t = (key, vars) => text(copy(key, vars));
  // Translate every tagged node under `root` from its data-i18n* attributes.
  function apply(root = document) {
    for (const n of root.querySelectorAll("[data-i18n]")) n.textContent = t(n.dataset.i18n);
    for (const [selector, attr] of [
      ["data-i18n-aria", "aria-label"],
      ["data-i18n-title", "title"],
      ["data-i18n-placeholder", "placeholder"],
    ]) {
      for (const n of root.querySelectorAll(`[${selector}]`))
        n.setAttribute(attr, t(n.getAttribute(selector)));
    }
  }
  // Switch language, direction and pressed state, then repaint the page.
  function select(code, remember = true) {
    language = code === "en" ? "en" : "fa";
    document.documentElement.lang = language;
    document.documentElement.dir = language === "fa" ? "rtl" : "ltr";
    document
      .querySelectorAll("[data-lang]")
      .forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === language)));
    if (remember) {
      try {
        localStorage.setItem(preference, language);
      } catch {
        /* storage is optional */
      }
    }
    apply();
  }
  // Fetch the catalog once, then restore the stored preference (Persian by default).
  async function load() {
    const response = await fetch("/strings.json");
    if (!response.ok) throw new Error("Cannot load locale catalog");
    catalog = await response.json();
    let initial = "fa";
    try {
      initial = localStorage.getItem(preference);
    } catch {
      /* Persian default */
    }
    select(initial, false);
  }
  return { load, select, apply, text, t, copy, has: (key) => Object.hasOwn(catalog, key) };
})();
