import json
import os
from pathlib import Path
import subprocess
import sys

from django.conf import settings
from django.db import connection
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.views.defaults import page_not_found, server_error


BASE_DIR = Path(__file__).resolve().parent.parent


class ProductionSettingsTests(SimpleTestCase):
    production_environment = {
        "ENVIRONMENT": "production",
        "RENDER": "true",
        "DEBUG": "false",
        "SECRET_KEY": "audit-only-abcdefghijklmnopqrstuvwxyz-0123456789-unique-key",
        "DATABASE_URL": "postgresql://audit:audit@localhost:5432/audit",
        "DATABASE_SSLMODE": "require",
        "ALLOWED_HOSTS": "example.test",
        "RENDER_EXTERNAL_HOSTNAME": "service.onrender.com",
        "CSRF_TRUSTED_ORIGINS": "https://example.test",
        "SITE_BASE_URL": "https://example.test",
        "CLOUDINARY_CLOUD_NAME": "audit",
        "CLOUDINARY_API_KEY": "audit",
        "CLOUDINARY_API_SECRET": "audit",
        "STRIPE_ENABLED": "false",
        "CINETPAY_ENABLED": "false",
        "DONATIONS_ENABLED": "false",
        "SUBSCRIPTIONS_ENABLED": "false",
    }

    def run_settings(self, **overrides):
        environment = os.environ.copy()
        environment.update(self.production_environment)
        environment.update(overrides)
        return subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import json; import blog.settings as s; "
                    "print(json.dumps({"
                    "'production': s.IS_PRODUCTION, "
                    "'debug': s.DEBUG, "
                    "'hosts': s.ALLOWED_HOSTS, "
                    "'csrf_origins': s.CSRF_TRUSTED_ORIGINS, "
                    "'db_engine': s.DATABASES['default']['ENGINE'], "
                    "'db_health_checks': "
                    "s.DATABASES['default'].get('CONN_HEALTH_CHECKS'), "
                    "'db_sslmode': "
                    "s.DATABASES['default'].get('OPTIONS', {}).get('sslmode'), "
                    "'ssl_redirect': getattr(s, 'SECURE_SSL_REDIRECT', False), "
                    "'hsts_subdomains': "
                    "getattr(s, 'SECURE_HSTS_INCLUDE_SUBDOMAINS', False), "
                    "'session_httponly': "
                    "getattr(s, 'SESSION_COOKIE_HTTPONLY', True), "
                    "'session_samesite': "
                    "getattr(s, 'SESSION_COOKIE_SAMESITE', 'Lax')"
                    "}))"
                ),
            ],
            cwd=BASE_DIR,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_false_render_string_does_not_enable_production(self):
        result = self.run_settings(
            ENVIRONMENT="development",
            RENDER="false",
            SECRET_KEY="",
            DATABASE_URL="",
            ALLOWED_HOSTS="",
            RENDER_EXTERNAL_HOSTNAME="",
            CSRF_TRUSTED_ORIGINS="",
            SITE_BASE_URL="",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)["production"])

    def test_production_settings_are_strict_and_proxy_compatible(self):
        result = self.run_settings()

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["production"])
        self.assertFalse(payload["debug"])
        self.assertEqual(
            payload["hosts"],
            ["example.test", "service.onrender.com"],
        )
        self.assertEqual(payload["csrf_origins"], ["https://example.test"])
        self.assertEqual(payload["db_engine"], "django.db.backends.postgresql")
        self.assertTrue(payload["db_health_checks"])
        self.assertEqual(payload["db_sslmode"], "require")
        self.assertTrue(payload["ssl_redirect"])
        self.assertFalse(payload["hsts_subdomains"])
        self.assertTrue(payload["session_httponly"])
        self.assertEqual(payload["session_samesite"], "Lax")

    def test_production_rejects_unsafe_or_missing_core_settings(self):
        cases = (
            ({"SECRET_KEY": ""}, "SECRET_KEY"),
            ({"DATABASE_URL": ""}, "DATABASE_URL"),
            (
                {"ALLOWED_HOSTS": "", "RENDER_EXTERNAL_HOSTNAME": ""},
                "ALLOWED_HOSTS",
            ),
            ({"ALLOWED_HOSTS": "*"}, "ALLOWED_HOSTS"),
            ({"CSRF_TRUSTED_ORIGINS": "http://example.test"}, "HTTPS"),
            ({"SITE_BASE_URL": "", "RENDER_EXTERNAL_URL": ""}, "SITE_BASE_URL"),
            ({"SITE_BASE_URL": "http://example.test"}, "SITE_BASE_URL"),
            ({"SITE_BASE_URL": "https://example.test/path"}, "SITE_BASE_URL"),
            ({"DEBUG": "true"}, "DEBUG"),
            ({"SECURE_HSTS_SECONDS": "-1"}, "SECURE_HSTS_SECONDS"),
            ({"DATABASE_SSLMODE": "disable"}, "DATABASE_SSLMODE"),
        )
        for overrides, expected_message in cases:
            with self.subTest(overrides=tuple(overrides)):
                result = self.run_settings(**overrides)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_message, result.stderr)


class HealthCheckTests(TestCase):
    def test_liveness_is_public_short_uncached_and_database_free(self):
        url = reverse("health")
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")
        self.assertEqual(len(captured), 0)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(self.client.head(url).status_code, 200)
        self.assertEqual(self.client.post(url).status_code, 405)
        self.assertEqual(self.client.get("/de/health/").status_code, 404)


class SecurityResponseTests(TestCase):
    @override_settings(
        SECURE_HSTS_SECONDS=3600,
        SECURE_HSTS_INCLUDE_SUBDOMAINS=False,
        SECURE_HSTS_PRELOAD=False,
        SECURE_CONTENT_TYPE_NOSNIFF=True,
        SECURE_REFERRER_POLICY="same-origin",
        SECURE_CROSS_ORIGIN_OPENER_POLICY="same-origin",
        X_FRAME_OPTIONS="DENY",
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        CSRF_COOKIE_SECURE=True,
        CSRF_COOKIE_SAMESITE="Lax",
    )
    def test_security_headers_and_cookie_policy(self):
        response = self.client.get(reverse("health"), secure=True)

        self.assertEqual(response["Strict-Transport-Security"], "max-age=3600")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["Referrer-Policy"], "same-origin")
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(response["Cross-Origin-Opener-Policy"], "same-origin")
        self.assertEqual(
            response["Permissions-Policy"],
            "camera=(), microphone=(), geolocation=()",
        )
        self.assertTrue(settings.SESSION_COOKIE_SECURE)
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, "Lax")
        self.assertTrue(settings.CSRF_COOKIE_SECURE)
        self.assertEqual(settings.CSRF_COOKIE_SAMESITE, "Lax")

    @override_settings(DEBUG=False)
    def test_default_error_pages_do_not_expose_tracebacks_or_secrets(self):
        request = RequestFactory().get("/missing/")
        responses = (
            page_not_found(request, Exception("private-marker")),
            server_error(request),
        )

        for response in responses:
            with self.subTest(status=response.status_code):
                markup = response.content.decode()
                self.assertNotIn("private-marker", markup)
                self.assertNotIn("Traceback", markup)
                self.assertNotIn(settings.SECRET_KEY, markup)


class DeploymentConfigurationTests(SimpleTestCase):
    def test_free_render_build_runs_migrations_before_collectstatic(self):
        build_script = (BASE_DIR / "build.sh").read_text(encoding="utf-8")

        install = build_script.index("python -m pip install -r requirements.txt")
        migrate = build_script.index("python manage.py migrate --noinput")
        collectstatic = build_script.index("python manage.py collectstatic --noinput")

        self.assertIn("set -o errexit", build_script)
        self.assertIn("Plan Render gratuit", build_script)
        self.assertLess(install, migrate)
        self.assertLess(migrate, collectstatic)

    def test_gunicorn_uses_render_port_without_reload(self):
        procfile = (BASE_DIR / "Procfile").read_text(encoding="utf-8")
        dockerfile = (BASE_DIR / "Dockerfile").read_text(encoding="utf-8")

        for content in (procfile, dockerfile):
            self.assertIn("gunicorn", content)
            self.assertIn("0.0.0.0", content)
            self.assertIn("PORT", content)
            self.assertNotIn("--reload", content)
            self.assertNotIn("runserver", content)
        self.assertIn("exec gunicorn", dockerfile)
        self.assertIn("USER appuser", dockerfile)

    def test_docker_context_excludes_local_and_sensitive_artifacts(self):
        dockerignore = (BASE_DIR / ".dockerignore").read_text(encoding="utf-8")

        for entry in (
            ".git",
            ".env",
            "media/",
            "media_backup.zip",
            "staticfiles/",
        ):
            with self.subTest(entry=entry):
                self.assertIn(entry, dockerignore)
