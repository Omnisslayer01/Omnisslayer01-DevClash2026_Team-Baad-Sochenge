from django.contrib import admin
from .models import User, Profile, Connection, Report

admin.site.register(User)
admin.site.register(Profile)
admin.site.register(Connection)
admin.site.register(Report)
