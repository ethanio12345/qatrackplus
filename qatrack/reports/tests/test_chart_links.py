from urllib.parse import parse_qs, urlparse

from django.test import TestCase
from django.utils import timezone

from qatrack.qa.tests import utils
from qatrack.reports import chart_links
from qatrack.reports.qc.testlistinstance import TestListInstanceDetailsReport


class TestChartUrls(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.window = (
            self.now.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
            self.now,
        )
        self.unit = utils.create_unit()
        self.test = utils.create_test()

    def test_chart_urls_contain_required_params(self):
        # control chart needs at least one valid status to render data
        utils.create_status()
        run, control = chart_links.chart_urls(self.test, self.unit, *self.window)
        run_q = parse_qs(urlparse(run).query)
        assert run_q["units[]"] == [str(self.unit.pk)]
        assert run_q["tests[]"] == [str(self.test.pk)]
        assert "date_range" in run_q
        assert urlparse(run).path.endswith("/charts/")

        control_q = parse_qs(urlparse(control).query)
        assert urlparse(control).path.endswith("/charts/control_chart.png")
        assert control_q["tests[]"] == [str(self.test.pk)]
        # control chart needs statuses to render data
        assert len(control_q["statuses[]"]) >= 1

    def test_chart_urls_absolute(self):
        run, control = chart_links.chart_urls(self.test, self.unit, *self.window)
        assert run.startswith("http")
        assert control.startswith("http")


class TestIncludeChartLinksFlag(TestCase):
    def _setup_utc_with_instance(self, chart_visibility=True):
        utc = utils.create_unit_test_collection()
        tli = utils.create_test_list_instance(unit_test_collection=utc)
        ti = utils.create_test_instance(test_list_instance=tli)
        if not chart_visibility:
            ti.unit_test_info.test.chart_visibility = False
            ti.unit_test_info.test.save()
        return utc, ti

    def test_default_off_no_chart_columns(self):
        utc, ti = self._setup_utc_with_instance()
        rep = TestListInstanceDetailsReport(
            report_opts={"unit_test_collection": [utc.pk]}
        )
        rep.report_format = "pdf"
        html = rep.to_html()
        assert "Run Chart" not in html
        assert "Control Chart" not in html

    def test_flag_on_adds_links_for_chartable_test(self):
        utc, ti = self._setup_utc_with_instance(chart_visibility=True)
        rep = TestListInstanceDetailsReport(
            base_opts={
                "include_chart_links": True,
                "chart_window": {
                    "start": timezone.now() - timezone.timedelta(days=30),
                    "end": timezone.now(),
                },
            },
            report_opts={"unit_test_collection": [utc.pk]},
        )
        rep.report_format = "pdf"
        html = rep.to_html()
        assert "Run Chart" in html
        assert "Control Chart" in html
        # link should reference charts endpoint
        assert "/charts/control_chart.png" in html

    def test_flag_on_skips_non_chartable_test(self):
        utc, ti = self._setup_utc_with_instance(chart_visibility=False)
        rep = TestListInstanceDetailsReport(
            base_opts={
                "include_chart_links": True,
                "chart_window": {
                    "start": timezone.now() - timezone.timedelta(days=30),
                    "end": timezone.now(),
                },
            },
            report_opts={"unit_test_collection": [utc.pk]},
        )
        rep.report_format = "pdf"
        html = rep.to_html()
        # header still present (flag on) but no actual link rendered for the row
        assert html.count("/charts/control_chart.png") == 0
