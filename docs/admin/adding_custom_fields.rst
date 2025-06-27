Adding Custom Fields to QATrack+ Models
==========================================

This guide explains how to safely add custom fields to QATrack+ models when you need to store additional information.

Quick Overview
--------------

Adding a custom field involves:

1. **Add field to model** - Modify the Python model class
2. **Create migration** - Generate database schema changes  
3. **Apply migration** - Update the database
4. **Update admin** (optional) - Make field visible in Django Admin

Safety First
------------

**Always backup your database before making changes!**

Safe practices:
- Use ``null=True, blank=True`` for optional fields (safest approach)
- Test on development environment first
- Adding fields is safe - removing fields can cause data loss

Step-by-Step Guide
------------------

Step 1: Add Field to Model
~~~~~~~~~~~~~~~~~~~~~~~~~~

Edit the appropriate model file (``qatrack/qa/models.py`` for Test-related fields):

.. code-block:: python

    # Example: Adding a department field to the Test model
    class Test(models.Model, TestPackMixin):
        # ... existing fields ...
        
        department = models.CharField(
            max_length=50,
            choices=[
                ('physics', 'Physics'),
                ('dosimetry', 'Dosimetry'),
                ('imaging', 'Imaging'),
            ],
            null=True,
            blank=True,
            help_text="Department responsible for this test"
        )

Step 2: Create Migration
~~~~~~~~~~~~~~~~~~~~~~~

Generate the database migration:

.. code-block:: bash

    python manage.py makemigrations qa

Step 3: Apply Migration
~~~~~~~~~~~~~~~~~~~~~~

Update the database:

.. code-block:: bash

    python manage.py migrate qa

Step 4: Update Admin Interface (Optional)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To show the field in Django Admin, edit ``qatrack/qa/admin.py``:

.. code-block:: python

    class TestAdmin(admin.ModelAdmin):
        list_display = [
            # ... existing fields ...
            'department',  # Add to list view
        ]
        
        list_filter = [
            # ... existing fields ...
            'department',  # Add to filter sidebar
        ]

Common Field Types
------------------

.. code-block:: python

    # Text field
    notes = models.CharField(max_length=255, blank=True)
    
    # Long text
    description = models.TextField(blank=True)
    
    # Number
    priority_level = models.IntegerField(default=1)
    
    # True/False
    is_critical = models.BooleanField(default=False)
    
    # Date
    last_calibration = models.DateField(null=True, blank=True)
    
    # Choice field
    status = models.CharField(
        max_length=20,
        choices=[
            ('active', 'Active'),
            ('inactive', 'Inactive'),
        ],
        default='active'
    )
    
    # Link to another model
    responsible_person = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

Common Models to Extend
----------------------

- ``Test`` (``qatrack/qa/models.py``) - Individual test definitions
- ``TestList`` (``qatrack/qa/models.py``) - Test list definitions  
- ``Unit`` (``qatrack/units/models.py``) - Equipment/machine definitions
- ``TestInstance`` (``qatrack/qa/models.py``) - Individual test results

Complete Example
----------------

Adding a ``priority`` field to tests:

**1. Edit qatrack/qa/models.py:**

.. code-block:: python

    class Test(models.Model, TestPackMixin):
        # ... existing fields ...
        
        priority = models.CharField(
            max_length=10,
            choices=[
                ('low', 'Low'),
                ('medium', 'Medium'),
                ('high', 'High'),
            ],
            default='medium',
            null=True,
            blank=True,
            help_text="Priority level for this test"
        )

**2. Create and apply migration:**

.. code-block:: bash

    python manage.py makemigrations qa
    python manage.py migrate qa

**3. Update admin (qatrack/qa/admin.py):**

.. code-block:: python

    class TestAdmin(admin.ModelAdmin):
        list_display = ['name', 'category', 'priority']
        list_filter = ['category', 'priority']

That's it! Your custom field is now available.

Important Notes
--------------

**Safe Operations:**
- Adding fields with ``null=True, blank=True``
- Increasing ``max_length`` of text fields
- Adding new choices to choice fields

**Risky Operations:**
- Removing fields
- Changing field types
- Adding required fields without defaults

**Best Practices:**
- Use ``null=True, blank=True`` for optional fields
- Test changes before applying to production