# Copy References and Tolerances Bug Fix

## Issue Description
A bug was identified in QATrack+ related to copying test references and tolerances between units. The issue manifested in the admin interface during a two-stage form submission process.

## Root Cause
The bug occurred because in stage 2 of the form submission, only the `confirm` value was being set to 'Confirm', but the `stage` value was not being set to '2'. The view requires both values to be properly set for the form to process correctly.

## Files Modified

### 1. Form Definition (`qatrack/qa/forms/admin.py`)
- Created proper form definition in the forms directory
- Added necessary form fields including hidden fields for stage and confirm values:
  ```python
  stage = forms.IntegerField(widget=forms.HiddenInput(), required=False)
  confirm = forms.CharField(widget=forms.HiddenInput(), required=False)
  ```
- Implemented validation logic to ensure:
  - Source and destination units are different
  - Content type is valid
  - Test list exists on the source unit

### 2. View (`qatrack/qa/views/admin.py`)
- Imports the form from the correct location
- Handles both stages of form submission
- Processes the form data and copies references when both stage=2 and confirm=Confirm are set

### 3. Template (`qatrack/qa/templates/qa/copy_refs_tols.html`)
- Updated to handle two-stage form submission
- Includes proper hidden fields for stage and confirm values

## Testing
The fix was verified by running the test suite, specifically:
```bash
python -m pytest qatrack/qa/tests/test_admin.py::TestSetReferencesAndTolerancesForm::test_save
```

The test now passes successfully, confirming that references and tolerances are properly copied between units.