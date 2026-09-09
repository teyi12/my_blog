from .donations import donations_are_available


def donation_availability(request):
    return {"donations_available": donations_are_available()}
