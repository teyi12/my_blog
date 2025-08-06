document.addEventListener('DOMContentLoaded', function () {
    const payBtn = document.getElementById('pay');
    if (payBtn) {
        payBtn.addEventListener('click', function () {
            fetch('/checkout/stripe/', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
                }
            })
            .then(response => response.json())
            .then(data => window.location.href = data.url)
            .catch(error => console.error('Erreur Stripe:', error));
        });
    }
});
