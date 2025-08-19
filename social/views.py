from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, get_object_or_404
from django.contrib.auth import get_user_model

User = get_user_model()

@login_required
def follow(request, user_id):
    user = get_object_or_404(User, id=user_id)
    if user != request.user:
        user.followers.get_or_create(follower=request.user, following=user)
    return redirect(request.META.get("HTTP_REFERER", "/"))

@login_required
def unfollow(request, user_id):
    user = get_object_or_404(User, id=user_id)
    user.followers.filter(follower=request.user, following=user).delete()
    return redirect(request.META.get("HTTP_REFERER", "/"))
