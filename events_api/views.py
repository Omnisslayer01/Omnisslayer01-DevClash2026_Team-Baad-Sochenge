from __future__ import annotations

import uuid

from django.db import transaction
from django.db.models import Case, IntegerField, When
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response

from events_api import razorpay_service, services, wallet_services
from events_api.models import (
    Event,
    EventEnrollment,
    EventFraudReport,
    EventGrievance,
    OrganizerPaymentAccount,
    WalletPayoutRequest,
    WalletTopUp,
)
from events_api.permissions import IsOrganizerOrReadOnly, IsVerifiedIdentityForEventCreate
from events_api.serializers import (
    EnrollSerializer,
    EventCreateSerializer,
    EventEnrollmentSerializer,
    EventGrievanceSerializer,
    EventListSerializer,
    FraudReportSerializer,
    OrganizerPaymentAccountSerializer,
    RazorpayTopUpOrderSerializer,
    RazorpayTopUpVerifySerializer,
    ScanQrSerializer,
    WalletPayoutBodySerializer,
    WalletPayoutRequestSerializer,
    enroll_user_in_event,
)


class OrganizerPaymentAccountViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = OrganizerPaymentAccountSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return OrganizerPaymentAccount.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class EventViewSet(viewsets.ModelViewSet):
    queryset = Event.objects.select_related("organizer", "payment_account").all()
    permission_classes = [IsVerifiedIdentityForEventCreate, IsOrganizerOrReadOnly]

    def get_queryset(self):
        qs = (
            Event.objects.select_related("organizer", "payment_account")
            .filter(
                status__in=(
                    Event.STATUS_ACTIVE,
                    Event.STATUS_COMPLETED,
                )
            )
            .annotate(
                _verified_rank=Case(
                    When(organizer_identity_verified=True, then=0),
                    default=1,
                    output_field=IntegerField(),
                )
            )
            .order_by("_verified_rank", "-created_at")
        )
        return qs

    def get_serializer_class(self):
        if self.action == "create":
            return EventCreateSerializer
        return EventListSerializer

    def perform_create(self, serializer):
        if not services.organizer_identity_allowed_for_events(self.request.user):
            raise PermissionDenied(
                "Verified identity (blue/green trust tier or government ID verified) "
                "is required to create events."
            )
        serializer.save()

    def perform_destroy(self, instance):
        if instance.organizer_id != self.request.user.id and not self.request.user.is_staff:
            raise PermissionDenied()
        if instance.status != Event.STATUS_ACTIVE:
            raise ValidationError({"detail": "Only active events can be deleted."})
        instance.delete()

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def enroll(self, request, pk=None):
        event = self.get_object()
        if event.organizer_id == request.user.id:
            raise ValidationError({"detail": "Organizer cannot enroll in own event."})
        ser = EnrollSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = enroll_user_in_event(
            event=event, user=request.user, quantity=ser.validated_data["quantity"]
        )
        return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def scan(self, request, pk=None):
        event = self.get_object()
        ser = ScanQrSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        vd = ser.validated_data
        qp = (vd.get("qr_payload") or "").strip()
        if qp:
            en = services.enrollment_check_in(
                event=event, organizer=request.user, qr_payload=qp
            )
        else:
            en = services.enrollment_check_in(
                event=event, organizer=request.user, public_id=vd["public_id"]
            )
        return Response(EventEnrollmentSerializer(en).data)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def report(self, request, pk=None):
        event = self.get_object()
        ser = FraudReportSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        report, created = EventFraudReport.objects.get_or_create(
            user=request.user,
            event=event,
            defaults={"reason": ser.validated_data["reason"]},
        )
        if not created:
            raise ValidationError({"detail": "You already reported this event."})
        event.refresh_from_db()
        services.evaluate_fraud_and_maybe_flag(event)
        return Response(FraudReportSerializer(report).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def complete(self, request, pk=None):
        event = self.get_object()
        if event.organizer_id != request.user.id:
            raise PermissionDenied()
        if event.status != Event.STATUS_ACTIVE:
            raise ValidationError({"detail": "Event is not active."})
        services.complete_event_and_settle(event)
        event.refresh_from_db()
        return Response(EventListSerializer(event).data)

    @action(
        detail=True,
        methods=["post"],
        permission_classes=[IsAdminUser],
        url_path="release-escrow",
    )
    def release_escrow(self, request, pk=None):
        event = self.get_object()
        n = services.release_escrow_to_organizer(event)
        return Response({"released": n})

    @action(
        detail=True,
        methods=["post"],
        permission_classes=[IsAdminUser],
        url_path="refund-escrow",
    )
    def refund_escrow(self, request, pk=None):
        event = self.get_object()
        n = services.refund_escrow_payments(event)
        return Response({"refunded": n})

    @action(detail=False, methods=["get"], permission_classes=[AllowAny])
    def home_feed(self, request):
        qs = self.filter_queryset(self.get_queryset())[:50]
        ser = EventListSerializer(qs, many=True, context={"request": request})
        return Response(ser.data)


class EventEnrollmentViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = EventEnrollment.objects.select_related("event", "user").all()
    serializer_class = EventEnrollmentSerializer
    lookup_field = "public_id"
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.user.is_staff:
            return qs
        return qs.filter(user=self.request.user)


class PlatformWalletViewSet(viewsets.ViewSet):
    """Balance, Razorpay top-up (demo/test), payout request (wallet → off-ramp)."""

    permission_classes = [IsAuthenticated]

    def list(self, request):
        w = wallet_services.get_or_create_user_wallet(request.user)
        return Response(
            {
                "balance": str(w.balance),
                "currency": w.currency,
                "razorpay_configured": razorpay_service.razorpay_configured(),
            }
        )

    @action(detail=False, methods=["post"], url_path="top-up-order")
    def top_up_order(self, request):
        ser = RazorpayTopUpOrderSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        amount = ser.validated_data["amount"]
        receipt = f"wt_{request.user.id}_{uuid.uuid4().hex[:10]}"
        order = razorpay_service.create_order(
            amount_inr=amount,
            receipt=receipt,
            notes={"user_id": str(request.user.id)},
        )
        WalletTopUp.objects.create(
            user=request.user,
            amount=amount,
            razorpay_order_id=order["id"],
            status=WalletTopUp.STATUS_PENDING,
        )
        return Response(
            {
                "order_id": order["id"],
                "amount": order["amount"],
                "currency": order["currency"],
                "key_id": razorpay_service.get_publishable_key_id(),
            }
        )

    @action(detail=False, methods=["post"], url_path="top-up-verify")
    def top_up_verify(self, request):
        ser = RazorpayTopUpVerifySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        oid = ser.validated_data["razorpay_order_id"]
        pid = ser.validated_data["razorpay_payment_id"]
        sig = ser.validated_data["razorpay_signature"]
        if not razorpay_service.verify_payment_signature(
            order_id=oid, payment_id=pid, signature=sig
        ):
            raise ValidationError({"detail": "Invalid Razorpay signature."})
        tu = WalletTopUp.objects.filter(user=request.user, razorpay_order_id=oid).first()
        if not tu:
            raise ValidationError({"detail": "Unknown order for this user."})
        pay = razorpay_service.fetch_payment(pid)
        if pay.get("order_id") != oid:
            raise ValidationError({"detail": "Payment does not match order."})
        if pay.get("status") not in ("authorized", "captured"):
            raise ValidationError({"detail": "Payment not captured."})
        amt_paise = int(pay.get("amount") or 0)
        if amt_paise != int(tu.amount * 100):
            raise ValidationError({"detail": "Amount does not match order."})
        with transaction.atomic():
            tu_locked = WalletTopUp.objects.select_for_update().get(pk=tu.pk)
            if tu_locked.status == WalletTopUp.STATUS_COMPLETED:
                w = wallet_services.get_or_create_user_wallet(request.user)
                return Response(
                    {"status": "already_completed", "balance": str(w.balance)}
                )
            wallet_services.credit_wallet_topup(
                user=request.user,
                amount=tu_locked.amount,
                razorpay_order_id=oid,
                razorpay_payment_id=pid,
            )
            tu_locked.razorpay_payment_id = pid
            tu_locked.status = WalletTopUp.STATUS_COMPLETED
            tu_locked.save(update_fields=["razorpay_payment_id", "status"])
        w = wallet_services.get_or_create_user_wallet(request.user)
        return Response({"status": "ok", "balance": str(w.balance)})

    @action(detail=False, methods=["post"], url_path="payout-request")
    def payout_request(self, request):
        ser = WalletPayoutBodySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        pr = wallet_services.request_payout(
            user=request.user,
            amount=ser.validated_data["amount"],
            note=ser.validated_data.get("note") or "",
        )
        return Response(
            {
                "id": str(pr.pk),
                "status": pr.status,
                "amount": str(pr.amount),
            },
            status=status.HTTP_201_CREATED,
        )


class EventGrievanceViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = EventGrievanceSerializer
    permission_classes = [IsAuthenticated]
    queryset = EventGrievance.objects.select_related("event", "user").all()

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.user.is_staff:
            return qs
        return qs.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(
        detail=True,
        methods=["post"],
        permission_classes=[IsAdminUser],
        url_path="resolve-refund",
    )
    def resolve_refund(self, request, pk=None):
        g = self.get_object()
        wallet_services.grievance_refund_to_user(g)
        g.refresh_from_db()
        return Response(EventGrievanceSerializer(g).data)

    @action(
        detail=True,
        methods=["post"],
        permission_classes=[IsAdminUser],
        url_path="resolve-reject",
    )
    def resolve_reject(self, request, pk=None):
        g = self.get_object()
        wallet_services.reject_grievance(g)
        g.refresh_from_db()
        return Response(EventGrievanceSerializer(g).data)


class AdminWalletPayoutViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAdminUser]
    serializer_class = WalletPayoutRequestSerializer
    queryset = WalletPayoutRequest.objects.select_related("user", "reviewed_by").order_by(
        "-created_at"
    )

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        payout = self.get_object()
        wallet_services.approve_payout(payout=payout, admin_user=request.user)
        payout.refresh_from_db()
        return Response(WalletPayoutRequestSerializer(payout).data)

    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        payout = self.get_object()
        wallet_services.reject_payout(payout=payout, admin_user=request.user)
        payout.refresh_from_db()
        return Response(WalletPayoutRequestSerializer(payout).data)

    @action(detail=True, methods=["post"], url_path="mark-processed")
    def mark_processed(self, request, pk=None):
        payout = self.get_object()
        if payout.status != WalletPayoutRequest.STATUS_APPROVED:
            raise ValidationError({"detail": "Approve the payout first."})
        wallet_services.mark_payout_processed_demo(payout=payout)
        payout.refresh_from_db()
        return Response(WalletPayoutRequestSerializer(payout).data)
