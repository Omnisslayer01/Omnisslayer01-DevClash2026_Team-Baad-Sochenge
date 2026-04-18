from django.contrib import admin

from django.contrib import admin
from .models import Profile, Post, Connection, JobOpportunity

admin.site.register(Profile)
admin.site.register(Post)
admin.site.register(Connection)
admin.site.register(JobOpportunity)