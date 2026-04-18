import json
from unittest.mock import patch

from django.test import Client, TestCase
from accounts.models import User


class VerificationApiTests(TestCase):
    def setUp(self):
        from django.core.management import call_command

        call_command("seed_verification_data", "--purge")
        self.client = Client()
        self.user = User.objects.create_user(
            username="boss1",
            password="pass1234",
            role="company",
        )
        profile = self.user.profile
        profile.is_boss = True
        profile.save()
        self.client.login(username="boss1", password="pass1234")
        for p in (
            patch(
                "verification.views.maybe_upstream_failure", return_value=None
            ),
            patch("verification.views.simulated_delay_ms"),
            patch(
                "verification.ownership_engine.maybe_random_not_found",
                return_value=False,
            ),
        ):
            self.addCleanup(p.stop)
            p.start()

    def test_verify_tax_happy_path(self):
        res = self.client.post(
            "/api/v1/verify/tax/",
            data='{"gstin": "07AABCU9601R1ZV"}',
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["data"]["legal_name"], "ACME INNOVATIONS PVT LTD")

    def test_verify_company_not_found(self):
        res = self.client.post(
            "/api/v1/verify/company/",
            data='{"cin": "U99999DL2099PTC999999"}',
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 404)
        self.assertFalse(res.json()["success"])

    def test_ownership_acme_director(self):
        payload = {
            "cin": "U74999DL2019PTC346789",
            "gstin": "07AABCU9601R1ZV",
            "company_name": "Acme Innovations Private Limited",
            "claimant_name": "Rajesh Kumar Sharma",
            "claimant_id": "user-1",
        }
        res = self.client.post(
            "/api/v1/verify/ownership/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["success"])
        self.assertIn(body["decision"], ("Verified", "Partially Verified", "Rejected"))
