from rest_framework import serializers
from .models import Profile, Post, Connection, JobOpportunity


class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = '__all__'


class PostSerializer(serializers.ModelSerializer):
    class Meta:
        model = Post
        fields = '__all__'


class ConnectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Connection
        fields = '__all__'


class JobSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobOpportunity
        fields = '__all__'