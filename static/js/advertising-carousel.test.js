"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const {
  AUTOPLAY_DELAY,
  SWIPE_THRESHOLD,
  createAdvertisingCarousel,
  formatPosition,
  getNavigationIndex,
} = require("./advertising-carousel.js");

class FakeClassList {
  constructor() {
    this.values = new Set();
  }

  add(value) {
    this.values.add(value);
  }

  contains(value) {
    return this.values.has(value);
  }

  toggle(value, force) {
    if (force) {
      this.values.add(value);
    } else {
      this.values.delete(value);
    }
  }
}

class FakeEventTarget {
  constructor() {
    this.listeners = new Map();
  }

  addEventListener(type, callback) {
    const callbacks = this.listeners.get(type) || [];
    callbacks.push(callback);
    this.listeners.set(type, callbacks);
  }

  removeEventListener(type, callback) {
    const callbacks = this.listeners.get(type) || [];
    this.listeners.set(type, callbacks.filter((item) => item !== callback));
  }

  dispatch(type, values) {
    const event = {
      altKey: false,
      changedTouches: [],
      ctrlKey: false,
      defaultPrevented: false,
      key: "",
      metaKey: false,
      relatedTarget: null,
      shiftKey: false,
      touches: [],
      preventDefault() {
        this.defaultPrevented = true;
      },
      ...values,
    };
    (this.listeners.get(type) || []).forEach((callback) => callback(event));
    return event;
  }
}

class FakeElement extends FakeEventTarget {
  constructor() {
    super();
    this.attributes = new Map();
    this.classList = new FakeClassList();
    this.dataset = {};
    this.hidden = false;
    this.textContent = "";
  }

  getAttribute(name) {
    return this.attributes.has(name) ? this.attributes.get(name) : null;
  }

  removeAttribute(name) {
    this.attributes.delete(name);
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }
}

class FakeMediaQuery extends FakeEventTarget {
  constructor() {
    super();
    this.matches = false;
  }
}

class FakeDocument extends FakeEventTarget {
  constructor() {
    super();
    this.hidden = false;
    this.activeElement = null;
  }
}

function timerHarness() {
  let nextId = 1;
  const timers = new Map();
  return {
    clearTimeout(id) {
      timers.delete(id);
    },
    count() {
      return timers.size;
    },
    delay() {
      const entry = timers.values().next().value;
      return entry ? entry.delay : null;
    },
    runNext() {
      const entry = timers.entries().next().value;
      if (!entry) {
        return false;
      }
      const [id, timer] = entry;
      timers.delete(id);
      timer.callback();
      return true;
    },
    setTimeout(callback, delay) {
      const id = nextId;
      nextId += 1;
      timers.set(id, { callback, delay });
      return id;
    },
  };
}

function buildCarousel(total) {
  const document = new FakeDocument();
  const mediaQuery = new FakeMediaQuery();
  const timers = timerHarness();
  const slides = Array.from({ length: total }, () => new FakeElement());
  const indicators = Array.from({ length: total }, () => new FakeElement());
  const controls = new FakeElement();
  controls.hidden = true;
  const previous = new FakeElement();
  const next = new FakeElement();
  const pause = new FakeElement();
  pause.dataset.pauseLabel = "Pause carousel";
  pause.dataset.resumeLabel = "Resume carousel";
  const pauseText = new FakeElement();
  const pauseIcon = new FakeElement();
  const status = new FakeElement();
  const selectorMap = {
    "[data-advertising-controls]": controls,
    "[data-advertising-previous]": previous,
    "[data-advertising-next]": next,
    "[data-advertising-pause]": pause,
    "[data-advertising-pause-text]": pauseText,
    "[data-advertising-pause-icon]": pauseIcon,
    "[data-advertising-status]": status,
  };
  const contained = new Set([
    ...slides,
    ...indicators,
    controls,
    previous,
    next,
    pause,
    pauseText,
    pauseIcon,
    status,
  ]);
  const carousel = new FakeElement();
  carousel.dataset.positionLabel = "Campaign {current} of {total}";
  carousel.ownerDocument = document;
  carousel.contains = (element) => contained.has(element);
  carousel.querySelector = (selector) => selectorMap[selector] || null;
  carousel.querySelectorAll = (selector) => {
    if (selector === "[data-advertising-slide]") {
      return slides;
    }
    if (selector === "[data-advertising-indicator]") {
      return indicators;
    }
    return [];
  };
  const controller = createAdvertisingCarousel(carousel, {
    document,
    matchMedia: () => mediaQuery,
    setTimeout: timers.setTimeout,
    clearTimeout: timers.clearTimeout,
  });

  return {
    carousel,
    controller,
    controls,
    document,
    indicators,
    mediaQuery,
    next,
    pause,
    pauseIcon,
    pauseText,
    previous,
    slides,
    status,
    timers,
  };
}

test("navigation helpers wrap and localize positions", () => {
  assert.equal(getNavigationIndex("ArrowLeft", 0, 3), 2);
  assert.equal(getNavigationIndex("ArrowRight", 2, 3), 0);
  assert.equal(getNavigationIndex("Home", 2, 3), 0);
  assert.equal(getNavigationIndex("End", 0, 3), 2);
  assert.equal(getNavigationIndex("Escape", 0, 3), null);
  assert.equal(formatPosition("Campaign {current} of {total}", 2, 5), "Campaign 2 of 5");
});

test("one campaign remains visible without controls or autoplay", () => {
  const fixture = buildCarousel(1);

  assert.ok(fixture.controller);
  assert.equal(fixture.slides[0].hidden, false);
  assert.equal(fixture.controls.hidden, true);
  assert.equal(fixture.pause.hidden, true);
  assert.equal(fixture.controller.hasTimer(), false);
  assert.equal(fixture.carousel.getAttribute("aria-roledescription"), null);
});

test("enhancement removes inactive slides from tab flow and syncs controls", () => {
  const fixture = buildCarousel(3);

  assert.equal(fixture.controls.hidden, false);
  assert.deepEqual(fixture.slides.map((slide) => slide.hidden), [false, true, true]);
  assert.equal(fixture.slides[1].getAttribute("aria-hidden"), "true");
  assert.equal(fixture.indicators[0].getAttribute("aria-current"), "true");
  assert.equal(fixture.pause.getAttribute("aria-label"), "Pause carousel");
  assert.equal(fixture.pauseText.textContent, "Pause carousel");

  fixture.next.dispatch("click");
  assert.equal(fixture.controller.getCurrentIndex(), 1);
  assert.deepEqual(fixture.slides.map((slide) => slide.hidden), [true, false, true]);
  assert.equal(fixture.indicators[1].getAttribute("aria-current"), "true");
  assert.equal(fixture.status.textContent, "Campaign 2 of 3");

  fixture.previous.dispatch("click");
  assert.equal(fixture.controller.getCurrentIndex(), 0);
});

test("keyboard navigation announces without moving focus", () => {
  const fixture = buildCarousel(3);
  const focusedControl = fixture.next;
  fixture.document.activeElement = focusedControl;

  for (const [key, expected] of [
    ["ArrowRight", 1],
    ["End", 2],
    ["Home", 0],
    ["ArrowLeft", 2],
  ]) {
    const event = fixture.carousel.dispatch("keydown", { key });
    assert.equal(event.defaultPrevented, true);
    assert.equal(fixture.controller.getCurrentIndex(), expected);
    assert.equal(fixture.document.activeElement, focusedControl);
  }
});

test("autoplay is slow, silent, pausable and cleaned up", () => {
  const fixture = buildCarousel(3);

  assert.equal(fixture.timers.count(), 1);
  assert.equal(fixture.timers.delay(), AUTOPLAY_DELAY);
  fixture.timers.runNext();
  assert.equal(fixture.controller.getCurrentIndex(), 1);
  assert.equal(fixture.status.textContent, "");
  assert.equal(fixture.timers.count(), 1);

  fixture.pause.dispatch("click");
  assert.equal(fixture.controller.isManuallyPaused(), true);
  assert.equal(fixture.pause.getAttribute("aria-pressed"), "true");
  assert.equal(fixture.pause.getAttribute("aria-label"), "Resume carousel");
  assert.equal(fixture.pauseIcon.classList.contains("fa-play"), true);
  assert.equal(fixture.timers.count(), 0);

  fixture.pause.dispatch("click");
  assert.equal(fixture.controller.isManuallyPaused(), false);
  assert.equal(fixture.timers.count(), 1);
  fixture.controller.destroy();
  assert.equal(fixture.timers.count(), 0);
});

test("hover, focus, hidden tab and reduced motion gate resumption", () => {
  const fixture = buildCarousel(2);

  fixture.carousel.dispatch("pointerenter");
  assert.equal(fixture.timers.count(), 0);
  fixture.carousel.dispatch("pointerleave");
  assert.equal(fixture.timers.count(), 1);

  fixture.carousel.dispatch("focusin");
  assert.equal(fixture.timers.count(), 0);
  fixture.carousel.dispatch("focusout", { relatedTarget: fixture.next });
  assert.equal(fixture.timers.count(), 0);
  fixture.carousel.dispatch("focusout", { relatedTarget: null });
  assert.equal(fixture.timers.count(), 1);

  fixture.document.hidden = true;
  fixture.document.dispatch("visibilitychange");
  assert.equal(fixture.timers.count(), 0);
  fixture.document.hidden = false;
  fixture.document.dispatch("visibilitychange");
  assert.equal(fixture.timers.count(), 1);

  fixture.mediaQuery.matches = true;
  fixture.mediaQuery.dispatch("change");
  assert.equal(fixture.timers.count(), 0);
  assert.equal(fixture.pause.hidden, true);
  fixture.mediaQuery.matches = false;
  fixture.mediaQuery.dispatch("change");
  assert.equal(fixture.pause.hidden, false);
  assert.equal(fixture.timers.count(), 1);
});

test("horizontal swipe uses a threshold and never blocks vertical scrolling", () => {
  const fixture = buildCarousel(3);
  assert.equal(SWIPE_THRESHOLD, 50);

  fixture.carousel.dispatch("touchstart", {
    touches: [{ clientX: 120, clientY: 100 }],
  });
  const vertical = fixture.carousel.dispatch("touchend", {
    changedTouches: [{ clientX: 90, clientY: 190 }],
  });
  assert.equal(vertical.defaultPrevented, false);
  assert.equal(fixture.controller.getCurrentIndex(), 0);

  fixture.carousel.dispatch("touchstart", {
    touches: [{ clientX: 120, clientY: 100 }],
  });
  const horizontal = fixture.carousel.dispatch("touchend", {
    changedTouches: [{ clientX: 55, clientY: 105 }],
  });
  assert.equal(horizontal.defaultPrevented, false);
  assert.equal(fixture.controller.getCurrentIndex(), 1);
});
