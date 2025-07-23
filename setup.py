import os
import re

from setuptools import find_packages, setup

root = os.path.dirname(__file__)

settingsf = open(os.path.join(root, 'qatrack', 'settings.py'), 'r')

__version__ = re.findall(r"""VERSION\s+=\s+['"]+(.*)['"]""", settingsf.read())[0]

setup(
    name='qatrackplus',
    version=__version__,
    packages=find_packages(exclude=["local_settings", "local_test_settings"]),
    include_package_data=True,
    description=(
        "QATrack+ is an open source application for managing QC data in radiotherapy and diagnostic imaging clinics"
    ),
    long_description=open('README.md').read(),
    zip_safe=False,
    url='http://qatrackplus.com/',
    keywords="QATrack+ medical physics TG142 quality assurance linac CT MRI radiotherapy diagnostic imaging",
    author='QATrack+ contributors',
    author_email='randy@multileaf.ca',
    dependency_links=[
        "git+https://github.com/randlet/django-genericdropdown.git@473ff52610af659f7d2a3616a6e3322e21673b4d#egg=django_genericdropdown"  # noqa: E501
        "git+https://github.com/randlet/django-recurrence.git@b3a73e8e03952107e58382922fec37aead31fd6f#egg=django-recurrence"  # noqa: E501
        "git+https://github.com/randlet/django-sql-explorer.git@12802fe83f9c45fd0bbe9610cb442dcfc5666d44#egg=django-sql-explorer"  # noqa: E501
    ],
    build_requires=[
        "numpy<1.21",
    ],
    setup_requires=[
        "numpy<1.21",
    ],
    install_requires=[
        "Django>=3.2.0,<3.3",
        "django-q2>=1.8.0",
        "PyVirtualDisplay>=2.0,<3.0",
        "beautifulsoup4>=4.9.0,<5.0",
        "concurrent-log-handler>=0.9.0,<1.0",
        "coverage>=5.4,<6.0",
        "django-auth-adfs>=1.6.0,<2.0",
        "django-braces>=1.17,<1.18",
        "django-contrib-comments>=2.2,<2.3",
        "django-coverage>=1.2.0,<2.0",
        "django-crispy-forms>=1.14.0,<2.0",
        "django-debug-toolbar>=3.2,<4.0",
        "django-dynamic-raw-id>=2.8,<3.0",
        "django-extensions>=3.0.0,<4.0",
        "django-filter>=21.0,<22.0",
        "django-formtools>=2.5,<2.6",
        "django-listable>=0.5.0,<1.0",
        "django-mptt>=0.13.4,<1.0",
        "django-mptt-admin>=0.7.0,<1.0",
        "django-picklefield>=2.0,<3.0",
        "django-recurrence>=1.11,<1.12",
        "django-registration>=3.1.0,<4.0",
        "djangorestframework>=3.14.0,<3.15",
        "djangorestframework-filters>=1.0.0,<2.0",
        "django-sql-explorer<2",
        "django-widget-tweaks>=1.4.0,<2.0",
        "freezegun>=0.3.0,<1.0",
        "html5lib>=1.1,<2.0",
        "markdown>=3.3.0,<4.0",
        "matplotlib>=3.3.0,<4.0",
        "numpy>=1.19.0,<2.0",
        "openpyxl>=3.0.0,<4.0",
        "pandas<=1.1.5",
        "pep8>=1.7.0,<2.0",
        "Pillow>=8.1.0,<9.0",
        "pydicom>=2.1.0,<3.0",
        "pylinac<3.20",
        "pynliner>=0.8.0,<1.0",
        "pytest-cov>=2.11.0,<3.0",
        "pytest-django>=4.1.0,<5.0",
        "pytest-sugar>=0.9.0,<1.0",
        "pytest>=6.2.0,<7.0",
        "python-dateutil>=2.8.0,<3.0",
        "reportlab>=3.5.0,<4.0",
        "requests<=3",
        "scipy<=1.5.4",
        "selenium>=3.141.0,<4.0",
        "urllib3>=1.25.11,<2.0",
        "xlrd>=2.0.0,<3.0",
        "XlsxWriter>=1.3.0,<2.0",
    ],
    license='MIT',
    test_suite='tests',
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Framework :: Django 1.11",
        "Intended Audience :: Developers",
        "Intended Audience :: Healthcare Industry",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",
        "Natural Language :: English",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python",
        "Programming Language :: JavaScript",
        "Topic :: Scientific/Engineering :: Medical Science Apps.",
        "Topic :: Scientific/Engineering :: Physics",
        "Topic :: Software Development :: Version Control :: Git",
    ]
)
