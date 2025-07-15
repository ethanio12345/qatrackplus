#!/usr/bin/env python3
"""
Translation Script for QATrack+
Translates .po files to a target language.
"""

import os
import re
import sys
import time
from pathlib import Path

# Google Translate API setup
try:
    from googletrans import Translator
    GOOGLE_TRANSLATE_AVAILABLE = True
except ImportError:
    GOOGLE_TRANSLATE_AVAILABLE = False


def find_po_files(language_code=None):
    """Find all .po files, filtered by language code"""
    po_files = []
    locale_dir = Path('qatrack/locale')
    
    if language_code:
        po_file = locale_dir / language_code / 'LC_MESSAGES' / 'django.po'
        if po_file.exists():
            po_files.append(po_file)
    else:
        # Find all .po files
        for lang_dir in locale_dir.iterdir():
            if lang_dir.is_dir():
                po_file = lang_dir / 'LC_MESSAGES' / 'django.po'
                if po_file.exists():
                    po_files.append(po_file)
    
    return po_files


def remove_duplicates_from_po(po_file_path):
    """Remove duplicate msgid entries from a .po file"""
    
    with open(po_file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Split content into sections
    sections = content.split('\n\n')
    header = sections[0]
    translation_entries = sections[1:]

    # Track seen msgids to remove duplicates
    seen_msgids = set()
    unique_entries = []

    for entry in translation_entries:
        if not entry.strip():
            continue

        # Extract msgid
        msgid_match = re.search(r'msgid\s+"([^"]*)"', entry)
        if msgid_match:
            msgid = msgid_match.group(1)
            if msgid not in seen_msgids:
                seen_msgids.add(msgid)
                unique_entries.append(entry)
        else:
            # Keep entries without msgid (like comments)
            unique_entries.append(entry)

    # Reconstruct the file
    fixed_content = header + '\n\n' + '\n\n'.join(unique_entries)

    with open(po_file_path, 'w', encoding='utf-8') as f:
        f.write(fixed_content)

    print(f"🧹 Removed duplicates from {po_file_path}")


def fix_translation_variables(po_file_path):
    """Preserve Python format variables in translations"""
    


def translate_po_file(po_file_path, target_language='fr', source_language='en'):
    """Translate all msgid strings in a .po file using Google Translate API"""
    
    if not GOOGLE_TRANSLATE_AVAILABLE:
        print("❌ Google Translate library not available. Install with: pip install googletrans==4.0.0rc1")
        return False

    translator = Translator()

    # Read the PO file
    with open(po_file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Split into sections
    sections = content.split('\n\n')
    header = sections[0]
    translation_entries = sections[1:]

    print(f"🌐 Translating strings to {target_language}...")

    translated_entries = []
    total_entries = len(translation_entries)
    failed_translations = []

    for i, entry in enumerate(translation_entries):
        if not entry.strip():
            translated_entries.append(entry)
            continue

        # Extract msgid
        msgid_match = re.search(r'msgid\s+"([^"]*)"', entry)
        if msgid_match:
            msgid = msgid_match.group(1)
            if msgid:  # Skip empty msgid (header)
                translated = False
                max_retries = 3

                for attempt in range(max_retries):
                    try:
                        # Add delay between requests to avoid rate limiting
                        if attempt > 0:
                            time.sleep(2)  # Wait 2 seconds before retry
                        else:
                            time.sleep(0.5)  # Small delay between requests

                        # Translate the string
                        translation = translator.translate(msgid, src=source_language, dest=target_language)

                        # Check if translation was successful
                        if translation is None:
                            raise Exception("Translation returned None")

                        translated_text = translation.text

                        # Check if translated text is valid
                        if not translated_text or translated_text.strip() == "":
                            raise Exception("Translation result is empty")

                        # Replace the msgstr
                        entry = re.sub(r'msgstr\s+""', f'msgstr "{translated_text}"', entry)
                        translated = True
                        break

                    except Exception as e:
                        if attempt < max_retries - 1:
                            print(f"⚠️  Retry {attempt + 1}/{max_retries} for '{msgid[:50]}...': {str(e)[:100]}")
                        else:
                            print(f"❌ Failed to translate '{msgid[:50]}...' after {max_retries} attempts: {str(e)[:100]}")
                            failed_translations.append(msgid)

                if not translated:
                    # Keep original English if translation failed
                    entry = re.sub(r'msgstr\s+""', f'msgstr "{msgid}"', entry)

                # Progress indicator
                if (i + 1) % 25 == 0:
                    print(f"   Progress: {i + 1}/{total_entries}")

        translated_entries.append(entry)

    # Reconstruct the file
    translated_content = header + '\n\n' + '\n\n'.join(translated_entries)

    with open(po_file_path, 'w', encoding='utf-8') as f:
        f.write(translated_content)

    print(f"✅ Translation completed for {po_file_path}")
    if failed_translations:
        print(f"⚠️  {len(failed_translations)} translations failed and kept original English text")
        print("   Failed strings saved to: scripts/failed_translations.txt")

        # Save failed translations for manual review
        with open('scripts/failed_translations.txt', 'w', encoding='utf-8') as f:
            for failed in failed_translations:
                f.write(f"{failed}\n")

    return True


def translate_po_file_batch(po_file_path, target_language='fr', source_language='en', batch_size=50):
    """Translate PO file in smaller batches to avoid timeouts"""
    
    if not GOOGLE_TRANSLATE_AVAILABLE:
        print("❌ Google Translate library not available. Install with: pip install googletrans==4.0.0rc1")
        return False

    translator = Translator()

    # Read the PO file
    with open(po_file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Split into sections
    sections = content.split('\n\n')
    header = sections[0]
    translation_entries = sections[1:]

    print(f"🌐 Translating strings to {target_language} in batches of {batch_size}...")

    translated_entries = []
    total_entries = len(translation_entries)
    failed_translations = []

    # Process in batches
    for batch_start in range(0, total_entries, batch_size):
        batch_end = min(batch_start + batch_size, total_entries)
        batch_entries = translation_entries[batch_start:batch_end]

        print(f"   Processing batch {batch_start//batch_size + 1}/{(total_entries + batch_size - 1)//batch_size}")

        for entry in batch_entries:
            if not entry.strip():
                translated_entries.append(entry)
                continue

            # Extract msgid
            msgid_match = re.search(r'msgid\s+"([^"]*)"', entry)
            if msgid_match:
                msgid = msgid_match.group(1)
                if msgid:  # Skip empty msgid (header)
                    translated = False
                    max_retries = 3

                    for attempt in range(max_retries):
                        try:
                            # Add delay between requests
                            if attempt > 0:
                                time.sleep(3)  # Longer delay for retries
                            else:
                                time.sleep(1)  # Delay between requests

                            # Translate the string
                            translation = translator.translate(msgid, src=source_language, dest=target_language)

                            # Check if translation was successful
                            if translation is None:
                                raise Exception("Translation returned None")

                            translated_text = translation.text

                            # Check if translated text is valid
                            if not translated_text or translated_text.strip() == "":
                                raise Exception("Translation result is empty")

                            # Replace the msgstr
                            entry = re.sub(r'msgstr\s+""', f'msgstr "{translated_text}"', entry)
                            translated = True
                            break

                        except Exception as e:
                            if attempt < max_retries - 1:
                                print(f"     ⚠️  Retry {attempt + 1}/{max_retries} for '{msgid[:30]}...': {str(e)[:100]}")
                            else:
                                print(f"     ❌ Failed: '{msgid[:30]}...': {str(e)[:100]}")
                                failed_translations.append(msgid)

                    if not translated:
                        # Keep original English if translation failed
                        entry = re.sub(r'msgstr\s+""', f'msgstr "{msgid}"', entry)

            translated_entries.append(entry)

        # Save progress after each batch
        temp_content = header + '\n\n' + '\n\n'.join(translated_entries)
        with open(po_file_path, 'w', encoding='utf-8') as f:
            f.write(temp_content)

        print(f"     ✅ Batch completed. Progress saved.")

    print(f"✅ Translation completed for {po_file_path}")
    if failed_translations:
        print(f"⚠️  {len(failed_translations)} translations failed and kept original English text")
        print("   Failed strings saved to: scripts/failed_translations.txt")

        # Save failed translations for manual review
        with open('scripts/failed_translations.txt', 'w', encoding='utf-8') as f:
            for failed in failed_translations:
                f.write(f"{failed}\n")

    return True


def compile_messages():
    """Compile the PO file to MO format using Django's compilemessages command"""
    try:
        import subprocess
        result = subprocess.run(['python', 'manage.py', 'compilemessages'], capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ Messages compiled successfully")
            return True
        else:
            print(f"❌ Error compiling messages: {result.stderr}")
            return False
    except Exception as e:
        print(f"❌ Error compiling messages: {e}")
        return False


def list_available_languages():
    """List all available language codes with existing .po files"""
    po_files = find_po_files()
    if not po_files:
        print("❌ No .po files found in qatrack/locale/")
        return
    
    print("📋 Available languages with .po files:")
    for po_file in po_files:
        lang_code = po_file.parent.parent.name
        print(f"   {lang_code}: {po_file}")


def main():
    """Main function to run the translation process"""
    
    if len(sys.argv) < 2:
        print("""
🌐 Translation Manager for QATrack+

This script translates existing .po files using Google Translate API.
Use Django's makemessages command to generate .po files first.

Usage:
  python scripts/translation.py <command> [language_code]

Commands:
  list                    - List available languages with .po files
  translate <lang>        - Translate existing .po file for specified language
  batch <lang>           - Translate existing .po file in batches (recommended)
  clean <lang>           - Clean and fix variables in existing .po file
  compile                - Compile all .po files to .mo format
  all <lang>             - Complete process: clean, translate, compile

Examples:
  # First, generate .po files using Django
  python manage.py makemessages -l fr
  python manage.py makemessages -l es
  
  # Then translate them
  python scripts/translation.py list
  python scripts/translation.py batch fr
  python scripts/translation.py all es
  python scripts/translation.py compile

Supported language codes: fr, es, de, it, pt, zh, ja, ko, ru, etc.
(Any language code supported by Google Translate)
        """)
        return

    command = sys.argv[1]

    if command == 'list':
        list_available_languages()
        return
    
    if command == 'compile':
        print("🔄 Compiling messages...")
        compile_messages()
        return

    # Commands that require a language code
    if len(sys.argv) < 3:
        print("❌ Language code required for this command")
        print("Usage: python scripts/translation.py <command> <language_code>")
        return
    
    language_code = sys.argv[2]
    po_file = Path(f'qatrack/locale/{language_code}/LC_MESSAGES/django.po')
    
    if not po_file.exists():
        print(f"❌ PO file not found: {po_file}")
        print(f"Generate it first with: python manage.py makemessages -l {language_code}")
        return

    if command == 'translate':
        print(f"🔄 Starting translation for language: {language_code}")
        translate_po_file(po_file, language_code)
        
    elif command == 'batch':
        print(f"🔄 Starting batch translation for language: {language_code}")
        translate_po_file_batch(po_file, language_code)
        
    elif command == 'clean':
        print(f"🔄 Cleaning .po file for language: {language_code}")
        remove_duplicates_from_po(po_file)
        fix_translation_variables(po_file)
        print(f"✅ Cleaning completed for {language_code}")
        
    elif command == 'all':
        print(f"🔄 Starting complete translation process for language: {language_code}")
        remove_duplicates_from_po(po_file)
        fix_translation_variables(po_file)
        translate_po_file_batch(po_file, language_code)
        compile_messages()
        print(f"✅ Complete translation process finished for {language_code}!")
        
    else:
        print(f"❌ Unknown command: {command}")
        print("Valid commands: list, translate, batch, clean, compile, all")


if __name__ == "__main__":
    main()
