document.querySelectorAll("[data-product-gallery]").forEach((gallery) => {
  const mainImage = gallery.querySelector("[data-product-gallery-main]");
  const thumbnails = gallery.querySelectorAll("[data-gallery-src]");

  if (!mainImage || thumbnails.length < 2) {
    return;
  }

  thumbnails.forEach((thumbnail) => {
    thumbnail.addEventListener("click", () => {
      mainImage.src = thumbnail.dataset.gallerySrc;
      mainImage.alt = thumbnail.dataset.galleryAlt || "";

      thumbnails.forEach((candidate) => {
        const isCurrent = candidate === thumbnail;
        candidate.classList.toggle("is-active", isCurrent);
        candidate.setAttribute("aria-pressed", String(isCurrent));
      });
    });
  });
});
