"""Tests for the tolerance name-collision fix in :func:`_get_or_create_tolerance`.

Regression: ``Tolerance.save()`` overwrites the ``name`` via
:func:`qatrack.qa.models.get_tolerance_name` using ``%.3f`` (absolute) or
``%.2f%%`` (percent) — a hardcoded format. Distinct small numeric values
(e.g. ``warn=3e-06`` vs ``warn=5e-06``) truncate to the same name
``"Absolute(-0.000, -0.000, 0.000, 0.000)"``, so the second insert hits the
``Tolerance.name`` UNIQUE constraint and the entire session import fails.

The fix: look up by exact numeric match first; on ``IntegrityError`` fall
back to a name-based lookup using the same ``get_tolerance_name`` format
the model uses so the pre-existing row is found.
"""

from django.contrib.auth.models import User
from django.test import TestCase

from qatrack.myqa_import import _get_or_create_tolerance


class TestGetOrCreateTolerance(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="testuser", password="x")

    def test_returns_none_when_warn_missing(self):
        assert _get_or_create_tolerance(None, 0.5, False, self.user) is None

    def test_returns_none_when_fail_missing(self):
        assert _get_or_create_tolerance(0.5, None, False, self.user) is None

    def test_creates_new_absolute_tolerance(self):
        tol = _get_or_create_tolerance(0.3, 0.5, False, self.user)
        assert tol is not None
        assert tol.type == "absolute"
        assert tol.act_low == -0.5
        assert tol.tol_low == -0.3
        assert tol.tol_high == 0.3
        assert tol.act_high == 0.5

    def test_creates_new_percent_tolerance(self):
        # relative=True means myQA fraction -> QATrack+ percent (x100)
        tol = _get_or_create_tolerance(0.015, 0.025, True, self.user)
        assert tol.type == "percent"
        # warn=0.015*100 = 1.5 ; fail=0.025*100 = 2.5
        assert tol.tol_high == 1.5
        assert tol.act_high == 2.5

    def test_finds_existing_tolerance_by_exact_numeric_match(self):
        first = _get_or_create_tolerance(0.3, 0.5, False, self.user)
        second = _get_or_create_tolerance(0.3, 0.5, False, self.user)
        assert first.id == second.id  # no duplicate created

    def test_micro_value_collision_returns_existing_row(self):
        """The original bug: warn=3e-06 / fail=5e-06 truncates to the same
        ``%.3f`` name as warn=5e-06 / fail=5e-06. The second call must NOT
        raise IntegrityError — it should return the existing row."""
        first = _get_or_create_tolerance(3e-06, 5e-06, False, self.user)
        # Both tolerances truncate to "Absolute(-0.000, -0.000, 0.000, 0.000)"
        # via get_tolerance_name. The second call would normally fail INSERT
        # — the fallback should now return the first row instead.
        second = _get_or_create_tolerance(5e-06, 5e-06, False, self.user)
        assert second is not None
        assert second.id == first.id

    def test_pre_existing_low_precision_row_is_reused(self):
        """Simulate the production scenario: a Tolerance with a ``%.3f``
        name from a prior import collides with a new insert attempt."""
        # Pre-existing row with one set of values that round to 0.000 in %.3f
        existing = _get_or_create_tolerance(1e-06, 2e-06, False, self.user)
        # New attempt with different values that produce the same truncated
        # name. Should NOT raise — should return ``existing``.
        reuse = _get_or_create_tolerance(3e-06, 4e-06, False, self.user)
        assert reuse is not None
        assert reuse.id == existing.id
