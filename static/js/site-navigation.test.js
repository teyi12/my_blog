"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const { createSiteNavigation } = require("./site-navigation.js");

class FakeTarget {
  constructor() {
    this.attributes = new Map();
    this.dataset = {};
    this.hidden = false;
    this.listeners = {};
    this.focusCount = 0;
  }

  addEventListener(type, listener) {
    this.listeners[type] ||= [];
    this.listeners[type].push(listener);
  }

  dispatch(type, event = {}) {
    for (const listener of this.listeners[type] || []) {
      listener(event);
    }
  }

  setAttribute(name, value) {
    this.attributes.set(name, value);
  }

  getAttribute(name) {
    return this.attributes.get(name);
  }

  focus() {
    this.focusCount += 1;
  }
}

class FakeMedia extends FakeTarget {
  constructor(matches) {
    super();
    this.matches = matches;
  }

  change(matches) {
    this.matches = matches;
    this.dispatch("change", { matches });
  }
}

function setup(matches = true) {
  const root = new FakeTarget();
  const toggle = new FakeTarget();
  const panel = new FakeTarget();
  const closeButton = new FakeTarget();
  const media = new FakeMedia(matches);
  toggle.setAttribute("aria-expanded", "false");

  const controller = createSiteNavigation({
    root,
    toggle,
    panel,
    closeButton,
    media,
  });

  return { root, toggle, panel, closeButton, media, controller };
}

test("mobile initialization progressively hides the initially visible menu", () => {
  const { toggle, panel, closeButton } = setup(true);

  assert.equal(toggle.hidden, false);
  assert.equal(closeButton.hidden, false);
  assert.equal(panel.hidden, true);
  assert.equal(toggle.getAttribute("aria-expanded"), "false");
  assert.equal(panel.dataset.siteNavigationInitialized, "true");
});

test("toggle, close button and Escape synchronize aria and restore focus", () => {
  const { root, toggle, panel, closeButton } = setup(true);

  toggle.dispatch("click");
  assert.equal(panel.hidden, false);
  assert.equal(toggle.getAttribute("aria-expanded"), "true");

  closeButton.dispatch("click");
  assert.equal(panel.hidden, true);
  assert.equal(toggle.focusCount, 1);

  toggle.dispatch("click");
  root.dispatch("keydown", { key: "Escape" });
  assert.equal(panel.hidden, true);
  assert.equal(toggle.getAttribute("aria-expanded"), "false");
  assert.equal(toggle.focusCount, 2);
});

test("selecting a link closes the mobile menu without trapping focus", () => {
  const { toggle, panel } = setup(true);
  toggle.dispatch("click");

  panel.dispatch("click", { target: { closest: () => ({ href: "/articles/" }) } });

  assert.equal(panel.hidden, true);
  assert.equal(toggle.focusCount, 0);
});

test("breakpoint changes expose desktop navigation and reset mobile state", () => {
  const { toggle, panel, closeButton, media } = setup(true);
  toggle.dispatch("click");

  media.change(false);
  assert.equal(panel.hidden, false);
  assert.equal(toggle.hidden, true);
  assert.equal(closeButton.hidden, true);
  assert.equal(toggle.getAttribute("aria-expanded"), "true");

  media.change(true);
  assert.equal(panel.hidden, true);
  assert.equal(toggle.hidden, false);
  assert.equal(toggle.getAttribute("aria-expanded"), "false");
});

test("initialization is idempotent for the same navigation panel", () => {
  const fixture = setup(true);
  const secondController = createSiteNavigation(fixture);

  assert.equal(secondController, fixture.controller);
  assert.equal(fixture.toggle.listeners.click.length, 1);
  assert.equal(fixture.root.listeners.keydown.length, 1);
});
