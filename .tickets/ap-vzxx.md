---
id: ap-vzxx
status: closed
deps: []
links: []
created: 2026-10-18T00:22:02Z
type: bug
priority: 2
assignee: Sampath Kumar
---
# Log swallowed exceptions in plugin manager and verifier probes

## Acceptance Criteria

PluginManager.trigger_post_registration and trigger_on_search log plugin errors and never raise; verifier probe failures are logged; tests cover both plugin hooks with caplog; validate_change --all has 0 swallowed-exception violations.


## Notes

**2026-10-18T00:22:17Z**

progress: plugin manager + verifier now log instead of pass; tests/test_plugins.py added

**2026-10-18T00:22:32Z**

validate_change PASS (4 passed); --all PASS (0 violations, was 4 swallowed-exception). Tests failed before fix (2 failed), pass after. Rubric: 1 Y (2 criteria->2 tests), 2 Y, 3 Y (no network), 4 N/A, 5 Y (test class docstring), 6 N/A (no new fetch), 7 N/A, 8 Y. Files: ards/plugins/base.py, ards/server/verifier.py, tests/test_plugins.py
