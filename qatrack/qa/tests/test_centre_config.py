"""Tests for the centre-config externalisation (Change A).

Covers:
- ``_load_centre_config()`` loader (cache, fallback, schema)
- ``_default_category()`` triple-fallback lookup
- ``get_linac_unit_type_names()`` config-driven allowlist (incl. RFT26 fix)
- ``infer_frequency()`` default behaviour + override path
- ``create_myqa_units._classify_device()`` config-driven classification
"""

import importlib
import warnings
from unittest import mock

from django.test import TestCase

from qatrack.myqa_import import (
    _BCHC_DEFAULT_CENTRE_CONFIG,
    _load_centre_config,
    infer_frequency,
)


class TestLoadCentreConfig(TestCase):
    def _reload(self):
        """Force re-import so the module-level cache is reset."""
        import qatrack.myqa_import as m

        importlib.reload(m)
        return m

    def test_returns_dict_with_required_keys(self):
        cfg = _load_centre_config()
        assert isinstance(cfg, dict)
        for key in ("network_name", "sites", "device_classes", "linac_unit_type_names"):
            assert key in cfg, f"missing required key: {key}"

    def test_cached_result_is_identical(self):
        # Second call returns the same object (cache hit).
        first = _load_centre_config()
        second = _load_centre_config()
        assert first is second

    def test_falls_back_to_bchc_defaults_when_yaml_absent(self):
        """When the YAML is missing the loader returns the in-code default
        dict and emits a DeprecationWarning. The default must reproduce
        today's BCHC behaviour."""
        with mock.patch("qatrack.myqa_import.os.path.exists", return_value=False):
            # Reset the module-level cache so the next call re-reads.
            import qatrack.myqa_import as m

            with mock.patch.object(m, "_CENTRE_CONFIG_CACHE", None):
                with mock.patch.object(m, "_CENTRE_CONFIG_FALLBACK_WARNED", False):
                    with warnings.catch_warnings(record=True) as caught:
                        warnings.simplefilter("always")
                        cfg = m._load_centre_config()
        assert cfg == _BCHC_DEFAULT_CENTRE_CONFIG
        assert any(
            issubclass(w.category, DeprecationWarning) for w in caught
        ), "expected a DeprecationWarning when YAML is absent"

    def test_device_classes_are_ordered_list(self):
        """``device_classes`` must be a list (order matters — first match
        wins) and each entry must have ``pattern``, ``unit_class``,
        ``unit_type`` keys."""
        cfg = _load_centre_config()
        assert isinstance(cfg["device_classes"], list)
        assert len(cfg["device_classes"]) > 0
        for rule in cfg["device_classes"]:
            assert "pattern" in rule
            assert "unit_class" in rule
            assert "unit_type" in rule

    def test_linac_unit_type_names_includes_treatment_linac(self):
        """The latent bug fix: 'Treatment LINAC' must be in the allowlist
        so myQA-created linacs (RFT26 etc.) are visible to linac-scoped
        operations."""
        cfg = _load_centre_config()
        assert "Treatment LINAC" in cfg["linac_unit_type_names"]


class TestDefaultCategory(TestCase):
    """``_default_category()`` should resolve via slug → first → PK 1."""

    def test_slug_uncategorised_wins(self):
        from qatrack.qa.management.commands.setup_myqa_tests import (
            _default_category_cached,
        )
        from qatrack.qa.models import Category

        # Ensure a Category with the expected slug exists. The default
        # QATrack+ fixture ships "Uncategorised" but the slug might be
        # either "uncategorised" or something else; create what we expect.
        cat, _ = Category.objects.get_or_create(
            slug="uncategorised",
            defaults={"name": "Uncategorised"},
        )
        _default_category_cached.cache_clear()
        result = _default_category_cached()
        assert result.slug == "uncategorised"

    def test_falls_back_to_first_when_slug_absent(self):
        from qatrack.qa.management.commands.setup_myqa_tests import (
            _default_category_cached,
        )
        from qatrack.qa.models import Category

        # Ensure no Category has the slug.
        Category.objects.filter(slug="uncategorised").delete()
        # Create at least one Category so the "first()" fallback has something to return.
        # Use a fresh slug to avoid PK collisions with fixture-loaded categories.
        sample = Category.objects.create(
            name="Sample Fallback Category", slug="sample-fallback"
        )
        _default_category_cached.cache_clear()
        result = _default_category_cached()
        # The result must be the lowest-PK Category remaining.
        assert result.pk == Category.objects.order_by("id").first().pk
        # Cleanup
        sample.delete()

    def test_falls_back_to_pk1_when_table_empty(self):
        from qatrack.qa.management.commands.setup_myqa_tests import (
            _default_category_cached,
        )
        from qatrack.qa.models import Category

        Category.objects.all().delete()
        _default_category_cached.cache_clear()
        with self.assertRaises(Category.DoesNotExist):
            _default_category_cached()


class TestGetLinacUnitTypeNames(TestCase):
    def test_default_includes_treatment_linac(self):
        from qatrack.reports.qa_selection import LINAC_UNIT_TYPE_NAMES

        # Sanity: the historical module-level constant also includes it now.
        assert "Treatment LINAC" in LINAC_UNIT_TYPE_NAMES

    def test_function_returns_default_when_no_override(self):
        from qatrack.reports.qa_selection import get_linac_unit_type_names

        result = get_linac_unit_type_names()
        assert "Treatment LINAC" in result
        assert isinstance(result, tuple)

    def test_override_via_centre_config(self):
        """When the centre config has an override, the function returns it
        verbatim (as a tuple)."""
        from qatrack.reports.qa_selection import get_linac_unit_type_names

        custom = ["Linac", "Treatment LINAC", "CustomLinac"]
        with mock.patch(
            "qatrack.myqa_import._load_centre_config",
            return_value={"linac_unit_type_names": custom},
        ):
            result = get_linac_unit_type_names()
        assert result == ("Linac", "Treatment LINAC", "CustomLinac")


class TestInferFrequency(TestCase):
    def test_default_dotted_path_patterns(self):
        cases = [
            ("5.Tmt.Linac.D", "daily"),
            ("5.Tmt.Linac.W", "weekly"),
            ("5.Tmt.Linac.M", "monthly"),
            ("5.Tmt.Linac.Q", "quarterly"),
            ("5.Tmt.Linac.Y", "annual"),
            ("5.Tmt.Linac.6M", "semi-annual"),
            ("5.Tmt.Linac.C", "once_off"),
            ("Commissioning.Beam", "once_off"),
            ("Daily Constancy Check", "daily"),
            ("Monthly QA", "monthly"),
            ("Unknown Thing", "other"),
        ]
        for tn, expected in cases:
            assert (
                infer_frequency(tn) == expected
            ), f"infer_frequency({tn!r}) returned {infer_frequency(tn)!r}, expected {expected!r}"

    def test_monthly_dosimetry_path_does_not_match_daily(self):
        # Regression: "5.Tmt.Linac.M.Dosimetry" — the M is the frequency
        # code; "Dosimetry" is a longer segment. The .D in .Dosimetry must
        # NOT accidentally match the daily pattern.
        assert infer_frequency("5.Tmt.Linac.M.Dosimetry") == "monthly"

    def test_override_via_centre_config(self):
        """A centre with non-IBA TaskNames can add a pattern via YAML
        without code changes."""
        # Reset the pattern cache so the override takes effect.
        import qatrack.myqa_import as m

        with mock.patch.object(m, "_FREQ_PATTERNS_CACHE", None):
            custom_cfg = {
                "frequency_inference": {
                    "monthly": [
                        r"^Monthly\s"
                    ],  # matches "Monthly QA" but not "5.Tmt.Linac.M"
                    "daily": [r"\.d(?:[^a-z]|$)", "daily"],
                    "weekly": [r"\.w(?:[^a-z]|$)", "weekly"],
                    "quarterly": [r"\.q(?:[^a-z]|$)", "quarterly"],
                    "annual": [r"\.y(?:[^a-z]|$)", "annual", "yearly"],
                    "semi-annual": [
                        r"\.6m(?:[^a-z]|$)",
                        "6 monthly",
                        "6-monthly",
                        "biannual",
                    ],
                    "once_off": [r"\.c(?:[^a-z]|$)", "commissioning"],
                }
            }
            with mock.patch(
                "qatrack.myqa_import._load_centre_config",
                return_value=custom_cfg,
            ):
                # "Monthly QA" matches the override's monthly pattern.
                assert m.infer_frequency("Monthly QA") == "monthly"
                # The IBA dotted-path still works via the override's other entries.
                assert m.infer_frequency("5.Tmt.Linac.D") == "daily"


class TestCreateMyqaUnitsClassification(TestCase):
    """``_classify_device()`` and ``_site_for()`` should be config-driven."""

    def test_classify_uses_first_matching_pattern(self):
        from qatrack.qa.management.commands.create_myqa_units import _classify_device

        # Sample devices across categories.
        cases = [
            ("RFT26 - H197686", "Linac", "Treatment LINAC"),
            ("LA317 - H192972", "Linac", "Treatment LINAC"),
            ("CPMCC (F) NE 2571 - 3708", "Ion Chamber", "CPMCC Field Ion Chamber"),
            (
                "CPMCC (Sec. Std) IBA FC65-G - 5413",
                "Ion Chamber",
                "Secondary Standard Chamber",
            ),
            ("CPMCC Well Chamber - A060254", "Well Chamber", "Well Chamber"),
            ("CPMCC Digital Thermometer - 210381212", "Thermometer", "Thermometer"),
            (
                "CPMCC Fluke Ion Chamber - 0000005509",
                "Ion Chamber",
                "CPMCC Field Ion Chamber",
            ),
            ("Something Completely Unknown", "Other", "Unknown Device"),
        ]
        for name, expected_cls, expected_type in cases:
            actual_cls, actual_type = _classify_device(name)
            assert (actual_cls, actual_type) == (expected_cls, expected_type), (
                f"_classify_device({name!r}) returned {(actual_cls, actual_type)!r}, "
                f"expected {(expected_cls, expected_type)!r}"
            )

    def test_rft26_now_classified_as_linac(self):
        """Regression for the latent UnitType bug. Pre-fix the number-range
        rule (435-441 → Safety) misclassified RFT26 as Audit/Safety."""
        from qatrack.qa.management.commands.create_myqa_units import _classify_device

        cls, typ = _classify_device("RFT26 - H197686")
        assert typ == "Treatment LINAC"
        assert cls == "Linac"

    def test_site_resolution_uses_first_matching_prefix(self):
        from qatrack.qa.management.commands.create_myqa_units import _site_for

        assert _site_for("CPMCC anything") == (
            "westmead-equipment",
            "Westmead Equipment",
        )
        assert _site_for("BCHC anything") == (
            "blacktown-equipment",
            "Blacktown Equipment",
        )
        assert _site_for("RFT26 - H197686") == ("westmead", "Westmead")
        assert _site_for("Unknown Device With No Prefix") is None
