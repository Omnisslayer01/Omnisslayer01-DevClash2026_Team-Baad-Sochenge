# Baadme_Sochenge/myapp/urls.py
from django.urls import path
from . import views

urlpatterns =[
    path('', views.home, name='home'),
    path('home/', views.home, name='home_alias'),
    path('feed/', views.home, name='feed_alias'),
    path('signup/', views.signup_view, name='signup'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('verify/', views.start_verification, name='start_verification'),
    path('process-liveness/', views.process_liveness, name='process_liveness'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('post/<int:post_id>/like/', views.like_post, name='like_post'),
    path('post/<int:post_id>/comment/', views.add_comment, name='add_comment'),
    path('post/<int:post_id>/share/', views.share_post, name='share_post'),
    path('connect/<int:user_id>/', views.send_connection_request, name='send_connection_request'),
    path('connect/respond/<int:connection_id>/<str:action>/', views.respond_connection_request, name='respond_connection_request'),
    path('opportunities/', views.opportunities, name='opportunities'),
    path('opportunities/<int:job_id>/apply/', views.apply_job, name='apply_job'),
    path('events/', views.event_list, name='events'),
    path('events/join/<int:event_id>/', views.join_event, name='join_event'),
    path('promotions/', views.promotions, name='promotions'),
    path("owner-verification/", views.owner_verification_lab, name="owner_verification_lab"),
    path("fundraiser/start/", views.start_fundraiser, name="start_fundraiser"),
    path("organizer/", views.organizer_hub, name="organizer_hub"),
    path("profile/", views.account_profile, name="account_profile"),
    path("profile/upgrade/", views.profile_rank_upgrade, name="profile_rank_upgrade"),
    path(
        "verify-employment/<uuid:token>/<str:action>/",
        views.employee_affiliation_action,
        name="employee_affiliation_action",
    ),
    path(
        "api/sandbox/v1/verify-identity/",
        views.sandbox_verify_identity_api,
        name="sandbox_verify_identity",
    ),
]