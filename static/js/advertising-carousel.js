(function () {
  "use strict";

  const AUTOPLAY_DELAY = 8000;
  const SWIPE_THRESHOLD = 50;

  function getNavigationIndex(key, currentIndex, total) {
    if (total < 1) {
      return null;
    }
    if (key === "ArrowLeft") {
      return (currentIndex - 1 + total) % total;
    }
    if (key === "ArrowRight") {
      return (currentIndex + 1) % total;
    }
    if (key === "Home") {
      return 0;
    }
    if (key === "End") {
      return total - 1;
    }
    return null;
  }

  function formatPosition(template, current, total) {
    return (template || "")
      .replace("{current}", String(current))
      .replace("{total}", String(total));
  }

  function createAdvertisingCarousel(carousel, options) {
    const settings = options || {};
    const pageDocument =
      settings.document || carousel.ownerDocument ||
      (typeof document !== "undefined" ? document : null);
    const setTimer = settings.setTimeout || setTimeout;
    const clearTimer = settings.clearTimeout || clearTimeout;
    const matchMedia = settings.matchMedia ||
      (typeof window !== "undefined" && window.matchMedia
        ? window.matchMedia.bind(window)
        : null);
    const slides = Array.from(
      carousel.querySelectorAll("[data-advertising-slide]"),
    );
    const indicators = Array.from(
      carousel.querySelectorAll("[data-advertising-indicator]"),
    );
    const controls = carousel.querySelector("[data-advertising-controls]");
    const previousButton = carousel.querySelector("[data-advertising-previous]");
    const nextButton = carousel.querySelector("[data-advertising-next]");
    const pauseButton = carousel.querySelector("[data-advertising-pause]");
    const pauseText = carousel.querySelector("[data-advertising-pause-text]");
    const pauseIcon = carousel.querySelector("[data-advertising-pause-icon]");
    const status = carousel.querySelector("[data-advertising-status]");

    if (slides.length === 0) {
      return null;
    }

    let currentIndex = 0;
    let timerId = null;
    let manuallyPaused = false;
    let pointerInside = false;
    let focusInside = false;
    let touchStart = null;
    let destroyed = false;
    const motionQuery = matchMedia
      ? matchMedia("(prefers-reduced-motion: reduce)")
      : null;

    function reducedMotion() {
      return Boolean(motionQuery && motionQuery.matches);
    }

    function documentHidden() {
      return Boolean(pageDocument && pageDocument.hidden);
    }

    function canAutoplay() {
      return (
        !destroyed &&
        slides.length > 1 &&
        !manuallyPaused &&
        !pointerInside &&
        !focusInside &&
        !documentHidden() &&
        !reducedMotion()
      );
    }

    function stopTimer() {
      if (timerId !== null) {
        clearTimer(timerId);
        timerId = null;
      }
    }

    function scheduleAutoplay() {
      stopTimer();
      if (!canAutoplay()) {
        return;
      }
      timerId = setTimer(() => {
        timerId = null;
        showSlide((currentIndex + 1) % slides.length, false);
        scheduleAutoplay();
      }, AUTOPLAY_DELAY);
    }

    function syncPauseButton() {
      if (!pauseButton) {
        return;
      }
      pauseButton.hidden = slides.length < 2 || reducedMotion();
      const label = manuallyPaused
        ? pauseButton.dataset.resumeLabel
        : pauseButton.dataset.pauseLabel;
      pauseButton.setAttribute("aria-label", label || "");
      pauseButton.setAttribute("aria-pressed", manuallyPaused ? "true" : "false");
      if (pauseText) {
        pauseText.textContent = label || "";
      }
      if (pauseIcon) {
        pauseIcon.classList.toggle("fa-pause", !manuallyPaused);
        pauseIcon.classList.toggle("fa-play", manuallyPaused);
      }
    }

    function showSlide(index, announce) {
      if (index < 0 || index >= slides.length) {
        return false;
      }
      currentIndex = index;
      slides.forEach((slide, slideIndex) => {
        const active = slideIndex === currentIndex;
        slide.hidden = !active;
        slide.setAttribute("aria-hidden", active ? "false" : "true");
      });
      indicators.forEach((indicator, indicatorIndex) => {
        if (indicatorIndex === currentIndex) {
          indicator.setAttribute("aria-current", "true");
        } else {
          indicator.removeAttribute("aria-current");
        }
      });
      if (status) {
        status.textContent = announce
          ? formatPosition(
            carousel.dataset.positionLabel,
            currentIndex + 1,
            slides.length,
          )
          : "";
      }
      return true;
    }

    function navigate(index) {
      if (showSlide(index, true)) {
        scheduleAutoplay();
      }
    }

    if (slides.length > 1) {
      carousel.setAttribute("aria-roledescription", "carousel");
      if (controls) {
        controls.hidden = false;
      }
      previousButton.addEventListener("click", () => {
        navigate((currentIndex - 1 + slides.length) % slides.length);
      });
      nextButton.addEventListener("click", () => {
        navigate((currentIndex + 1) % slides.length);
      });
      indicators.forEach((indicator, index) => {
        indicator.addEventListener("click", () => navigate(index));
      });
      if (pauseButton) {
        pauseButton.addEventListener("click", () => {
          manuallyPaused = !manuallyPaused;
          syncPauseButton();
          scheduleAutoplay();
        });
      }
    }

    carousel.addEventListener("keydown", (event) => {
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) {
        return;
      }
      const index = getNavigationIndex(event.key, currentIndex, slides.length);
      if (index !== null && slides.length > 1) {
        event.preventDefault();
        navigate(index);
      }
    });

    carousel.addEventListener("pointerenter", () => {
      pointerInside = true;
      scheduleAutoplay();
    });
    carousel.addEventListener("pointerleave", () => {
      pointerInside = false;
      scheduleAutoplay();
    });
    carousel.addEventListener("focusin", () => {
      focusInside = true;
      scheduleAutoplay();
    });
    carousel.addEventListener("focusout", (event) => {
      if (!event.relatedTarget || !carousel.contains(event.relatedTarget)) {
        focusInside = false;
        scheduleAutoplay();
      }
    });

    carousel.addEventListener("touchstart", (event) => {
      if (event.touches.length !== 1) {
        touchStart = null;
        return;
      }
      touchStart = {
        x: event.touches[0].clientX,
        y: event.touches[0].clientY,
      };
    }, { passive: true });
    carousel.addEventListener("touchend", (event) => {
      if (!touchStart || event.changedTouches.length !== 1) {
        touchStart = null;
        return;
      }
      const deltaX = event.changedTouches[0].clientX - touchStart.x;
      const deltaY = event.changedTouches[0].clientY - touchStart.y;
      touchStart = null;
      if (
        slides.length > 1 &&
        Math.abs(deltaX) >= SWIPE_THRESHOLD &&
        Math.abs(deltaX) > Math.abs(deltaY) * 1.2
      ) {
        navigate(
          deltaX < 0
            ? (currentIndex + 1) % slides.length
            : (currentIndex - 1 + slides.length) % slides.length,
        );
      }
    }, { passive: true });
    carousel.addEventListener("touchcancel", () => {
      touchStart = null;
    }, { passive: true });

    const visibilityHandler = () => scheduleAutoplay();
    if (pageDocument) {
      pageDocument.addEventListener("visibilitychange", visibilityHandler);
    }
    const motionHandler = () => {
      syncPauseButton();
      scheduleAutoplay();
    };
    if (motionQuery) {
      if (typeof motionQuery.addEventListener === "function") {
        motionQuery.addEventListener("change", motionHandler);
      } else if (typeof motionQuery.addListener === "function") {
        motionQuery.addListener(motionHandler);
      }
    }

    carousel.classList.add("is-enhanced");
    showSlide(0, false);
    syncPauseButton();
    scheduleAutoplay();

    function destroy() {
      destroyed = true;
      stopTimer();
      if (pageDocument) {
        pageDocument.removeEventListener("visibilitychange", visibilityHandler);
      }
      if (motionQuery) {
        if (typeof motionQuery.removeEventListener === "function") {
          motionQuery.removeEventListener("change", motionHandler);
        } else if (typeof motionQuery.removeListener === "function") {
          motionQuery.removeListener(motionHandler);
        }
      }
    }

    if (typeof window !== "undefined") {
      window.addEventListener("pagehide", destroy, { once: true });
    }

    return {
      destroy,
      getCurrentIndex: () => currentIndex,
      hasTimer: () => timerId !== null,
      isManuallyPaused: () => manuallyPaused,
      showSlide,
    };
  }

  function initAdvertisingCarousels(root) {
    const context = root || document;
    return Array.from(context.querySelectorAll("[data-advertising-carousel]"))
      .filter((carousel) => !carousel.dataset.advertisingInitialized)
      .map((carousel) => {
        carousel.dataset.advertisingInitialized = "true";
        return createAdvertisingCarousel(carousel);
      })
      .filter(Boolean);
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = {
      AUTOPLAY_DELAY,
      SWIPE_THRESHOLD,
      createAdvertisingCarousel,
      formatPosition,
      getNavigationIndex,
      initAdvertisingCarousels,
    };
  }

  if (typeof document !== "undefined") {
    initAdvertisingCarousels(document);
  }
})();
