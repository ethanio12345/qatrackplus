#!/usr/bin/env python3
"""
Script to extract all translation tags from the QATrack+ codebase.
This helps identify all strings that need to be translated.
"""

import os
import re
import json
from pathlib import Path

def extract_template_translations(directory):
    """Extract {% trans %} tags from Django templates"""
    translations = []
    
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith('.html'):
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # Find all {% trans "..." %} patterns
                    pattern = r'{%\s*trans\s+"([^"]+)"\s*%}'
                    matches = re.findall(pattern, content)
                    
                    for match in matches:
                        translations.append({
                            'type': 'template',
                            'file': filepath,
                            'string': match,
                            'context': '{% trans %}'
                        })
                        
                except Exception as e:
                    print(f"Error reading {filepath}: {e}")
    
    return translations

def extract_python_translations(directory):
    """Extract _() and _l() function calls from Python files"""
    translations = []
    
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith('.py'):
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # Find all _("...") patterns
                    pattern1 = r'_\(\s*"([^"]+)"\s*\)'
                    matches1 = re.findall(pattern1, content)
                    
                    for match in matches1:
                        translations.append({
                            'type': 'python',
                            'file': filepath,
                            'string': match,
                            'context': '_()'
                        })
                    
                    # Find all _l("...") patterns
                    pattern2 = r'_l\(\s*"([^"]+)"\s*\)'
                    matches2 = re.findall(pattern2, content)
                    
                    for match in matches2:
                        translations.append({
                            'type': 'python',
                            'file': filepath,
                            'string': match,
                            'context': '_l()'
                        })
                        
                except Exception as e:
                    print(f"Error reading {filepath}: {e}")
    
    return translations

def extract_javascript_translations(directory):
    """Extract JavaScript translation object keys"""
    translations = []
    
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith('.js') or file.endswith('.html'):
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # Find JavaScript translation object patterns
                    pattern = r'translations\[["\']([^"\']+)["\']\]'
                    matches = re.findall(pattern, content)
                    
                    for match in matches:
                        translations.append({
                            'type': 'javascript',
                            'file': filepath,
                            'string': match,
                            'context': 'translations[key]'
                        })
                        
                except Exception as e:
                    print(f"Error reading {filepath}: {e}")
    
    return translations

def main():
    # Get the project root directory
    project_root = Path(__file__).parent.parent
    qatrack_dir = project_root / 'qatrack'
    
    print("Extracting translation tags from QATrack+ codebase...")
    
    # Extract all types of translations
    template_translations = extract_template_translations(qatrack_dir)
    python_translations = extract_python_translations(qatrack_dir)
    js_translations = extract_javascript_translations(qatrack_dir)
    
    # Combine all translations
    all_translations = template_translations + python_translations + js_translations
    
    # Remove duplicates based on string content
    unique_translations = []
    seen_strings = set()
    
    for trans in all_translations:
        if trans['string'] not in seen_strings:
            unique_translations.append(trans)
            seen_strings.add(trans['string'])
    
    # Sort by string for easier review
    unique_translations.sort(key=lambda x: x['string'].lower())
    
    # Generate output files
    output_dir = project_root / 'scripts' / 'translation_extraction'
    output_dir.mkdir(exist_ok=True)
    
    # Save as JSON for programmatic use
    with open(output_dir / 'all_translations.json', 'w', encoding='utf-8') as f:
        json.dump(unique_translations, f, indent=2, ensure_ascii=False)
    
    # Save as text file for easy reading
    with open(output_dir / 'translation_strings.txt', 'w', encoding='utf-8') as f:
        f.write("QATrack+ Translation Strings\n")
        f.write("=" * 50 + "\n\n")
        
        for trans in unique_translations:
            f.write(f"String: {trans['string']}\n")
            f.write(f"Type: {trans['type']} ({trans['context']})\n")
            f.write(f"File: {trans['file']}\n")
            f.write("-" * 30 + "\n\n")
    
    # Save just the strings for translation
    with open(output_dir / 'strings_to_translate.txt', 'w', encoding='utf-8') as f:
        for trans in unique_translations:
            f.write(f"{trans['string']}\n")
    
    # Generate statistics
    stats = {
        'total_unique_strings': len(unique_translations),
        'template_strings': len([t for t in unique_translations if t['type'] == 'template']),
        'python_strings': len([t for t in unique_translations if t['type'] == 'python']),
        'javascript_strings': len([t for t in unique_translations if t['type'] == 'javascript']),
    }
    
    print(f"\nTranslation extraction complete!")
    print(f"Total unique strings: {stats['total_unique_strings']}")
    print(f"Template strings: {stats['template_strings']}")
    print(f"Python strings: {stats['python_strings']}")
    print(f"JavaScript strings: {stats['javascript_strings']}")
    print(f"\nOutput files saved to: {output_dir}")
    print(f"- all_translations.json: Complete data with file locations")
    print(f"- translation_strings.txt: Human-readable format with context")
    print(f"- strings_to_translate.txt: Just the strings for translation")

if __name__ == '__main__':
    main() 