from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import *

router = DefaultRouter()
router.register('profiles', ProfileViewSet)
router.register('posts', PostViewSet)
router.register('connections', ConnectionViewSet)
router.register('jobs', JobViewSet)

urlpatterns = [
    path('', include(router.urls)),
]