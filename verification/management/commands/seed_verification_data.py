"""
Load simulated MCA + GST registers from JSON into the database.
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from verification import models


class Command(BaseCommand):
    help = "Seed Company, Director, and TaxRecord rows from verification/data/*.json"

    def add_arguments(self, parser):
        parser.add_argument(
            "--purge",
            action="store_true",
            help="Delete existing verification rows before import.",
        )

    def handle(self, *args, **options):
        base = Path(__file__).resolve().parent.parent.parent / "data"
        companies_path = base / "companies_seed.json"
        taxes_path = base / "taxes_seed.json"

        if options["purge"]:
            models.FraudSignal.objects.all().delete()
            models.OwnershipClaim.objects.all().delete()
            models.TaxRecord.objects.all().delete()
            models.Director.objects.all().delete()
            models.Company.objects.all().delete()
            self.stdout.write(self.style.WARNING("Purged existing verification data."))

        companies_raw = json.loads(companies_path.read_text(encoding="utf-8"))
        cin_map: dict[str, models.Company] = {}
        for row in companies_raw:
            c = models.Company.objects.create(
                cin=row["cin"],
                legal_name=row["legal_name"],
                status=row["status"],
            )
            cin_map[c.cin] = c
            for d in row.get("directors", []):
                models.Director.objects.create(company=c, full_name=d)

        taxes_raw = json.loads(taxes_path.read_text(encoding="utf-8"))
        for row in taxes_raw:
            linked = None
            lc = row.get("linked_cin")
            if lc:
                linked = cin_map.get(lc)
            models.TaxRecord.objects.create(
                gstin=row["gstin"],
                legal_name=row["legal_name"],
                status=row["status"],
                company=linked,
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(cin_map)} companies and {len(taxes_raw)} tax rows."
            )
        )
