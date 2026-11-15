from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.test import Client
from rest_framework.test import APIClient
# Create your tests here.

class ModelTests(TestCase):
    def test_create_user_with_email_sucess(self):
        email = 'test@example.com'
        password = 'password'
        user = get_user_model().objects.create_user(
            email=email,
            password=password
        )

        self.assertEqual(user.email, email)
        self.assertTrue(user.check_password(password))

    def test_new_user_email_normalized(self):
        sample_emails = [
            ['test1@EXAMPLE.com', 'test1@example.com'],
            ['Test2@Example.com', 'Test2@example.com'], 
            ['TEST3@Example.COM', 'TEST3@example.com'], 
            ['test4@example.COM', 'test4@example.com'], 
        ]
        
        for email, expected_email in sample_emails:
            user = get_user_model().objects.create_user(email, 'sample123')
            self.assertEqual(user.email, expected_email)
    
    def test_new_user_without_email_raises_error(self):
        with self.assertRaises(ValueError):
            get_user_model().objects.create_user('','sample123')

    def test_create_superuser(self):
        user = get_user_model().objects.create_superuser(
            email='test@example.com',
            password='test123'
        )

        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_staff)

class AdminSiteTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin_user = get_user_model().objects.create_superuser(
            email="admin@example.com",
            password="TestPassword123"
        )
        self.client.force_login(self.admin_user)
        self.user = get_user_model().objects.create_user(
            email="user@example.com",
            password="TestPassword123",
            name="Test User"
        )

    def test_users_list(self):
        # {{ app_label }}_{{ model_name }}_changelist	 
        url = reverse('admin:profile_userprofile_changelist')
        res = self.client.get(url)

        self.assertContains(res, self.user.name)
        self.assertContains(res, self.user.email)

    def test_edit_user_page(self):
        url = reverse('admin:profile_userprofile_change', args=[self.user.id])
        res = self.client.get(url)

        self.assertEqual(res.status_code, 200)

    def test_create_user_page(self):
        url = reverse('admin:profile_userprofile_add')
        res = self.client.get(url)

        self.assertEqual(res.status_code, 200)


class ProfileApiPermissionTests(TestCase):
    """Anonymous profile API access is denied and creation is staff-only."""

    def setUp(self):
        self.client = APIClient()
        self.user_model = get_user_model()
        self.owner = self.user_model.objects.create_user(
            email="owner@example.com",
            password="TestPassword123",
            name="Owner",
        )
        self.other = self.user_model.objects.create_user(
            email="other@example.com",
            password="TestPassword123",
            name="Other",
        )
        self.staff = self.user_model.objects.create_user(
            email="staff@example.com",
            password="TestPassword123",
            name="Staff",
            is_staff=True,
        )
        self.superuser = self.user_model.objects.create_user(
            email="super@example.com",
            password="TestPassword123",
            name="Super",
        )
        self.superuser.is_superuser = True
        self.superuser.is_staff = False
        self.superuser.save(update_fields=["is_superuser", "is_staff"])
        self.list_url = "/api/profiles/"
        self.owner_url = f"/api/profiles/{self.owner.pk}/"
        self.other_url = f"/api/profiles/{self.other.pk}/"

    def _assert_denied(self, response):
        self.assertIn(response.status_code, (401, 403))
        self.assertNotIn(b"owner@example.com", response.content)
        self.assertNotIn(b"other@example.com", response.content)

    def test_anonymous_reads_and_writes_are_denied_and_create_no_user(self):
        starting = self.user_model.objects.count()
        anonymous_calls = (
            self.client.get(self.list_url),
            self.client.head(self.list_url),
            self.client.get(self.owner_url),
            self.client.put(
                self.owner_url,
                {"email": "owner@example.com", "name": "Taken", "password": "TestPassword123"},
                format="json",
            ),
            self.client.patch(self.owner_url, {"name": "Taken"}, format="json"),
            self.client.delete(self.owner_url),
            self.client.post(
                self.list_url,
                {
                    "email": "created-anon@example.com",
                    "name": "Anon",
                    "password": "TestPassword123",
                },
                format="json",
            ),
        )
        for response in anonymous_calls:
            self._assert_denied(response)
        self.assertEqual(self.user_model.objects.count(), starting)
        self.assertFalse(
            self.user_model.objects.filter(email="created-anon@example.com").exists()
        )
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.name, "Owner")

    def test_non_staff_cannot_create_and_can_edit_only_own_profile(self):
        self.client.force_authenticate(self.owner)
        starting = self.user_model.objects.count()
        created = self.client.post(
            self.list_url,
            {
                "email": "created-user@example.com",
                "name": "Created",
                "password": "TestPassword123",
            },
            format="json",
        )
        self.assertIn(created.status_code, (401, 403))
        self.assertEqual(self.user_model.objects.count(), starting)

        own = self.client.patch(self.owner_url, {"name": "Owner Renamed"}, format="json")
        self.assertEqual(own.status_code, 200)
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.name, "Owner Renamed")

        other = self.client.patch(self.other_url, {"name": "Hijacked"}, format="json")
        self.assertIn(other.status_code, (401, 403))
        deleted = self.client.delete(self.other_url)
        self.assertIn(deleted.status_code, (401, 403))
        self.other.refresh_from_db()
        self.assertEqual(self.other.name, "Other")
        self.assertTrue(self.user_model.objects.filter(pk=self.other.pk).exists())

    def test_staff_and_superuser_create_run_password_validators(self):
        for actor in (self.staff, self.superuser):
            self.client.force_authenticate(actor)
            weak = self.client.post(
                self.list_url,
                {
                    "email": f"weak-{actor.pk}@example.com",
                    "name": "Weak",
                    "password": "password",
                },
                format="json",
            )
            self.assertEqual(weak.status_code, 400)
            self.assertIn("password", weak.json())
            self.assertFalse(
                self.user_model.objects.filter(email=f"weak-{actor.pk}@example.com").exists()
            )

            numeric = self.client.post(
                self.list_url,
                {
                    "email": f"numeric-{actor.pk}@example.com",
                    "name": "Numeric",
                    "password": "12345678",
                },
                format="json",
            )
            self.assertEqual(numeric.status_code, 400)
            self.assertFalse(
                self.user_model.objects.filter(email=f"numeric-{actor.pk}@example.com").exists()
            )

            created = self.client.post(
                self.list_url,
                {
                    "email": f"created-{actor.pk}@example.com",
                    "name": "Created",
                    "password": "TestPassword123",
                },
                format="json",
            )
            self.assertEqual(created.status_code, 201)
            user = self.user_model.objects.get(email=f"created-{actor.pk}@example.com")
            self.assertTrue(user.check_password("TestPassword123"))
            self.assertNotIn("password", created.json())

            stolen = self.client.patch(self.owner_url, {"name": "Not Allowed"}, format="json")
            self.assertIn(stolen.status_code, (401, 403))
            self.owner.refresh_from_db()
            self.assertEqual(self.owner.name, "Owner")

    def test_create_rejects_a_password_similar_to_the_submitted_email(self):
        self.client.force_authenticate(self.staff)
        response = self.client.post(
            self.list_url,
            {
                "email": "distinctiveoperator@example.com",
                "name": "Clinic",
                "password": "distinctiveoperator",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("password", response.json())
        self.assertFalse(
            self.user_model.objects.filter(
                email="distinctiveoperator@example.com"
            ).exists()
        )