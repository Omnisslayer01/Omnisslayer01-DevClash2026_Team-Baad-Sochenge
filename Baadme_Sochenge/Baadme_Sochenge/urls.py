from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect

# Quick lambda redirect for the home page
def home_redirect(request):
    return redirect('signup')

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', home_redirect), # Redirects '/' to signup
    path('', include('myapp.urls')),
]