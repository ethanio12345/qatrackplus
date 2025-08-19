.. _add_language:

How to Add a New Language to QATrack+
=====================================

This tutorial will guide you through the process of adding a new language to QATrack+. 
The process involves extracting translatable strings, translating them, and configuring 
the system to use the new language.

Prerequisites
------------

- QATrack+ development environment set up
- Python 3.12+ and uv package manager installed
- polib library for PO file handling
- Google Translate library (optional, for automated translation)

Supported Languages
------------------

QATrack+ supports any language that Django supports. Common language codes include:

- **French**: ``fr``
- **Spanish**: ``es`` 
- **German**: ``de``
- **Italian**: ``it``
- **Portuguese**: ``pt``
- **Chinese**: ``zh``
- **Japanese**: ``ja``
- **Korean**: ``ko``
- **Russian**: ``ru``

Step 1: Generate Translation Files
----------------------------------

First, you need to extract all translatable strings from your codebase using Django's 
``makemessages`` command:

.. code-block:: bash

    # Generate Django template and Python file translations
    python manage.py makemessages -l es

Replace ``es`` with your desired language code (e.g., ``fr`` for French, ``de`` for German).

This command will:
- Create a new directory structure: ``qatrack/locale/es/LC_MESSAGES/``
- Generate a ``django.po`` file
- Extract all strings marked for translation in your code

Step 2: Translate the Strings (Optional)
----------------------------------------

You have two options for translating the strings:

**Option A: Manual Translation**
Edit the generated ``.po`` files manually using any text editor. Each entry looks like:

.. code-block:: po

    msgid "Welcome to QATrack+"
    msgstr ""

Change the ``msgstr ""`` to your translation:

.. code-block:: po

    msgid "Welcome to QATrack+"
    msgstr "Bienvenido a QATrack+"

**Option B: Automated Translation (Recommended for initial setup)**
Use the included translation script with Google Translate:

.. code-block:: bash

    # Install required libraries
    uv pip install polib
    uv pip install googletrans==4.0.0rc1

    # Translate using the script
    python scripts/translation.py translate es

The script will:
- Automatically translate all strings to your target language
- Preserve format variables like ``%(name)s`` and ``{variable}``
- Skip non-translatable content (numbers, punctuation, etc.)

**Important**: After automated translation, always review the results for accuracy, 
especially technical terms and medical terminology.

Step 3: Compile the Translations
--------------------------------

Once you have translated the strings, compile them into Django's binary format:

.. code-block:: bash

    # Compile all languages
    python manage.py compilemessages

    # Or compile a specific language
    python manage.py compilemessages --locale=es

This creates ``.mo`` files that Django uses at runtime.

Step 4: Configure Language Settings
-----------------------------------

QATrack+ automatically detects available languages from your locale folders, so you 
typically only need to configure the language settings in your local configuration.

**In ``qatrack/local_settings.py``:**
Configure the language settings for your environment:

.. code-block:: python

    # Language Configuration
    USE_I18N = True
    USE_L10N = True
    LANGUAGE_CODE = 'es'  # Change to your language code

    # Add locale paths to tell Django where to find translation files
    LOCALE_PATHS = [
        os.path.join(os.path.dirname(__file__), 'locale'),
    ]

**Override available languages**
If you want to control which languages appear in the language selector, you can add:

.. code-block:: python

    # Available languages for translation (optional)
    LANGUAGES = [
        ('en', 'English'),
        ('es', 'Spanish'),  # Add your new language here
        ('fr', 'French'),
        # Add more languages as needed
    ]

**How it works:**
QATrack+ automatically scans your ``locale`` directory and detects all available 
languages. The ``available_languages`` context processor will automatically find 
any language folders you create and make them available in the interface.

Known Issues
-----------

**String Extraction Coverage**

We are aware that not all user-facing strings in QATrack+ are currently being 
caught by Django's ``makemessages`` command. This can happen for various reasons:

- **Dynamic strings**: Some text is generated programmatically and not marked for translation
- **Template variables**: Some strings are passed as variables and not directly in templates
- **JavaScript strings**: Client-side text may not be properly marked for translation
- **Database content**: User-generated content stored in the database
- **Third-party packages**: Some dependencies have strings that aren't marked for translation

**What We're Doing**

We are actively working to improve string extraction coverage by:
- Reviewing and updating model fields and configurations with proper translation decorators
- Adding translation markers to dynamic content generation
- Improving JavaScript internationalization support
- Working with the community to identify and fix missing translations

**Current Status**

While we work on improving coverage, the current translation system will capture 
the majority of static user interface text. You may notice some strings remain 
in English - this is expected and will be addressed in future updates.

**Reporting Missing Strings**

If you notice specific strings that aren't being translated, please:
1. Check if the string appears in the generated ``.po`` file
2. If not, the string may need to be marked for translation in the source code
3. Consider reporting the issue on our GitHub repository so we can improve coverage

