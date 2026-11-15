from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from core.models import BotControl, DustSignalReview, ManualCorrection

BROWSER_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
DUST_POST = {
    "symbol": "BTCUSDT",
    "asset": "BTC",
    "reason": "below_min_notional",
    "event_type": "dust_candidate_detected",
    "severity": "info",
    "status": DustSignalReview.STATUS_IGNORED,
    "note": "should-not-write",
}


def _user(email, *, staff=False, superuser=False):
    user = get_user_model().objects.create_user(
        email=email,
        password="TestPassword123",
        name=email.split("@", 1)[0],
        is_staff=staff and not superuser,
    )
    if superuser:
        user.is_staff = False
        user.is_superuser = True
        user.save(update_fields=["is_staff", "is_superuser"])
    return user


class BotControlStaffAccessTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.pause_url = reverse("bot_stop")
        self.resume_url = reverse("bot_resume")
        self.status_url = reverse("bot_status")
        self.non_staff = _user("operator@example.com")
        self.staff = _user("operator-staff@example.com", staff=True)
        self.superuser = _user("operator-super@example.com", superuser=True)

    def _snapshot(self):
        return list(
            BotControl.objects.values_list(
                "id", "is_paused", "reason", "updated_by_id"
            )
        )

    def test_anonymous_control_endpoints_do_not_write(self):
        before = self._snapshot()
        pause = self.client.post(
            self.pause_url,
            {"confirm": "yes", "reason": "anon"},
            HTTP_ACCEPT=BROWSER_ACCEPT,
        )
        resume = self.client.post(
            self.resume_url,
            {"reason": "anon"},
            HTTP_ACCEPT="application/json",
        )
        status = self.client.get(self.status_url)
        for response in (pause, resume, status):
            self.assertEqual(response.status_code, 302)
            self.assertIn(reverse("login"), response["Location"])
        self.assertEqual(self._snapshot(), before)
        self.assertFalse(BotControl.objects.filter(is_paused=True).exists())

    def test_non_staff_control_endpoints_are_forbidden_without_side_effects(self):
        self.client.force_login(self.non_staff)
        before = self._snapshot()
        pause = self.client.post(
            self.pause_url,
            {"confirm": "yes", "reason": "nope"},
            HTTP_ACCEPT="application/json",
        )
        resume = self.client.post(
            self.resume_url,
            {"reason": "nope"},
            HTTP_ACCEPT=BROWSER_ACCEPT,
        )
        status = self.client.get(self.status_url)
        denied_get = self.client.get(self.pause_url)
        for response in (pause, resume, status, denied_get):
            self.assertEqual(response.status_code, 403)
        self.assertEqual(self._snapshot(), before)

    def test_staff_keeps_confirmation_csrf_and_pause_behavior(self):
        self.client.force_login(self.staff)
        unconfirmed = self.client.post(
            self.pause_url,
            {"reason": "sin-confirmacion"},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(unconfirmed.status_code, 400)
        self.assertEqual(unconfirmed.json()["error"], "confirmation_required")
        self.assertFalse(BotControl.objects.filter(is_paused=True).exists())

        paused = self.client.post(
            self.pause_url,
            {"confirm": "yes", "reason": "mantenimiento"},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(paused.status_code, 200)
        self.assertEqual(paused.json()["status"], "paused")
        self.assertEqual(paused.json()["reason"], "mantenimiento")
        self.assertTrue(BotControl.objects.get().is_paused)

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.staff)
        blocked = csrf_client.post(
            self.resume_url,
            {"reason": "csrf"},
            HTTP_ACCEPT=BROWSER_ACCEPT,
        )
        self.assertEqual(blocked.status_code, 403)
        self.assertTrue(BotControl.objects.get().is_paused)
        self.assertEqual(BotControl.objects.get().reason, "mantenimiento")

        status = self.client.get(self.status_url)
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["status"], "paused")

    def test_superuser_without_staff_flag_can_resume(self):
        BotControl.objects.create(is_paused=True, reason="antes", updated_by=self.staff)
        self.client.force_login(self.superuser)
        response = self.client.post(
            self.resume_url,
            {"reason": "continuar"},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "running")
        self.assertFalse(BotControl.objects.get().is_paused)
        self.assertEqual(BotControl.objects.get().updated_by, self.superuser)


class DustReviewStaffAccessTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse("dust_detail")
        self.non_staff = _user("dust-user@example.com")
        self.staff = _user("dust-staff@example.com", staff=True)
        self.superuser = _user("dust-super@example.com", superuser=True)

    def test_non_staff_post_is_forbidden_and_reviews_stay_unchanged(self):
        self.client.force_login(self.non_staff)
        before = DustSignalReview.objects.count()
        response = self.client.post(self.url, DUST_POST)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(DustSignalReview.objects.count(), before)

        page = self.client.get(self.url)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(DustSignalReview.objects.count(), before)

    def test_anonymous_post_does_not_write(self):
        before = DustSignalReview.objects.count()
        response = self.client.post(self.url, DUST_POST)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(DustSignalReview.objects.count(), before)

    def test_staff_and_superuser_can_record_a_review(self):
        for actor, status in (
            (self.staff, DustSignalReview.STATUS_IGNORED),
            (self.superuser, DustSignalReview.STATUS_REVIEWED),
        ):
            self.client.force_login(actor)
            payload = dict(DUST_POST)
            payload["symbol"] = "ETHUSDT" if actor.is_superuser else "BTCUSDT"
            payload["asset"] = "ETH" if actor.is_superuser else "BTC"
            payload["status"] = status
            response = self.client.post(self.url, payload)
            self.assertEqual(response.status_code, 302)
            review = DustSignalReview.objects.get(symbol=payload["symbol"])
            self.assertEqual(review.status, status)
            self.assertEqual(review.reviewed_by, actor)


class ManualCorrectionReadAccessTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._created_table = False
        existing = connection.introspection.table_names()
        if ManualCorrection._meta.db_table not in existing:
            with connection.schema_editor() as schema_editor:
                schema_editor.create_model(ManualCorrection)
            cls._created_table = True

    @classmethod
    def tearDownClass(cls):
        if cls._created_table:
            with connection.schema_editor() as schema_editor:
                schema_editor.delete_model(ManualCorrection)
        super().tearDownClass()

    def setUp(self):
        ManualCorrection.objects.all().delete()
        self.client = Client()
        self.non_staff = _user("correction-user@example.com")
        self.staff = _user("correction-staff@example.com", staff=True)
        self.superuser = _user("correction-super@example.com", superuser=True)
        self.correction = ManualCorrection.objects.create(
            correction_type=ManualCorrection.TYPE_CLOSE_LOTS_EXTERNAL_SELL,
            symbol="BTCUSDT",
            asset="BTC",
            quantity=Decimal("0.100000000000000000"),
            price_usdt=Decimal("1.000000000000000000"),
            estimated_value_usdt=Decimal("0.100000000000000000"),
            reason="unchanged",
            status=ManualCorrection.STATUS_PENDING,
        )
        self.list_url = reverse("manual_corrections", args=["pending"])
        self.detail_url = reverse(
            "manual_correction_detail", args=[self.correction.pk]
        )

    def test_anonymous_and_non_staff_cannot_read_corrections(self):
        anonymous_list = self.client.get(self.list_url)
        anonymous_detail = self.client.get(self.detail_url)
        for response in (anonymous_list, anonymous_detail):
            self.assertEqual(response.status_code, 302)
            self.assertIn(reverse("login"), response["Location"])

        self.client.force_login(self.non_staff)
        denied_list = self.client.get(self.list_url)
        denied_detail = self.client.get(self.detail_url)
        denied_post = self.client.post(self.detail_url, {"reason": "changed"})
        for response in (denied_list, denied_detail, denied_post):
            self.assertEqual(response.status_code, 403)
        self.correction.refresh_from_db()
        self.assertEqual(self.correction.reason, "unchanged")
        self.assertEqual(self.correction.status, ManualCorrection.STATUS_PENDING)

    def test_staff_and_superuser_can_read_corrections(self):
        for actor in (self.staff, self.superuser):
            self.client.force_login(actor)
            listing = self.client.get(self.list_url)
            detail = self.client.get(self.detail_url)
            self.assertEqual(listing.status_code, 200)
            self.assertEqual(detail.status_code, 200)
            self.assertContains(detail, "unchanged")
        self.correction.refresh_from_db()
        self.assertEqual(self.correction.reason, "unchanged")
