## MODIFIED Requirements

### Requirement: Optional chart-link rendering in details report
The `TestListInstanceDetailsReport` template SHALL support an opt-in `include_chart_links` flag. When set, each test row SHALL render two additional link cells: one to the live run chart and one to the control chart, scoped to that test and unit. When unset (default), the template renders exactly as today with no chart columns.

#### Scenario: Existing saved reports unaffected
- **WHEN** an existing SavedReport of type `testlistinstance_details` is rendered
- **THEN** no chart-link columns appear (the flag defaults off)

#### Scenario: Flag enabled adds chart links
- **WHEN** the details report is rendered with `include_chart_links=True` for a test on a unit
- **THEN** the row includes a run-chart link to `/qa/charts/?units[]=<unit>&tests[]=<test>&...` and a control-chart link to `/qa/charts/control_chart.png?tests[]=<test>&...`

#### Scenario: Non-chartable test
- **WHEN** a Test has `chart_visibility=False`
- **THEN** no chart links are rendered for that row even when the flag is on
