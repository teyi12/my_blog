(() => {
  const root = document.querySelector("[data-cart-root]");
  if (!root || !window.fetch) return;

  const status = document.getElementById("cart-status");
  const emptyTemplate = document.getElementById("cart-empty-template");

  const announce = (message) => {
    if (status) status.textContent = message;
  };

  const formatPrice = (value) => Number(value).toFixed(2) + " €";

  const updateSummary = (data) => {
    const total = document.getElementById("cart-total");
    const count = document.getElementById("cart-count");
    if (total) total.textContent = formatPrice(data.total);
    if (count) count.textContent = data.total_articles;

    Object.entries(data.sous_totaux || {}).forEach(([id, subtotal]) => {
      const element = document.getElementById("subtotal-" + id);
      if (element) element.textContent = formatPrice(subtotal);
    });

    let checkoutLink = document.getElementById("checkout-link");
    const checkoutBlocked = document.getElementById("checkout-blocked");
    if (!data.cart_has_stock_issue && !checkoutLink && checkoutBlocked) {
      checkoutLink = document.createElement("a");
      checkoutLink.id = "checkout-link";
      checkoutLink.className = checkoutBlocked.className;
      checkoutLink.href = checkoutBlocked.dataset.checkoutUrl;
      checkoutLink.textContent = root.dataset.checkoutMessage;
      checkoutBlocked.replaceWith(checkoutLink);
    }

    if (data.total_articles === 0) {
      const layout = document.getElementById("cart-layout");
      if (layout && emptyTemplate) {
        layout.replaceWith(emptyTemplate.content.cloneNode(true));
      }
    }
  };

  const submitCartAction = async (form) => {
    const action = form.dataset.cartAction;
    const itemId = Number.parseInt(form.dataset.itemId, 10);
    const submitButton = form.querySelector('button[type="submit"]');
    const csrfToken = form.querySelector('[name="csrfmiddlewaretoken"]')?.value || "";
    const payload = { action, item_id: itemId };

    if (action === "modifier") {
      const quantityInput = form.querySelector('[name="quantite"]');
      payload.quantite = Number.parseInt(quantityInput?.value || "", 10);
      if (!Number.isInteger(payload.quantite) || payload.quantite < 1) {
        quantityInput?.focus();
        return;
      }
    }

    form.setAttribute("aria-busy", "true");
    if (submitButton) submitButton.disabled = true;

    try {
      const response = await fetch(root.dataset.updateUrl, {
        method: "POST",
        headers: {
          "X-CSRFToken": csrfToken,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });
      const data = await response.json();

      if (!data.success) {
        if (data.available !== undefined) {
          announce(root.dataset.stockMessage + " " + data.available);
        } else {
          announce(data.error || root.dataset.errorMessage);
        }
        return;
      }

      if (action === "supprimer") {
        document.getElementById("item-" + itemId)?.remove();
        announce(root.dataset.removedMessage);
      } else {
        announce(root.dataset.updatedMessage);
      }
      updateSummary(data);
    } catch {
      announce(root.dataset.errorMessage);
    } finally {
      form.removeAttribute("aria-busy");
      if (submitButton && submitButton.isConnected) submitButton.disabled = false;
    }
  };

  root.addEventListener("submit", (event) => {
    const form = event.target.closest(".cart-action-form");
    if (!form) return;
    event.preventDefault();
    submitCartAction(form);
  });
})();
