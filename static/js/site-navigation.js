"use strict";

(function siteNavigationModule(globalScope) {
  const MOBILE_QUERY = "(max-width: 1199.98px)";
  const controllers = new WeakMap();

  function createSiteNavigation({ root, toggle, panel, closeButton, media }) {
    if (!root || !toggle || !panel || !closeButton || !media) {
      return null;
    }

    if (controllers.has(panel)) {
      return controllers.get(panel);
    }

    let isMobile = Boolean(media.matches);

    function setOpen(open, { restoreFocus = false } = {}) {
      const shouldOpen = !isMobile || Boolean(open);
      panel.hidden = !shouldOpen;
      toggle.setAttribute("aria-expanded", shouldOpen ? "true" : "false");

      if (!shouldOpen && restoreFocus) {
        toggle.focus();
      }

      return shouldOpen;
    }

    function synchronize() {
      isMobile = Boolean(media.matches);
      toggle.hidden = !isMobile;
      closeButton.hidden = !isMobile;
      setOpen(!isMobile);
    }

    function onToggle() {
      setOpen(toggle.getAttribute("aria-expanded") !== "true", {
        restoreFocus: toggle.getAttribute("aria-expanded") === "true",
      });
    }

    function onClose() {
      if (isMobile) {
        setOpen(false, { restoreFocus: true });
      }
    }

    function onKeydown(event) {
      if (
        isMobile &&
        event.key === "Escape" &&
        toggle.getAttribute("aria-expanded") === "true"
      ) {
        setOpen(false, { restoreFocus: true });
      }
    }

    function onPanelClick(event) {
      const selectedLink = event.target.closest && event.target.closest("a[href]");
      if (isMobile && selectedLink) {
        setOpen(false);
      }
    }

    toggle.addEventListener("click", onToggle);
    closeButton.addEventListener("click", onClose);
    panel.addEventListener("click", onPanelClick);
    root.addEventListener("keydown", onKeydown);

    if (typeof media.addEventListener === "function") {
      media.addEventListener("change", synchronize);
    } else if (typeof media.addListener === "function") {
      media.addListener(synchronize);
    }

    panel.dataset.siteNavigationInitialized = "true";
    synchronize();

    const controller = { setOpen, synchronize };
    controllers.set(panel, controller);
    return controller;
  }

  function initSiteNavigation(root = globalScope.document) {
    if (!root || !globalScope.matchMedia) {
      return null;
    }

    return createSiteNavigation({
      root,
      toggle: root.querySelector("[data-site-navigation-toggle]"),
      panel: root.querySelector("[data-site-navigation-panel]"),
      closeButton: root.querySelector("[data-site-navigation-close]"),
      media: globalScope.matchMedia(MOBILE_QUERY),
    });
  }

  const api = { MOBILE_QUERY, createSiteNavigation, initSiteNavigation };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }

  if (globalScope.document) {
    if (globalScope.document.readyState === "loading") {
      globalScope.document.addEventListener("DOMContentLoaded", () => {
        initSiteNavigation(globalScope.document);
      });
    } else {
      initSiteNavigation(globalScope.document);
    }
  }
})(typeof window !== "undefined" ? window : globalThis);
