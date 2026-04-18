# Baadme_Sochenge/myapp/urls.py
from django.urls import path
from . import views

urlpatterns =[
    path('signup/', views.signup_view, name='signup'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('verify/', views.start_verification, name='start_verification'),
    path('process-liveness/', views.process_liveness, name='process_liveness'), # New endpoint
    path('dashboard/', views.dashboard, name='dashboard'),
]