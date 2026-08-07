# =============================================================================
# QATrack+ local settings — TEMPLATE FOR A NEW CENTRE
# =============================================================================
# Copy this file to `qatrack/local_settings.py` and fill in your centre's
# values. Do NOT commit your real `local_settings.py` (it contains secrets).
#
# This template intentionally mirrors the structure of BCHC's dev
# `local_settings.py` so you can see every knob the myQA import system needs.
# Lines marked `# REQUIRED` must be set; lines marked `# OPTIONAL` can be
# left as the default or removed.
# =============================================================================

# Set to True ONLY for development (not safe for production!)
DEBUG = False

# -----------------------------------------------------------------------------
# Database — REQUIRED
# -----------------------------------------------------------------------------
# QATrack+'s own database. PostgreSQL in production; SQLite for tests/dev.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql_psycopg2",
        "NAME": "<your-qatrack-database-name>",
        "USER": "<your-qatrack-db-user>",
        "PASSWORD": "<your-qatrack-db-password>",
        "HOST": "",  # empty string for localhost
        "PORT": "",  # empty string for default
    },
    # The `readonly` alias is required by settings.py (used for SQL report
    # tool). Point it at a read-only role on the same database:
    "readonly": {
        "ENGINE": "django.db.backends.postgresql_psycopg2",
        "NAME": "<your-qatrack-database-name>",
        "USER": "<your-readonly-role-name>",
        "PASSWORD": "<your-readonly-role-password>",
        "HOST": "",
        "PORT": "",
    },
}

# -----------------------------------------------------------------------------
# Hosts / URLs — REQUIRED
# -----------------------------------------------------------------------------
# IP addresses / hostnames QATrack+ will be served from. Update for your
# centre's network.
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "<your-server-hostname>"]

# -----------------------------------------------------------------------------
# myQA database connection — REQUIRED for the myQA import system
# -----------------------------------------------------------------------------
# Connection details for the IBA myQA SQL Server database at your centre.
# The import engine reads these lazily (qatrack.myqa_import._myqa_db_settings
# inside get_connection()) so the module imports cleanly without them — but
# every management command (setup_myqa_tests, import_myqa, etc.) needs them
# to actually do work. The user needs SELECT permission on the MQA_* schema.
MYQA_DB_SERVER = "<your-myQA-server-host>"  # e.g. "10.x.x.x"
MYQA_DB_NAME = "<your-myQA-database-name>"  # e.g. "myQA-MainDB-Server"
MYQA_DB_USERNAME = "<read-only-myQA-user>"
MYQA_DB_PASSWORD = "<your-myQA-user-password>"

# -----------------------------------------------------------------------------
# Hosted subpath — OPTIONAL
# -----------------------------------------------------------------------------
# If QATrack+ is hosted at a subpath behind a reverse proxy (e.g. /qatrack/),
# uncomment and set these. Otherwise leave commented for root-hosting.
# FORCE_SCRIPT_NAME = "/qatrack"
# STATIC_URL = "/qatrack/static/"
# MEDIA_URL = "/qatrack/media/"

# -----------------------------------------------------------------------------
# Auth — OPTIONAL
# -----------------------------------------------------------------------------
# LOGIN_EXEMPT_URLS = [r"^accounts/", r"api/*", r"^oauth2/*", r"^i18n/"]
# LOGIN_REDIRECT_URL = "/qa/unit/"
# LOGIN_URL = "/accounts/login/"

# -----------------------------------------------------------------------------
# Timezone — REQUIRED
# -----------------------------------------------------------------------------
# Used by django-q2 croniter to evaluate cron schedules (the weekly
# setup_myqa_tests schedule uses cron '0 2 * * 0' which fires at 02:00 in
# THIS timezone, not UTC).
TIME_ZONE = "<your-centre-timezone>"  # e.g. "Australia/Sydney", "Europe/London"

# -----------------------------------------------------------------------------
# Precision / display — OPTIONAL (defaults shown)
# -----------------------------------------------------------------------------
# CONSTANT_PRECISION = 8
# DEFAULT_WARNING_MESSAGE = "Do not treat"
# ORDER_UNITS_BY = "number"
# REVIEW_DIFF_COL = False
#
# TEST_STATUS_DISPLAY = {
#     'fail': "Fail", 'not_done': "Not Done", 'done': "Done",
#     'ok': "OK", 'tolerance': "Tolerance", 'action': "Action",
#     'no_tol': "No Tol Set",
# }
# TEST_STATUS_DISPLAY_SHORT = {
#     'fail': "Fail", 'not_done': "Not Done", 'done': "Done",
#     'ok': "OK", 'tolerance': "TOL", 'action': "ACT", 'no_tol': "NO TOL",
# }

# -----------------------------------------------------------------------------
# Email — OPTIONAL (only needed if you enable notifications)
# -----------------------------------------------------------------------------
# EMAIL_NOTIFICATION_USER = None
# EMAIL_NOTIFICATION_PWD = None
# EMAIL_NOTIFICATION_SENDER = "qatrack@yourmailhost.com"
# EMAIL_FAIL_SILENTLY = True
# EMAIL_HOST = ""  # e.g. 'smtp.gmail.com'
# EMAIL_HOST_USER = ""
# EMAIL_HOST_PASSWORD = ""
# EMAIL_USE_TLS = True
# EMAIL_PORT = 587

# -----------------------------------------------------------------------------
# PDF report mirror — OPTIONAL (only needed if you use the linac QA archive)
# -----------------------------------------------------------------------------
# When the linac QA archive generates monthly PDFs, copies are written to a
# local `pdf/` folder AND optionally mirrored to a network drive so
# physicists can retrieve them without server login. Override or disable:
# QA_REPORTS_MIRROR_DIR = "/mnt/your_network_drive/Physics Data/QATrackPlus"
# QA_REPORTS_OUT_DIR = "/var/lib/qatrack/pdf"
