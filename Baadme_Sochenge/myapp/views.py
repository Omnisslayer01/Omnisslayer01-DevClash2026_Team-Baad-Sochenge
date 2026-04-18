# Baadme_Sochenge/myapp/views.py
import requests
import json
from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from .models import User
from django.conf import settings

# Add your Luxand API Token here (ideally move this to settings.py later)
LUXAND_API_TOKEN = "03d0e1da50a046a486eb5e08920f6e00"

def signup_view(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        full_name = request.POST.get('full_name')
        
        if not User.objects.filter(email=email).exists():
            user = User.objects.create_user(email=email, password=password, full_name=full_name)
            login(request, user)
            return redirect('start_verification')
            
    return render(request, 'myapp/signup.html')

def login_view(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        user = authenticate(request, email=email, password=password)
        if user is not None:
            login(request, user)
            return redirect('dashboard')
    return render(request, 'myapp/login.html')

def logout_view(request):
    logout(request)
    return redirect('login')

@login_required
def start_verification(request):
    # If already verified, skip
    if request.user.is_verified_human:
        return redirect('dashboard')

    # Render the webcam capture page
    return render(request, 'myapp/verify.html')

@login_required
def process_liveness(request):
    """ Receives the image from the frontend and calls Luxand API """
    if request.method == 'POST' and request.FILES.get('photo'):
        uploaded_file = request.FILES['photo']
        
        url = "https://api.luxand.cloud/photo/liveness"
        headers = {"token": settings.LUXAND_API_TOKEN}
        
        # Pass the file directly to requests
        files = {"photo": (uploaded_file.name, uploaded_file.read(), uploaded_file.content_type)}
        
        try:
            response = requests.post(url, headers=headers, files=files)
            
            if response.status_code == 200:
                result = response.json()
                
                # Check if Luxand determined the photo is a real person
                if result.get("result") == "real":
                    request.user.is_verified_human = True
                    request.user.save()
                    return JsonResponse({"success": True, "message": "Verification successful!", "score": result.get("score")})
                else:
                    return JsonResponse({"success": False, "message": "Liveness check failed. Spoof detected."})
            else:
                return JsonResponse({"success": False, "message": f"API Error: {response.text}"})
                
        except Exception as e:
            return JsonResponse({"success": False, "message": str(e)})

    return JsonResponse({"success": False, "message": "Invalid request or missing photo."})

@login_required
def dashboard(request):
    return render(request, 'myapp/dashboard.html')