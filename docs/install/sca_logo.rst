.. _sca_logo:

Adding the Saskatchewan Cancer Agency Logo to Reports
==================================================

QATrack+ allows you to add your organization's logo to reports. This guide will walk you through adding the Saskatchewan Cancer Agency (SCA) logo to your reports.

Prerequisites
------------

Before starting, ensure you have:

* A copy of your organization's logo in JPG format
* Access to your QATrack+ installation files
* Appropriate permissions to modify the codebase

Adding the Logo
--------------

1. Create the directory structure for storing the logo:

   .. code-block:: bash

       mkdir -p qatrack/reports/static/reports/img/

2. Place your logo file in this directory:

   .. code-block:: bash

       # Copy your logo file to qatrack/reports/static/reports/img/sca_logo.jpg

3. Update the report header template to include the logo. Edit `qatrack/reports/templates/reports/_header.html`:

   .. code-block:: html

       {% load i18n %}
       {% load static %}
       {% load reports_tags %}

       <style>
       .logo-hidden {
         opacity: 0;
       }
       .logo-visible {
         opacity: 1;
       }
       .logo {
         max-height: 60px;
         margin-top: 20px;
         transition: opacity 0.2s;
       }
       </style>

       <div class="row">
         <div class="col-xs-8">
           <h1 style="color:#777; margin-top: 20px; " class="pdf">{% trans "QATrack+ Reports" %}</h1>
           <h5 style="color: #1c9aea; font-weight: bold; padding-left: 4px;">{{ report_title }}</h5>
         </div>
         <div class="col-xs-4 text-right">
           <img src="{% static 'reports/img/sca_logo.jpg' %}" alt="Saskatchewan Cancer Agency" class="logo {% if include_logo %}logo-visible{% else %}logo-hidden{% endif %}"/>
         </div>
       </div>

4. Update the database model to include the logo toggle option:

   .. code-block:: python

       # In qatrack/reports/models.py
       include_logo = models.BooleanField(default=True)

5. Update the report form to include the logo checkbox:

   .. code-block:: python

       # In qatrack/reports/forms.py
       fields = ("title", "report_type", "report_format", "visible_to", "include_signature", "include_logo")

6. Run database migrations:

   .. code-block:: bash

       python manage.py makemigrations reports
       python manage.py migrate reports

7. Collect static files:

   .. code-block:: bash

       python manage.py collectstatic

Features
--------

* Toggle logo visibility using a checkbox in the report settings
* Default visibility can be controlled through the model's default value

Configuration
------------

The logo dimensions are controlled by CSS in the template:

* Maximum height: 60px
* Top margin: 20px
* Smooth opacity transition: 0.2 seconds

You can adjust these values in the template's style section to match your needs.

Troubleshooting
--------------

If the logo doesn't appear:

1. Ensure the logo file exists in the correct directory
2. Check that the file extension matches (.jpg vs .png)
3. Run `collectstatic` to ensure static files are properly collected
4. Verify the template tags are properly loaded
5. Check browser console for any 404 errors

Notes
-----

* The logo is positioned in the top right corner of reports
* The visibility toggle is saved with each report configuration
* The feature works seamlessly with both HTML and PDF report formats 