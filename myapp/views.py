import json
import secrets
import requests
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseForbidden
from django.contrib import messages
from django.db.models import Count
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.core.mail import send_mail
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from accounts.models import (
    Connection,
    Profile,
    EmployeeAffiliationRequest,
    CLAIM_EMPLOYEE,
    CLAIM_OWNER,
    CLAIM_ORGANISER,
)
from accounts.services.trust_service import update_trust_score
from accounts.services.sandbox_service import verify_identity_sandbox, mark_profile_sandbox_time
from verification.facade import run_ownership_verification
from verification.repositories import get_company_by_cin, get_tax_by_gstin
from .models import (
    Event,
    Registration,
    Post,
    Comment,
    Like,
    JobOpportunity,
    JobApplication,
    Promotion,
)
from django.conf import settings

User = get_user_model()

PROMOTION_TRUST_THRESHOLD = 70
OWNER_VERIFICATION_SAMPLES = [
    {
        "label": "Acme Innovations",
        "cin": "U74999DL2019PTC346789",
        "gstin": "07AABCU9601R1ZV",
        "company_name": "Acme Innovations Private Limited",
        "claimant_name": "Rajesh Kumar Sharma",
    },
    {
        "label": "Heritage Textiles",
        "cin": "L17110MH1973PLC019786",
        "gstin": "27AAPFU0939F1ZV",
        "company_name": "Heritage Textiles Limited",
        "claimant_name": "Anil Kapoor",
    },
    {
        "label": "Southern Grid Energy",
        "cin": "U40109TN2020PTC131415",
        "gstin": "33AABCS1234E1Z1",
        "company_name": "Southern Grid Energy Private Limited",
        "claimant_name": "Karthik Iyer",
    },
    {
        "label": "Scammer Attempt",
        "cin": "U74999DL2019PTC346789",
        "gstin": "07AABCU9601R1ZV",
        "company_name": "Acme Innovations Private Limited",
        "claimant_name": "Fake Hacker Name",
    },
]


def signup_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        full_name = request.POST.get('full_name')

        if not User.objects.filter(username=username).exists():
            user = User.objects.create_user(
                username=username,
                password=password,
                full_name=full_name,
                email=request.POST.get("email", ""),
                role=request.POST.get("role", "professional"),
            )
            Profile.objects.get_or_create(user=user, defaults={"name": full_name})
            login(request, user)
            return redirect('start_verification')

        messages.error(request, "Username already exists.")

    return render(request, 'myapp/signup.html')


def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('home')
        messages.error(request, "Invalid credentials.")

    return render(request, 'myapp/login.html')


def logout_view(request):
    logout(request)
    return redirect('login')

@login_required
def start_verification(request):
    if request.user.is_verified_human:
        return redirect('home')

    return render(request, 'myapp/verify.html')


@login_required
def process_liveness(request):
    if request.method == 'POST' and request.FILES.get('photo'):
        uploaded_file = request.FILES['photo']

        url = "https://api.luxand.cloud/photo/liveness"
        headers = {"token": getattr(settings, "LUXAND_API_TOKEN", "")}
        files = {"photo": (uploaded_file.name, uploaded_file.read(), uploaded_file.content_type)}

        challenge_completed = request.POST.get("challenge_completed") == "true"
        if not challenge_completed:
            return JsonResponse({"success": False, "message": "Liveness challenge not completed."})

        try:
            if headers["token"]:
                response = requests.post(url, headers=headers, files=files, timeout=15)
                if response.status_code == 200:
                    result = response.json()
                    if result.get("result") == "real":
                        request.user.is_verified_human = True
                        request.user.is_verified = True
                        update_trust_score(request.user)
                        return JsonResponse({"success": True, "message": "Verification successful!", "score": result.get("score")})
                    return JsonResponse({"success": False, "message": "Liveness check failed. Spoof detected."})
                return JsonResponse({"success": False, "message": f"API Error: {response.text}"})

            request.user.is_verified_human = True
            request.user.is_verified = True
            update_trust_score(request.user)
            return JsonResponse({"success": True, "message": "Verification successful by challenge flow."})
        except requests.RequestException:
            return JsonResponse({"success": False, "message": "Verification service unavailable. Try again."})

    return JsonResponse({"success": False, "message": "Invalid request or missing photo."})


@login_required
def home(request):
    profile, _ = Profile.objects.get_or_create(user=request.user, defaults={"name": request.user.full_name or request.user.username})

    if request.method == "POST" and request.POST.get("form_type") == "post":
        content = request.POST.get("content", "").strip()
        if content:
            Post.objects.create(author=request.user, content=content, image=request.FILES.get("image"))
            messages.success(request, "Post created.")
        return redirect("home")

    posts = Post.objects.select_related("author").prefetch_related("comments", "likes")
    suggested_users = User.objects.exclude(id=request.user.id)[:8]
    sent_connections = set(
        Connection.objects.filter(user_from=request.user).values_list("user_to_id", flat=True)
    )
    pending_requests = Connection.objects.filter(user_to=request.user, status="pending").select_related("user_from")
    accepted_connections = Connection.objects.filter(
        user_from=request.user, status="accepted"
    ).count()
    update_trust_score(request.user)
    context = {
        "posts": posts,
        "profile": profile,
        "suggested_users": suggested_users,
        "sent_connections": sent_connections,
        "pending_requests": pending_requests,
        "accepted_connections": accepted_connections,
        "can_start_fundraiser": profile.is_verified_user,
        "is_event_organizer": profile.is_event_organizer,
    }
    return render(request, "myapp/home.html", context)


@login_required
def like_post(request, post_id):
    post = get_object_or_404(Post, id=post_id)
    Like.objects.get_or_create(post=post, user=request.user)
    return redirect("home")


@login_required
def add_comment(request, post_id):
    post = get_object_or_404(Post, id=post_id)
    if request.method == "POST":
        content = request.POST.get("content", "").strip()
        if content:
            Comment.objects.create(post=post, author=request.user, content=content)
    return redirect("home")


@login_required
def share_post(request, post_id):
    source = get_object_or_404(Post, id=post_id)
    Post.objects.create(author=request.user, content=f"Shared: {source.content}")
    source.share_count += 1
    source.save(update_fields=["share_count"])
    return redirect("home")


@login_required
def send_connection_request(request, user_id):
    target = get_object_or_404(User, id=user_id)
    if target != request.user:
        Connection.objects.get_or_create(user_from=request.user, user_to=target, defaults={"status": "pending"})
    return redirect("home")


@login_required
def respond_connection_request(request, connection_id, action):
    connection = get_object_or_404(Connection, id=connection_id, user_to=request.user)
    if action == "accept":
        connection.status = "accepted"
        connection.save(update_fields=["status"])
    elif action == "reject":
        connection.delete()
    update_trust_score(request.user)
    return redirect("home")


@login_required
def opportunities(request):
    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        if title:
            JobOpportunity.objects.create(
                posted_by=request.user,
                title=title,
                company=request.POST.get("company", "").strip(),
                location=request.POST.get("location", "").strip(),
                description=request.POST.get("description", "").strip(),
                is_remote=bool(request.POST.get("is_remote")),
            )
            messages.success(request, "Opportunity posted.")
            return redirect("opportunities")

    jobs = JobOpportunity.objects.select_related("posted_by").annotate(
        total_applications=Count("applications")
    )
    return render(request, "myapp/opportunities.html", {"jobs": jobs})


@login_required
def apply_job(request, job_id):
    job = get_object_or_404(JobOpportunity, id=job_id)
    if request.method == "POST":
        JobApplication.objects.get_or_create(
            job=job, applicant=request.user, defaults={"note": request.POST.get("note", "")}
        )
        messages.success(request, "Application submitted.")
    return redirect("opportunities")


@login_required
def event_list(request):
    profile, _ = Profile.objects.get_or_create(
        user=request.user,
        defaults={"name": request.user.full_name or request.user.username},
    )
    if request.method == "POST":
        if not profile.is_verified_user:
            return HttpResponseForbidden(
                "Become a verified user (employee, owner, or organiser path on Profile → Upgrade) to host events."
            )

        Event.objects.create(
            title=request.POST.get("title", ""),
            description=request.POST.get("description", ""),
            date=request.POST.get("date"),
            location=request.POST.get("location", ""),
            banner=request.FILES.get("banner"),
            ticket_price=request.POST.get("ticket_price") or 0,
            max_attendees=request.POST.get("max_attendees") or 100,
            created_by=request.user,
        )
        messages.success(request, "Event published.")
        return redirect("events")

    events = Event.objects.select_related("created_by")
    return render(
        request,
        "myapp/events.html",
        {
            "events": events,
            "profile": profile,
            "can_host_events": profile.is_verified_user,
            "is_event_organizer": profile.is_event_organizer,
        },
    )


@login_required
def join_event(request, event_id):
    event = Event.objects.get(id=event_id)
    if request.method == "POST":
        Registration.objects.get_or_create(
            user=request.user,
            event=event,
            defaults={"ticket_count": int(request.POST.get("ticket_count", 1))},
        )
        messages.success(request, "Ticket booked.")
    return redirect("events")


@login_required
def promotions(request):
    update_trust_score(request.user)
    can_post = request.user.is_verified_human and request.user.trust_score >= PROMOTION_TRUST_THRESHOLD
    if request.method == "POST":
        if not can_post:
            return HttpResponseForbidden("Complete profile and verification to unlock promotions.")

        Promotion.objects.create(
            owner=request.user,
            title=request.POST.get("title", ""),
            promotion_type=request.POST.get("promotion_type", "post_boost"),
            target_url=request.POST.get("target_url", ""),
            budget=request.POST.get("budget") or 0,
            content=request.POST.get("content", ""),
        )
        messages.success(request, "Promotion created.")
        return redirect("promotions")

    promotions_qs = Promotion.objects.select_related("owner")
    context = {
        "promotions": promotions_qs,
        "can_post": can_post,
        "promotion_threshold": PROMOTION_TRUST_THRESHOLD,
    }
    return render(request, "myapp/promotions.html", context)


@login_required
def owner_verification_lab(request):
    profile, _ = Profile.objects.get_or_create(
        user=request.user,
        defaults={"name": request.user.full_name or request.user.username},
    )
    if request.user.role != "company" or not profile.is_boss:
        return HttpResponseForbidden("Only company boss accounts can use owner verification.")

    selected_sample = request.GET.get("sample", "0")
    try:
        selected_index = max(0, min(int(selected_sample), len(OWNER_VERIFICATION_SAMPLES) - 1))
    except ValueError:
        selected_index = 0

    initial = OWNER_VERIFICATION_SAMPLES[selected_index]
    form_data = {
        "cin": initial["cin"],
        "gstin": initial["gstin"],
        "company_name": initial["company_name"],
        "claimant_name": initial["claimant_name"],
    }
    results = {}

    if request.method == "POST":
        form_data = {
            "cin": request.POST.get("cin", "").strip().upper(),
            "gstin": request.POST.get("gstin", "").strip().upper(),
            "company_name": request.POST.get("company_name", "").strip(),
            "claimant_name": request.POST.get("claimant_name", "").strip(),
        }

        company = get_company_by_cin(form_data["cin"]) if form_data["cin"] else None
        tax = get_tax_by_gstin(form_data["gstin"]) if form_data["gstin"] else None
        ownership = run_ownership_verification(
            cin=form_data["cin"],
            gstin=form_data["gstin"],
            company_name=form_data["company_name"],
            claimant_name=form_data["claimant_name"],
            claimant_id=str(request.user.id),
            apply_realism=False,
        )

        should_upgrade_company_verification = (
            ownership.get("success")
            and ownership.get("decision") == "Verified"
            and int(ownership.get("trust_score") or 0) >= 80
            and bool(company)
            and bool(tax)
        )
        if should_upgrade_company_verification and not profile.is_company_verified:
            profile.is_company_verified = True
            # Keep profile company in sync when verification is accepted.
            profile.company = form_data["company_name"] or profile.company
            profile.save(update_fields=["is_company_verified", "company"])
            messages.success(
                request,
                "Company ownership verified. `is_company_verified` has been set to True.",
            )
        elif ownership.get("success") and ownership.get("decision") != "Verified":
            messages.warning(
                request,
                f"Ownership decision: {ownership.get('decision')}. Company verification was not auto-approved.",
            )

        results = {
            "company": {
                "success": bool(company),
                "data": company,
            },
            "tax": {
                "success": bool(tax),
                "data": tax,
            },
            "ownership": ownership,
        }

    context = {
        "profile": profile,
        "samples": OWNER_VERIFICATION_SAMPLES,
        "selected_index": selected_index,
        "form_data": form_data,
        "results": results,
    }
    return render(request, "myapp/owner_verification.html", context)


@login_required
def start_fundraiser(request):
    profile, _ = Profile.objects.get_or_create(
        user=request.user,
        defaults={"name": request.user.full_name or request.user.username},
    )
    if not profile.is_verified_user:
        return HttpResponseForbidden(
            "Fundraisers are available to verified users only. Complete an upgrade path under Profile → Upgrade rank."
        )

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        target_amount = request.POST.get("target_amount", "").strip()
        pitch = request.POST.get("pitch", "").strip()
        if title and target_amount and pitch:
            messages.success(
                request,
                f"Fundraiser '{title}' submitted (demo mode). Investors can now review this campaign.",
            )
            return redirect("start_fundraiser")
        messages.error(request, "Please fill title, target amount, and pitch.")

    return render(request, "myapp/start_fundraiser.html", {"profile": profile})


@login_required
def organizer_hub(request):
    profile, _ = Profile.objects.get_or_create(
        user=request.user,
        defaults={"name": request.user.full_name or request.user.username},
    )
    organizer = getattr(request.user, "event_organizer_profile", None)
    return render(
        request,
        "myapp/organizer_hub.html",
        {"profile": profile, "organizer": organizer},
    )


def _sandbox_api_authorized(request):
    expected = (getattr(settings, "SANDBOX_API_KEY", "") or "").strip()
    if not expected:
        return True
    got = request.headers.get("X-Sandbox-Key", "").strip()
    if len(got) != len(expected):
        return False
    return secrets.compare_digest(got, expected)


@csrf_exempt
@require_http_methods(["POST"])
def sandbox_verify_identity_api(request):
    """
    Sandbox JSON API: checks name / claim hint to reduce obviously fake signups (demo rules).
    Send header X-Sandbox-Key when SANDBOX_API_KEY is set in settings.
    """
    if not _sandbox_api_authorized(request):
        return JsonResponse({"verified": False, "error": "invalid_sandbox_key"}, status=401)
    try:
        payload = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"verified": False, "error": "invalid_json"}, status=400)
    claim_type = (payload.get("claim_type") or "employee").strip().lower()
    full_name = (payload.get("full_name") or "").strip()
    hint = (payload.get("document_hint") or "").strip()
    if not full_name:
        return JsonResponse({"verified": False, "error": "full_name_required"}, status=400)
    result = verify_identity_sandbox(
        claim_type=claim_type, full_name=full_name, document_hint=hint
    )
    return JsonResponse(
        {
            "verified": result["verified"],
            "reference": result.get("reference", ""),
            "reason": result.get("reason", ""),
        }
    )


def _send_employee_affiliation_email(request, affiliation):
    approve = request.build_absolute_uri(
        reverse(
            "employee_affiliation_action",
            kwargs={"token": str(affiliation.token), "action": "approve"},
        )
    )
    reject = request.build_absolute_uri(
        reverse(
            "employee_affiliation_action",
            kwargs={"token": str(affiliation.token), "action": "reject"},
        )
    )
    body = (
        f"A user ({affiliation.user.username}) claims to be an employee of {affiliation.company_name}.\n\n"
        f"If this is legitimate, open APPROVE (they will get a green badge and verified-user access):\n{approve}\n\n"
        f"If this person is not with your organisation, open REJECT:\n{reject}\n"
    )
    send_mail(
        subject=f"[Baadme Sochenge] Employment check for {affiliation.user.username}",
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[affiliation.company_email],
        fail_silently=False,
    )


def employee_affiliation_action(request, token, action):
    aff = get_object_or_404(
        EmployeeAffiliationRequest,
        token=token,
        status=EmployeeAffiliationRequest.STATUS_PENDING,
    )
    profile, _ = Profile.objects.get_or_create(
        user=aff.user,
        defaults={"name": aff.user.full_name or aff.user.username},
    )
    if action == "approve":
        aff.status = EmployeeAffiliationRequest.STATUS_APPROVED
        aff.save(update_fields=["status"])
        profile.employee_company_confirmed = True
        profile.is_verified_user = True
        profile.is_company_email_verified = True
        profile.save(
            update_fields=[
                "employee_company_confirmed",
                "is_verified_user",
                "is_company_email_verified",
            ]
        )
        update_trust_score(aff.user)
        return render(
            request,
            "myapp/affiliation_result.html",
            {"title": "Approved", "message": "This employee is now verified on the platform."},
        )
    if action == "reject":
        aff.status = EmployeeAffiliationRequest.STATUS_REJECTED
        aff.save(update_fields=["status"])
        profile.employee_company_confirmed = False
        profile.is_verified_user = False
        profile.save(update_fields=["employee_company_confirmed", "is_verified_user"])
        update_trust_score(aff.user)
        return render(
            request,
            "myapp/affiliation_result.html",
            {
                "title": "Rejected",
                "message": "The affiliation request was rejected. The user stays on yellow/blue tier until trust improves or they re-apply.",
            },
        )
    return HttpResponseForbidden("Invalid action.")


@login_required
def account_profile(request):
    profile, _ = Profile.objects.get_or_create(
        user=request.user,
        defaults={"name": request.user.full_name or request.user.username},
    )
    if request.method == "POST":
        profile.name = request.POST.get("name", "")
        profile.headline = request.POST.get("headline", "")
        profile.location = request.POST.get("location", "")
        profile.skills = request.POST.get("skills", "")
        profile.company = request.POST.get("company", "")
        profile.bio = request.POST.get("bio", "")
        profile.save()
        update_trust_score(request.user)
        messages.success(request, "Profile saved.")
        return redirect("account_profile")

    pending_aff = (
        EmployeeAffiliationRequest.objects.filter(
            user=request.user, status=EmployeeAffiliationRequest.STATUS_PENDING
        )
        .order_by("-created_at")
        .first()
    )
    return render(
        request,
        "myapp/account_profile.html",
        {
            "profile": profile,
            "pending_affiliation": pending_aff,
        },
    )


@login_required
def profile_rank_upgrade(request):
    profile, _ = Profile.objects.get_or_create(
        user=request.user,
        defaults={"name": request.user.full_name or request.user.username},
    )
    if request.method == "POST":
        claim = (request.POST.get("claim_type") or "").strip().lower()
        display_name = (profile.name or request.user.full_name or request.user.username).strip()

        if claim == CLAIM_EMPLOYEE:
            aadhar_hint = (request.POST.get("emp_aadhar_hint") or "").strip()
            company_name = request.POST.get("emp_company_name", "").strip()
            company_email = request.POST.get("emp_company_email", "").strip()
            emp_doc = request.FILES.get("emp_gov_id")
            if not company_name or not company_email or not emp_doc:
                messages.error(request, "Employee path requires company name, company email, and Aadhaar / ID upload.")
                return redirect("profile_rank_upgrade")
            sb = verify_identity_sandbox(
                claim_type="employee",
                full_name=display_name,
                document_hint=aadhar_hint,
            )
            if not sb["verified"]:
                messages.error(request, sb.get("reason") or "Sandbox identity check failed.")
                return redirect("profile_rank_upgrade")
            profile.company = company_name
            profile.company_email = company_email
            profile.gov_id = emp_doc
            profile.claim_type = CLAIM_EMPLOYEE
            profile.is_verified_user = False
            profile.employee_company_confirmed = False
            mark_profile_sandbox_time(profile)
            profile.sandbox_reference = sb.get("reference", "")
            profile.save()
            aff = EmployeeAffiliationRequest.objects.create(
                user=request.user,
                company_name=company_name,
                company_email=company_email,
            )
            _send_employee_affiliation_email(request, aff)
            messages.success(
                request,
                "Sandbox check passed. We emailed your company contact — when they approve the link, you become a verified user (green).",
            )
            return redirect("account_profile")

        if claim == CLAIM_OWNER:
            cin = request.POST.get("owner_cin", "").strip().upper()
            gstin = request.POST.get("owner_gstin", "").strip().upper()
            company_name = request.POST.get("owner_company_name", "").strip()
            if not cin or not gstin or not company_name:
                messages.error(request, "Owner path requires company name, CIN, and GSTIN.")
                return redirect("profile_rank_upgrade")
            company = get_company_by_cin(cin) if cin else None
            tax = get_tax_by_gstin(gstin) if gstin else None
            ownership = run_ownership_verification(
                cin=cin,
                gstin=gstin,
                company_name=company_name,
                claimant_name=display_name,
                claimant_id=str(request.user.id),
                apply_realism=False,
            )
            profile.claim_type = CLAIM_OWNER
            profile.owner_cin = cin
            profile.owner_gstin = gstin
            profile.company = company_name or profile.company
            if request.FILES.get("company_docs"):
                profile.company_docs = request.FILES["company_docs"]
            if request.POST.get("is_boss"):
                profile.is_boss = True
            should_upgrade = (
                ownership.get("success")
                and ownership.get("decision") == "Verified"
                and int(ownership.get("trust_score") or 0) >= 80
                and bool(company)
                and bool(tax)
            )
            if should_upgrade:
                profile.is_company_verified = True
                profile.is_verified_user = True
                messages.success(
                    request,
                    "Company records and ownership check passed. You are now a verified user (fundraiser + events).",
                )
            else:
                profile.is_verified_user = False
                messages.warning(
                    request,
                    f"Ownership decision: {ownership.get('decision')!r}. "
                    "Documents may still be reviewed manually; verified-user access was not granted.",
                )
            profile.save()
            update_trust_score(request.user)
            return redirect("account_profile")

        if claim == CLAIM_ORGANISER:
            org_hint = (request.POST.get("org_document_hint") or "").strip()
            org_doc = request.FILES.get("org_gov_id")
            if not org_doc:
                messages.error(request, "Organiser path requires a government ID upload.")
                return redirect("profile_rank_upgrade")
            sb = verify_identity_sandbox(
                claim_type="organiser",
                full_name=display_name,
                document_hint=org_hint,
            )
            if not sb["verified"]:
                messages.error(request, sb.get("reason") or "Sandbox identity check failed.")
                return redirect("profile_rank_upgrade")
            profile.gov_id = org_doc
            profile.claim_type = CLAIM_ORGANISER
            profile.is_gov_id_verified = True
            profile.is_verified_user = True
            mark_profile_sandbox_time(profile)
            profile.sandbox_reference = sb.get("reference", "")
            profile.save()
            update_trust_score(request.user)
            messages.success(
                request,
                "Government ID recorded and sandbox verification passed. You are a verified user and can post events.",
            )
            return redirect("account_profile")

        messages.error(request, "Choose a valid upgrade path.")
        return redirect("profile_rank_upgrade")

    return render(request, "myapp/profile_rank_upgrade.html", {"profile": profile})


@login_required
def dashboard(request):
    return redirect("home")