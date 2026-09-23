"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const {
  createPasswordToggle,
  createPhotoPreview,
  initAccountsUi,
  setPasswordVisibility,
} = require("./accounts.js");

class FakeElement {
  constructor() {
    this.attributes = new Map();
    this.dataset = {};
    this.listeners = {};
    this.hidden = false;
    this.textContent = "";
    this.value = "";
    this.files = [];
    this.focused = false;
  }

  addEventListener(type, listener) {
    this.listeners[type] = listener;
  }

  dispatch(type) {
    this.listeners[type]();
  }

  setAttribute(name, value) {
    this.attributes.set(name, value);
  }

  getAttribute(name) {
    return this.attributes.get(name);
  }

  removeAttribute(name) {
    this.attributes.delete(name);
    if (name === "src") {
      this.src = "";
    }
  }

  focus() {
    this.focused = true;
  }
}

test("password visibility keeps the value and synchronizes aria state", () => {
  const input = new FakeElement();
  input.type = "password";
  input.value = "never-change-this-value";
  const button = new FakeElement();
  button.dataset.showLabel = "Show";
  button.dataset.hideLabel = "Hide";

  assert.equal(setPasswordVisibility(input, button, true), true);
  assert.equal(input.type, "text");
  assert.equal(input.value, "never-change-this-value");
  assert.equal(button.getAttribute("aria-pressed"), "true");
  assert.equal(button.textContent, "Hide");

  setPasswordVisibility(input, button, false);
  assert.equal(input.type, "password");
  assert.equal(input.value, "never-change-this-value");
  assert.equal(button.getAttribute("aria-pressed"), "false");
  assert.equal(button.textContent, "Show");
});

test("password toggle uses a native click handler", () => {
  const input = new FakeElement();
  input.type = "password";
  const button = new FakeElement();
  button.hidden = true;
  button.dataset.showLabel = "Show";
  button.dataset.hideLabel = "Hide";
  button.setAttribute("aria-controls", "password-id");
  const root = { getElementById: () => input };

  assert.ok(createPasswordToggle(button, root));
  assert.equal(button.hidden, false);
  button.dispatch("click");
  assert.equal(input.type, "text");
  button.dispatch("click");
  assert.equal(input.type, "password");
});

test("photo preview revokes temporary URLs on replacement and cancel", () => {
  const input = new FakeElement();
  const preview = new FakeElement();
  preview.hidden = true;
  const image = new FakeElement();
  image.alt = "Photo preview";
  const name = new FakeElement();
  const cancel = new FakeElement();
  const status = new FakeElement();
  const elements = {
    'input[type="file"]': input,
    "[data-photo-preview]": preview,
    "[data-photo-preview-image]": image,
    "[data-photo-preview-name]": name,
    "[data-photo-preview-cancel]": cancel,
    "[data-photo-preview-status]": status,
  };
  const control = { querySelector: (selector) => elements[selector] };
  const revoked = [];
  let created = 0;
  const urls = {
    createObjectURL: () => "blob:preview-" + ++created,
    revokeObjectURL: (url) => revoked.push(url),
  };
  const controller = createPhotoPreview(control, urls);

  input.files = [{ name: "first.webp", type: "image/webp" }];
  assert.equal(controller.showSelectedPhoto(), true);
  assert.equal(image.src, "blob:preview-1");
  assert.equal(name.textContent, "first.webp");
  assert.equal(preview.hidden, false);

  input.files = [{ name: "second.png", type: "image/png" }];
  controller.showSelectedPhoto();
  assert.deepEqual(revoked, ["blob:preview-1"]);
  assert.equal(image.src, "blob:preview-2");

  cancel.dispatch("click");
  assert.deepEqual(revoked, ["blob:preview-1", "blob:preview-2"]);
  assert.equal(input.value, "");
  assert.equal(preview.hidden, true);
  assert.equal(input.focused, true);
});

test("initialization focuses only a rendered invalid-submit summary", () => {
  const summary = new FakeElement();
  const root = {
    querySelectorAll: () => [],
    querySelector: () => summary,
  };

  const result = initAccountsUi(root);
  assert.equal(result.errorSummary, summary);
  assert.equal(summary.focused, true);
});
