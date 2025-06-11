Reference and Tolerance History Display Fix
=====================================

Original Issue
------------
The application wasn't properly displaying the history of reference and tolerance changes in the UnitTestInfo admin interface. While the history tracking existed in the database through the ``UnitTestInfoChange`` model, there was no proper display mechanism.

Code Changes Made
---------------

1. Added History Field to Admin Display
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Added a new ``history`` field to the ``UnitTestInfoAdmin`` fieldsets::

    fieldsets = [
        (None, {
            'fields': (
                'unit',
                'test',
                'reference',
                'tolerance',
            )
        }),
        (_('Reference Value'), {
            'fields': (
                'test_type',
                'reference_value',
                'reference_set_by',
                'reference_set',
                'comment',
            ),
        }),
        (_('History'), {
            'fields': ('history',),
        }),
    ]

2. Implemented History Display Method
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Added a new ``history`` method to the ``UnitTestInfoAdmin`` class::

    def history(self, obj):
        """Display history of reference and tolerance changes"""
        if not obj:
            return _("No history available")

        changes = models.UnitTestInfoChange.objects.filter(
            unit_test_info=obj
        ).order_by('-changed')

        if not changes:
            return _("No history available")

        # Create pairs of changes to show old and new values
        history = []
        current = {
            'reference': obj.reference,
            'tolerance': obj.tolerance,
        }
        
        for change in changes:
            history.append((current, change))
            current = {
                'reference': change.reference,
                'tolerance': change.tolerance,
            }

        t = loader.get_template("admin/qa/unittestinfo/history.html")
        return t.render({'history': history})
    history.short_description = _("Reference & Tolerance History")

3. Added History Tracking in Save Method
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Enhanced the form save logic to track changes::

    def save_model(self, request, test_info, form, change):
        """create new reference when user updates value"""

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

Key Improvements
--------------

1. Change Tracking:
   - Now properly records both reference and tolerance changes
   - Stores who made the change and when
   - Includes optional comments explaining why changes were made

2. History Display:
   - Shows a chronological history of changes
   - Displays both old and new values for each change
   - Clearly indicates which values (reference or tolerance) were modified
   - Integrates with Django's admin interface

3. User Experience:
   - Added a dedicated history section in the admin interface
   - Provides clear visibility of all historical changes
   - Maintains audit trail for quality assurance purposes