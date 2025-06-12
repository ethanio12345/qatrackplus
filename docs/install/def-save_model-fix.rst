def-save_model-fix

When a tolerance was saved it would override the previous tolerance. 
file: qatrack/qa/admin.py

Old implementation:
def save_model(self, request, test_info, form, change):
        """create new reference when user updates value"""
        super().save_model(request, test_info, form, change)

        if any(k in form.changed_data for k in ['comment', 'reference_value', 'tolerance']):
            if form.instance and form.instance.pk:
                old = models.UnitTestInfo.objects.get(pk=form.instance.pk)
                models.UnitTestInfoChange.objects.create(
                    unit_test_info=old,
                    comment=form.cleaned_data["comment"],
                    reference=old.reference,
                    reference_changed=old.reference != form.instance.reference,
                    tolerance=old.tolerance,
                    tolerance_changed=old.tolerance != form.instance.tolerance,
                    changed_by=request.user,
                )

Why it didn't work:
The line super().save_model(...) saves the new reference/tolerance to the database.
After this, fetching old = models.UnitTestInfo.objects.get(pk=form.instance.pk) retrieves the object with the new values already saved.
As a result, the history record (UnitTestInfoChange) is created with the new values as the "old" values.
This causes the history table to show the new value for both the current and previous entries, effectively overwriting the old value in the display.

New implementation:
 def save_model(self, request, test_info, form, change):
        # Fetch the old instance from the DB before saving changes
        if test_info.pk:
            old = models.UnitTestInfo.objects.get(pk=test_info.pk)
            old_reference = old.reference
            old_tolerance = old.tolerance
        else:
            old_reference = None
            old_tolerance = None

        # Save the new values
        super().save_model(request, test_info, form, change)

        # Now create the history record using the old values
        if any(k in form.changed_data for k in ['comment', 'reference_value', 'tolerance']):
            if form.instance and form.instance.pk:
                models.UnitTestInfoChange.objects.create(
                    unit_test_info=form.instance,
                    comment=form.cleaned_data["comment"],
                    reference=old_reference,
                    reference_changed=old_reference != form.instance.reference,
                    tolerance=old_tolerance,
                    tolerance_changed=old_tolerance != form.instance.tolerance,
                    changed_by=request.user,
                )
                
Why the new implementation works:
The old values (old_reference, old_tolerance) are fetched before saving the new values.
Only after capturing the old values do we call super().save_model(...) to update the object.
The history record is then created with the true old values, ensuring the history table accurately reflects the sequence of changes.


Testing:
Created test "test_history_records_old_values" in qatrack/qa/tests/test_admin.py since this error was happening but there was no test to catch it.
Now if something like this happens again, the test will catch it!