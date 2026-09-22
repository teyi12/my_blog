(function () {
  "use strict";

  function isActivationKey(key) {
    return key === "Enter" || key === " ";
  }

  function getNavigationIndex(key, currentIndex, total) {
    if (total < 1) {
      return null;
    }

    if (key === "ArrowLeft") {
      return Math.max(0, currentIndex - 1);
    }
    if (key === "ArrowRight") {
      return Math.min(total - 1, currentIndex + 1);
    }
    if (key === "Home") {
      return 0;
    }
    if (key === "End") {
      return total - 1;
    }
    return null;
  }

  function createProductGallery(gallery) {
    const mainImage = gallery.querySelector("[data-product-gallery-main]");
    const enlargeLink = gallery.querySelector("[data-gallery-enlarge]");
    const thumbnails = Array.from(
      gallery.querySelectorAll("[data-gallery-thumbnail]"),
    );
    const galleryStatus = gallery.querySelector("[data-gallery-status]");
    const dialog = gallery.querySelector("[data-gallery-dialog]");
    const dialogImage = gallery.querySelector("[data-gallery-dialog-image]");
    const dialogCounter = gallery.querySelector(
      "[data-gallery-dialog-counter]",
    );
    const closeButton = gallery.querySelector("[data-gallery-dialog-close]");

    if (!mainImage || !enlargeLink || thumbnails.length === 0) {
      return null;
    }

    let currentIndex = Math.max(
      0,
      thumbnails.findIndex(
        (thumbnail) => thumbnail.getAttribute("aria-current") === "true",
      ),
    );
    let dialogOpener = null;

    function activeThumbnail() {
      return thumbnails[currentIndex];
    }

    function updateDialogImage() {
      if (!dialogImage || !dialogCounter) {
        return;
      }

      const thumbnail = activeThumbnail();
      dialogImage.setAttribute("src", thumbnail.dataset.gallerySrc);
      dialogImage.alt = thumbnail.dataset.galleryAlt || "";
      dialogCounter.textContent = thumbnail.dataset.galleryStatus || "";
    }

    function selectImage(index, options) {
      const settings = options || {};
      if (index < 0 || index >= thumbnails.length) {
        return false;
      }

      currentIndex = index;
      const thumbnail = activeThumbnail();
      mainImage.setAttribute("src", thumbnail.dataset.gallerySrc);
      mainImage.alt = thumbnail.dataset.galleryAlt || "";
      enlargeLink.setAttribute("href", thumbnail.dataset.gallerySrc);

      thumbnails.forEach((candidate, candidateIndex) => {
        const isCurrent = candidateIndex === currentIndex;
        candidate.classList.toggle("is-active", isCurrent);
        if (isCurrent) {
          candidate.setAttribute("aria-current", "true");
        } else {
          candidate.removeAttribute("aria-current");
        }
      });

      if (galleryStatus && settings.announce !== false) {
        galleryStatus.textContent = thumbnail.dataset.galleryStatus || "";
      }
      if (dialog && dialog.open) {
        updateDialogImage();
      }
      return true;
    }

    function selectFromKeyboard(event, index) {
      if (selectImage(index)) {
        event.preventDefault();
      }
    }

    thumbnails.forEach((thumbnail, index) => {
      thumbnail.addEventListener("click", (event) => {
        if (selectImage(index)) {
          event.preventDefault();
        }
      });

      thumbnail.addEventListener("keydown", (event) => {
        if (isActivationKey(event.key)) {
          selectFromKeyboard(event, index);
          return;
        }

        const targetIndex = getNavigationIndex(
          event.key,
          currentIndex,
          thumbnails.length,
        );
        if (targetIndex === null) {
          return;
        }

        selectFromKeyboard(event, targetIndex);
        thumbnails[targetIndex].focus();
      });
    });

    enlargeLink.addEventListener("click", (event) => {
      if (
        !dialog ||
        !dialogImage ||
        !dialogCounter ||
        !closeButton ||
        typeof dialog.showModal !== "function"
      ) {
        return;
      }

      dialogOpener = enlargeLink;
      updateDialogImage();
      try {
        dialog.showModal();
        event.preventDefault();
        if (galleryStatus) {
          galleryStatus.setAttribute("aria-live", "off");
        }
        dialogCounter.setAttribute("aria-live", "polite");
        closeButton.focus({ preventScroll: true });
      } catch (error) {
        dialogOpener = null;
      }
    });

    if (dialog && closeButton) {
      closeButton.addEventListener("click", () => dialog.close());

      dialog.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          dialog.close();
          return;
        }

        const targetIndex = getNavigationIndex(
          event.key,
          currentIndex,
          thumbnails.length,
        );
        if (targetIndex !== null) {
          selectFromKeyboard(event, targetIndex);
        }
      });

      dialog.addEventListener("click", (event) => {
        if (event.target === dialog) {
          dialog.close();
        }
      });

      dialog.addEventListener("close", () => {
        if (dialogImage) {
          dialogImage.removeAttribute("src");
        }
        if (dialogCounter) {
          dialogCounter.setAttribute("aria-live", "off");
        }
        if (galleryStatus) {
          galleryStatus.setAttribute("aria-live", "polite");
        }
        if (dialogOpener) {
          dialogOpener.focus({ preventScroll: true });
          dialogOpener = null;
        }
      });
    }

    selectImage(currentIndex, { announce: false });

    return {
      getCurrentIndex: () => currentIndex,
      selectImage,
    };
  }

  function initProductGalleries(root) {
    const context = root || document;
    return Array.from(context.querySelectorAll("[data-product-gallery]"))
      .filter((gallery) => !gallery.dataset.galleryInitialized)
      .map((gallery) => {
        gallery.dataset.galleryInitialized = "true";
        return createProductGallery(gallery);
      })
      .filter(Boolean);
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = {
      createProductGallery,
      getNavigationIndex,
      initProductGalleries,
      isActivationKey,
    };
  }

  if (typeof document !== "undefined") {
    initProductGalleries(document);
  }
})();
