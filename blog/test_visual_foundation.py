import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class VisualFoundationStaticTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.base_dir = Path(settings.BASE_DIR)
        cls.styles_path = cls.base_dir / "static" / "css" / "styles.css"
        cls.styles = cls.styles_path.read_text(encoding="utf-8")
        cls.base_template = (
            cls.base_dir / "templates" / "template_base.html"
        ).read_text(encoding="utf-8")

    @staticmethod
    def _custom_properties(css):
        return dict(
            re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;{}]+);", css, re.IGNORECASE)
        )

    def test_critical_and_canonical_tokens_are_defined(self):
        properties = self._custom_properties(self.styles)
        expected = {
            "--brand-500",
            "--brand-200",
            "--gold-700",
            "--gold-500",
            "--ink-900",
            "--ink-600",
            "--ink-400",
            "--muted",
            "--surface-0",
            "--surface-1",
            "--surface-2",
            "--border-subtle",
            "--border-strong",
            "--font-sans",
            "--focus-outline",
            "--focus-ring",
        }

        self.assertFalse(expected - properties.keys())

    def test_legacy_tokens_alias_the_canonical_vocabulary(self):
        properties = self._custom_properties(self.styles)
        expected_aliases = {
            "--accent-600": "var(--gold-700)",
            "--accent-500": "var(--gold-500)",
            "--accent-100": "var(--gold-100)",
            "--line": "var(--border-subtle)",
            "--line-strong": "var(--border-strong)",
            "--surface": "var(--surface-0)",
            "--surface-soft": "var(--surface-2)",
            "--page-bg": "var(--surface-1)",
            "--muted": "var(--ink-500)",
            "--color-primary": "var(--brand-900)",
            "--color-accent": "var(--gold-700)",
            "--color-text-muted": "var(--ink-500)",
        }

        for token, value in expected_aliases.items():
            with self.subTest(token=token):
                self.assertEqual(properties.get(token), value)

    def test_bootstrap_bridge_exposes_colors_and_rgb_variants(self):
        properties = self._custom_properties(self.styles)
        expected = {
            "--bs-primary",
            "--bs-primary-rgb",
            "--bs-success",
            "--bs-success-rgb",
            "--bs-danger",
            "--bs-danger-rgb",
            "--bs-warning",
            "--bs-warning-rgb",
            "--bs-info",
            "--bs-info-rgb",
            "--bs-body-color",
            "--bs-body-color-rgb",
            "--bs-body-bg",
            "--bs-body-bg-rgb",
            "--bs-border-color",
            "--bs-link-color",
            "--bs-link-color-rgb",
            "--bs-link-hover-color",
            "--bs-link-hover-color-rgb",
            "--bs-focus-ring-color",
        }

        self.assertFalse(expected - properties.keys())

    def test_application_styles_do_not_use_undefined_custom_properties(self):
        application_styles = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((self.base_dir / "static" / "css").glob("*.css"))
            if not path.name.endswith(".min.css")
        )
        used = set(re.findall(r"var\(\s*(--[a-z0-9-]+)", application_styles))
        defined = set(self._custom_properties(application_styles))

        self.assertEqual(used - defined, set())

    def test_stylesheets_keep_the_required_loading_order(self):
        markers = (
            "bootstrap@5.3.2/dist/css/bootstrap.min.css",
            "font-awesome/6.5.0/css/all.min.css",
            "{% static 'css/styles.css' %}",
            "{% block styles %}",
        )
        positions = [self.base_template.index(marker) for marker in markers]

        self.assertEqual(positions, sorted(positions))

    def test_global_accessibility_guards_remain_present(self):
        self.assertIn(":focus-visible", self.styles)
        self.assertIn("outline: var(--focus-outline)", self.styles)
        self.assertIn("@media (prefers-reduced-motion: reduce)", self.styles)
        body_rule = re.search(r"body\s*\{([^}]*)\}", self.styles).group(1)
        self.assertNotIn("overflow-x: hidden", body_rule)
