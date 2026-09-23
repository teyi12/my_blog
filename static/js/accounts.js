(function () {
  "use strict";

  function setPasswordVisibility(input, button, visible) {
    if (!input || !button) {
      return false;
    }

    input.type = visible ? "text" : "password";
    button.setAttribute("aria-pressed", visible ? "true" : "false");
    button.textContent = visible
      ? button.dataset.hideLabel
      : button.dataset.showLabel;
    return true;
  }

  function createPasswordToggle(button, root) {
    const context = root || document;
    const input = context.getElementById(button.getAttribute("aria-controls"));
    if (!input || input.type !== "password") {
      return null;
    }

    button.hidden = false;
    setPasswordVisibility(input, button, false);
    button.addEventListener("click", function () {
      setPasswordVisibility(
        input,
        button,
        button.getAttribute("aria-pressed") !== "true",
      );
    });

    return { input: input, button: button };
  }

  function createPhotoPreview(control, urlApi) {
    const input = control.querySelector('input[type="file"]');
    const preview = control.querySelector("[data-photo-preview]");
    const image = control.querySelector("[data-photo-preview-image]");
    const name = control.querySelector("[data-photo-preview-name]");
    const cancel = control.querySelector("[data-photo-preview-cancel]");
    const status = control.querySelector("[data-photo-preview-status]");
    const urls = urlApi || URL;
    let objectUrl = null;

    if (!input || !preview || !image || !name || !cancel || !status) {
      return null;
    }

    function revokePreviewUrl() {
      if (objectUrl) {
        urls.revokeObjectURL(objectUrl);
        objectUrl = null;
      }
    }

    function clearPreview(clearInput) {
      revokePreviewUrl();
      image.removeAttribute("src");
      name.textContent = "";
      preview.hidden = true;
      status.textContent = "";
      if (clearInput) {
        input.value = "";
      }
    }

    function showSelectedPhoto() {
      const file = input.files && input.files[0];
      clearPreview(false);
      if (!file || !file.type || !file.type.startsWith("image/")) {
        return false;
      }

      objectUrl = urls.createObjectURL(file);
      image.src = objectUrl;
      name.textContent = file.name;
      preview.hidden = false;
      status.textContent = image.alt;
      return true;
    }

    input.addEventListener("change", showSelectedPhoto);
    cancel.addEventListener("click", function () {
      clearPreview(true);
      input.focus();
    });

    if (typeof window !== "undefined") {
      window.addEventListener("beforeunload", revokePreviewUrl, { once: true });
    }

    return {
      clearPreview: clearPreview,
      revokePreviewUrl: revokePreviewUrl,
      showSelectedPhoto: showSelectedPhoto,
    };
  }

  function initAccountsUi(root) {
    const context = root || document;
    const passwordToggles = Array.from(
      context.querySelectorAll("[data-password-toggle]"),
    )
      .map(function (button) {
        return createPasswordToggle(button, context);
      })
      .filter(Boolean);
    const photoPreviews = Array.from(
      context.querySelectorAll("[data-photo-control]"),
    )
      .map(function (control) {
        return createPhotoPreview(control);
      })
      .filter(Boolean);
    const errorSummary = context.querySelector("[data-account-error-summary]");

    if (errorSummary) {
      errorSummary.focus({ preventScroll: true });
    }

    return {
      errorSummary: errorSummary,
      passwordToggles: passwordToggles,
      photoPreviews: photoPreviews,
    };
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = {
      createPasswordToggle: createPasswordToggle,
      createPhotoPreview: createPhotoPreview,
      initAccountsUi: initAccountsUi,
      setPasswordVisibility: setPasswordVisibility,
    };
  }

  if (typeof document !== "undefined") {
    initAccountsUi(document);
  }
})();
