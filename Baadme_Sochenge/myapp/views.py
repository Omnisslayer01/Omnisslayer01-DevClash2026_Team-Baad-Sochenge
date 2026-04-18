# from rest_framework import viewsets
# from rest_framework.permissions import IsAuthenticated
# from .models import Profile, Post, Connection, JobOpportunity
# from .serializers import *


# # 🔐 Custom permission
# from rest_framework.permissions import BasePermission

# class IsVerifiedUser(BasePermission):
#     def has_permission(self, request, view):
#         return request.user.profile.is_verified


# # 👤 Profile API
# class ProfileViewSet(viewsets.ModelViewSet):
#     queryset = Profile.objects.all()
#     serializer_class = ProfileSerializer


# # 📝 Post API
# class PostViewSet(viewsets.ModelViewSet):
#     queryset = Post.objects.all()
#     serializer_class = PostSerializer


# # 🤝 Connection API
# class ConnectionViewSet(viewsets.ModelViewSet):
#     queryset = Connection.objects.all()
#     serializer_class = ConnectionSerializer


# # 💼 Job API (ONLY VERIFIED USERS)
# class JobViewSet(viewsets.ModelViewSet):
#     queryset = JobOpportunity.objects.all()
#     serializer_class = JobSerializer
#     permission_classes = [IsAuthenticated, IsVerifiedUser]
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated, BasePermission
from .models import Profile, Post, Connection, JobOpportunity
from .serializers import ProfileSerializer, PostSerializer, ConnectionSerializer, JobSerializer


# 🔐 Custom permission (SAFE VERSION)
class IsVerifiedUser(BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if not hasattr(request.user, 'profile'):
            return False
        return request.user.profile.is_verified


# 👤 Profile API
class ProfileViewSet(viewsets.ModelViewSet):
    queryset = Profile.objects.all()
    serializer_class = ProfileSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


# 📝 Post API (Networking Feed)
class PostViewSet(viewsets.ModelViewSet):
    queryset = Post.objects.all()
    serializer_class = PostSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


# 🤝 Connection API
class ConnectionViewSet(viewsets.ModelViewSet):
    queryset = Connection.objects.all()
    serializer_class = ConnectionSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(sender=self.request.user)


# 💼 Job API (ONLY VERIFIED USERS)
class JobViewSet(viewsets.ModelViewSet):
    queryset = JobOpportunity.objects.all()
    serializer_class = JobSerializer
    permission_classes = [IsAuthenticated, IsVerifiedUser]

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)