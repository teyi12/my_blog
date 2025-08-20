from django.shortcuts import render

def dashboard(request):
    stats = {
        "revenus_publicite": 120.50,
        "revenus_affiliation": 89.30,
        "abonnements_premium": 45,
    }

    # Données pour graphique linéaire
    revenus_mensuels = {
        "labels": ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin"],
        "publicite": [50, 80, 120, 150, 200, 250],
        "affiliation": [30, 40, 60, 80, 90, 100],
        "premium": [10, 20, 30, 35, 40, 45],
    }

    # Données pour le camembert
    repartition_revenus = {
        "labels": ["Publicité", "Affiliation", "Premium"],
        "data": [stats["revenus_publicite"], stats["revenus_affiliation"], stats["abonnements_premium"]],
    }

    return render(
        request,
        "monetization/dashboard.html",
        {
            "stats": stats,
            "revenus_mensuels": revenus_mensuels,
            "repartition_revenus": repartition_revenus,
        },
    )
