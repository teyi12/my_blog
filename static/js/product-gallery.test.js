"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const {
  createProductGallery,
  getNavigationIndex,
  isActivationKey,
} = require("./product-gallery.js");

class FakeClassList {
  constructor(initial) {
    this.values = new Set(initial || []);
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

class FakeElement {
  constructor() {
    this.attributes = new Map();
    this.classList = new FakeClassList();
    this.dataset = {};
    this.listeners = new Map();
    this.textContent = "";
    this.alt = "";
    this.focused = false;
  }

  addEventListener(type, callback) {
    const callbacks = this.listeners.get(type) || [];
    callbacks.push(callback);
    this.listeners.set(type, callbacks);
  }

  dispatch(type, values) {
    const event = {
      defaultPrevented: false,
      key: "",
      target: this,
      preventDefault() {
        this.defaultPrevented = true;
      },
      ...values,
    };
    (this.listeners.get(type) || []).forEach((callback) => callback(event));
    return event;
  }

  focus() {
    this.focused = true;
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

class FakeDialog extends FakeElement {
  constructor() {
    super();
    this.open = false;
  }

  close() {
    this.open = false;
    this.dispatch("close");
  }

  showModal() {
    this.open = true;
  }
}

function buildGallery(total) {
  const mainImage = new FakeElement();
  const enlargeLink = new FakeElement();
  const galleryStatus = new FakeElement();
  const dialog = new FakeDialog();
  const dialogContent = new FakeElement();
  const dialogImage = new FakeElement();
  const dialogCounter = new FakeElement();
  const closeButton = new FakeElement();
  const thumbnails = Array.from({ length: total }, (_, index) => {
    const thumbnail = new FakeElement();
    thumbnail.dataset.gallerySrc = `/image-${index + 1}.jpg`;
    thumbnail.dataset.galleryAlt = `Alternative ${index + 1}`;
    thumbnail.dataset.galleryStatus = `Image ${index + 1} sur ${total}`;
    if (index === 0) {
      thumbnail.setAttribute("aria-current", "true");
      thumbnail.classList.toggle("is-active", true);
    }
    return thumbnail;
  });
  const elements = {
    "[data-product-gallery-main]": mainImage,
    "[data-gallery-enlarge]": enlargeLink,
    "[data-gallery-status]": galleryStatus,
    "[data-gallery-dialog]": dialog,
    "[data-gallery-dialog-content]": dialogContent,
    "[data-gallery-dialog-image]": dialogImage,
    "[data-gallery-dialog-counter]": dialogCounter,
    "[data-gallery-dialog-close]": closeButton,
  };
  const gallery = {
    querySelector: (selector) => elements[selector] || null,
    querySelectorAll: (selector) =>
      selector === "[data-gallery-thumbnail]" ? thumbnails : [],
  };

  return {
    closeButton,
    dialog,
    dialogCounter,
    dialogImage,
    enlargeLink,
    gallery,
    galleryStatus,
    mainImage,
    thumbnails,
  };
}

test("activation and navigation keys have deterministic indices", () => {
  assert.equal(isActivationKey("Enter"), true);
  assert.equal(isActivationKey(" "), true);
  assert.equal(isActivationKey("Spacebar"), false);
  assert.equal(getNavigationIndex("ArrowLeft", 1, 3), 0);
  assert.equal(getNavigationIndex("ArrowRight", 1, 3), 2);
  assert.equal(getNavigationIndex("ArrowLeft", 0, 3), 0);
  assert.equal(getNavigationIndex("ArrowRight", 2, 3), 2);
  assert.equal(getNavigationIndex("Home", 2, 3), 0);
  assert.equal(getNavigationIndex("End", 0, 3), 2);
  assert.equal(getNavigationIndex("Escape", 0, 3), null);
});

test("thumbnail selection synchronizes image, alt, fallback href and state", () => {
  const fixture = buildGallery(3);
  const controller = createProductGallery(fixture.gallery);

  const click = fixture.thumbnails[1].dispatch("click");

  assert.equal(click.defaultPrevented, true);
  assert.equal(controller.getCurrentIndex(), 1);
  assert.equal(fixture.mainImage.getAttribute("src"), "/image-2.jpg");
  assert.equal(fixture.mainImage.alt, "Alternative 2");
  assert.equal(fixture.enlargeLink.getAttribute("href"), "/image-2.jpg");
  assert.equal(fixture.thumbnails[0].getAttribute("aria-current"), null);
  assert.equal(fixture.thumbnails[1].getAttribute("aria-current"), "true");
  assert.equal(fixture.thumbnails[1].classList.contains("is-active"), true);
  assert.equal(fixture.galleryStatus.textContent, "Image 2 sur 3");
});

test("Enter, Space, arrows, Home and End select while arrows move focus", () => {
  const fixture = buildGallery(3);
  const controller = createProductGallery(fixture.gallery);

  const end = fixture.thumbnails[0].dispatch("keydown", { key: "End" });
  assert.equal(end.defaultPrevented, true);
  assert.equal(controller.getCurrentIndex(), 2);
  assert.equal(fixture.thumbnails[2].focused, true);

  fixture.thumbnails[1].dispatch("keydown", { key: " " });
  assert.equal(controller.getCurrentIndex(), 1);

  fixture.thumbnails[0].dispatch("keydown", { key: "Enter" });
  assert.equal(controller.getCurrentIndex(), 0);

  fixture.thumbnails[0].dispatch("keydown", { key: "ArrowRight" });
  assert.equal(controller.getCurrentIndex(), 1);

  fixture.thumbnails[1].dispatch("keydown", { key: "Home" });
  assert.equal(controller.getCurrentIndex(), 0);
});

test("dialog navigation, Escape and close restore the exact opener", () => {
  const fixture = buildGallery(3);
  const controller = createProductGallery(fixture.gallery);
  controller.selectImage(1);

  const open = fixture.enlargeLink.dispatch("click");
  assert.equal(open.defaultPrevented, true);
  assert.equal(fixture.dialog.open, true);
  assert.equal(fixture.closeButton.focused, true);
  assert.equal(fixture.dialogImage.getAttribute("src"), "/image-2.jpg");
  assert.equal(fixture.dialogImage.alt, "Alternative 2");
  assert.equal(fixture.dialogCounter.textContent, "Image 2 sur 3");

  fixture.dialog.dispatch("keydown", { key: "ArrowRight" });
  assert.equal(controller.getCurrentIndex(), 2);
  assert.equal(fixture.dialogImage.getAttribute("src"), "/image-3.jpg");

  const escape = fixture.dialog.dispatch("keydown", { key: "Escape" });
  assert.equal(escape.defaultPrevented, true);
  assert.equal(fixture.dialog.open, false);
  assert.equal(fixture.dialogImage.getAttribute("src"), null);
  assert.equal(fixture.enlargeLink.focused, true);
  assert.equal(fixture.galleryStatus.getAttribute("aria-live"), "polite");
});

test("a one-image gallery still opens and closes safely", () => {
  const fixture = buildGallery(1);
  const controller = createProductGallery(fixture.gallery);

  assert.ok(controller);
  fixture.enlargeLink.dispatch("click");
  assert.equal(fixture.dialog.open, true);
  fixture.closeButton.dispatch("click");
  assert.equal(fixture.dialog.open, false);
  assert.equal(fixture.enlargeLink.focused, true);
});

test("a failed dialog enhancement preserves native link navigation", () => {
  const fixture = buildGallery(1);
  fixture.dialog.showModal = () => {
    throw new Error("dialog unavailable");
  };
  createProductGallery(fixture.gallery);

  const open = fixture.enlargeLink.dispatch("click");

  assert.equal(open.defaultPrevented, false);
  assert.equal(fixture.dialog.open, false);
  assert.equal(
    fixture.enlargeLink.getAttribute("href"),
    "/image-1.jpg",
  );
});
