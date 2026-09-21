import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class SharedUIComponentsStaticTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        base_dir = Path(settings.BASE_DIR)
        cls.styles = (base_dir / "static" / "css" / "styles.css").read_text(
            encoding="utf-8"
        )
        cls.base_template = (
            base_dir / "templates" / "template_base.html"
        ).read_text(encoding="utf-8")
        cls.application_styles = {
            path.name: path.read_text(encoding="utf-8")
            for path in sorted((base_dir / "static" / "css").glob("*.css"))
            if not path.name.endswith(".min.css")
        }
        start = cls.styles.index("/* Shared cards and panels */")
        end = cls.styles.index("/* Shared pagination and small utilities */")
        cls.components = cls.styles[start:end]

    def _rule(self, selector):
        match = re.search(
            rf"(?:^|\n){re.escape(selector)}\s*\{{([^}}]*)\}}",
            self.styles,
        )
        self.assertIsNotNone(match, f"Missing CSS rule for {selector}")
        return match.group(1)

    def test_shared_components_only_use_foundation_color_tokens(self):
        self.assertNotIn("!important", self.components)
        self.assertIsNone(re.search(r"#[0-9a-f]{3,8}\b", self.components, re.I))
        self.assertIsNone(re.search(r"\brgba?\(", self.components, re.I))

    def test_buttons_keep_aliases_and_cover_interaction_states(self):
        button_rule = self._rule(".btn")
        self.assertIn("min-height: 2.75rem", button_rule)
        self.assertIn("max-inline-size: 100%", button_rule)
        self.assertIn("white-space: normal", button_rule)
        self.assertIn(".btn-sm", self.components)
        self.assertIn(".btn-lg", self.components)

        for selector in (
            ".btn-brand, .btn-primary",
            ".btn-soft, .btn-secondary",
            ".btn-danger",
            ".btn-link",
        ):
            with self.subTest(selector=selector):
                self.assertIn(selector, self.components)

        for state in (
            ":hover",
            ":focus-visible",
            ":active",
            ":disabled",
            '[aria-disabled="true"]',
            '[aria-busy="true"]',
            ".is-loading",
        ):
            with self.subTest(state=state):
                self.assertIn(state, self.components)

        self.assertIn("@keyframes button-loading", self.components)
        loading_rule = self._rule('.btn:is(.is-loading, [aria-busy="true"])')
        self.assertIn("pointer-events: none", loading_rule)

    def test_static_cards_have_no_implicit_hover_animation(self):
        card_rule = self._rule(".card")
        self.assertNotIn("transition", card_rule)
        self.assertIsNone(
            re.search(r"(?<![a-z-])\.card:hover\b", self.styles, re.I)
        )
        self.assertIn(".card-interactive:hover", self.components)
        self.assertIn("a.card:hover", self.components)

        forbidden_static_hovers = {
            "articles.css": ".article-card:hover",
            "videos.css": ".video-card:hover",
            "home.css": ".home-product-card:hover",
            "shop.css": ".shop-card:hover",
            "monetization.css": ".advertising-card:hover",
        }
        for stylesheet, selector in forbidden_static_hovers.items():
            with self.subTest(stylesheet=stylesheet, selector=selector):
                self.assertNotIn(selector, self.application_styles[stylesheet])

    def test_form_states_cover_django_bootstrap_and_accessibility_hooks(self):
        for hook in (
            ".form-control",
            ".form-select",
            ".form-text",
            ".helptext",
            ".errorlist",
            ".invalid-feedback",
            ".valid-feedback",
            '[aria-invalid="true"]',
            "[aria-describedby]",
            ":focus-visible",
            ":disabled",
            "[readonly]",
            ":user-invalid",
            ":user-valid",
            '[type="checkbox"]',
            '[type="radio"]',
            '[type="file"]::file-selector-button',
        ):
            with self.subTest(hook=hook):
                self.assertIn(hook, self.components)

        self.assertIn("background-color: var(--surface-0)", self.components)
        self.assertNotIn("background: var(--surface-0)", self._rule(".form-select"))
        self.assertIn("border-inline-start-width", self.components)

    def test_alerts_keep_semantics_and_all_variants(self):
        for selector in (
            ".alert-success",
            ".alert-danger, .alert-error",
            ".alert-warning",
            ".alert-info",
            ".alert .btn-close",
        ):
            with self.subTest(selector=selector):
                self.assertIn(selector, self.components)

        self.assertIn('aria-live="polite"', self.base_template)
        self.assertIn('role="alert"', self.base_template)

    def test_badges_expose_semantic_variants_without_business_status_logic(self):
        for selector in (
            ".badge-neutral",
            ".badge-success",
            ".badge-warning",
            ".badge-danger",
            ".badge-info",
            ".status-badge::before",
        ):
            with self.subTest(selector=selector):
                self.assertIn(selector, self.components)

    def test_table_overflow_is_scoped_to_the_responsive_container(self):
        responsive_rule = self._rule(".table-responsive")
        self.assertIn("overflow-x: auto", responsive_rule)
        self.assertIn("max-width: 100%", responsive_rule)
        self.assertIn(".table-responsive:focus-visible", self.components)
        self.assertIn(".table-responsive > .table", self.styles)

        body_rule = self._rule("body")
        self.assertNotIn("overflow-x: hidden", body_rule)
        self.assertIsNone(
            re.search(r"(?:^|[;}])\s*\.table\s*\{[^}]*min-width", self.styles)
        )

    def test_empty_state_has_optional_content_parts_and_legacy_aliases(self):
        for selector in (
            ".empty-state-icon",
            ".articles-empty-icon",
            ".cart-empty-icon",
            ".empty-state-title",
            ".empty-state-description",
            ".empty-state-action",
            ".articles-empty",
            ".videos-empty",
            ".cart-empty",
            ".orders-empty",
            ".category-empty-state",
            ".monetization-empty",
        ):
            with self.subTest(selector=selector):
                self.assertIn(selector, self.components)

        icon_rule = re.search(
            r":where\(\.empty-state-icon,[^{]+\)\s*\{([^}]*)\}",
            self.components,
        )
        self.assertIsNotNone(icon_rule)
        self.assertNotIn("content:", icon_rule.group(1))

    def test_motion_and_narrow_viewport_guards_cover_component_behavior(self):
        self.assertIn("@media (prefers-reduced-motion: reduce)", self.styles)
        self.assertIn("animation-duration: .01ms", self.styles)
        self.assertIn("@media (max-width: 991.98px)", self.styles)
        self.assertIn("@media (max-width: 767.98px)", self.styles)
        self.assertIn("@media (max-width: 419.98px)", self.styles)

    def test_core_component_color_pairs_meet_wcag_aa(self):
        root = re.search(r":root\s*\{(.*?)\n\}", self.styles, re.S).group(1)
        colors = dict(
            re.findall(r"(--[a-z0-9-]+)\s*:\s*(#[0-9a-f]{3,6})\s*;", root, re.I)
        )
        pairs = (
            ("--surface-0", "--brand-700"),
            ("--surface-0", "--brand-900"),
            ("--surface-2", "--ink-700"),
            ("--brand-50", "--brand-800"),
        )

        for background, foreground in pairs:
            with self.subTest(background=background, foreground=foreground):
                ratio = self._contrast_ratio(colors[background], colors[foreground])
                self.assertGreaterEqual(ratio, 4.5)

        for foreground in (
            "--color-danger",
            "--color-success",
            "--color-warning",
            "--color-info",
        ):
            with self.subTest(tinted_background=foreground):
                background = self._mix_colors(
                    colors[foreground], colors["--surface-0"], 0.07
                )
                ratio = self._contrast_ratio(background, colors[foreground])
                self.assertGreaterEqual(ratio, 4.5)

    @classmethod
    def _contrast_ratio(cls, first, second):
        lighter, darker = sorted(
            (cls._relative_luminance(first), cls._relative_luminance(second)),
            reverse=True,
        )
        return (lighter + 0.05) / (darker + 0.05)

    @staticmethod
    def _relative_luminance(hex_color):
        value = hex_color.lstrip("#")
        if len(value) == 3:
            value = "".join(character * 2 for character in value)
        channels = [int(value[index : index + 2], 16) / 255 for index in (0, 2, 4)]
        linear = [
            channel / 12.92
            if channel <= 0.04045
            else ((channel + 0.055) / 1.055) ** 2.4
            for channel in channels
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    @staticmethod
    def _mix_colors(foreground, background, foreground_weight):
        def channels(value):
            value = value.lstrip("#")
            if len(value) == 3:
                value = "".join(character * 2 for character in value)
            return [int(value[index : index + 2], 16) for index in (0, 2, 4)]

        mixed = (
            round(
                foreground_channel * foreground_weight
                + background_channel * (1 - foreground_weight)
            )
            for foreground_channel, background_channel in zip(
                channels(foreground), channels(background)
            )
        )
        return "#" + "".join(f"{channel:02x}" for channel in mixed)
