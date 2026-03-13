#!/usr/bin/env python3
"""
Prepare Obsidian blog posts for Hugo publishing.

This script:
1. Finds posts marked with #status/ready_to_publish and draft: false
2. Backs up original Obsidian version to obsidian_originals/
3. Cleans the Hugo version:
   - Converts wikilinks to plain text
   - Extracts and flattens nested tags to frontmatter
   - Removes inline tags from content
   - Cleans frontmatter
"""

import os
import re
import shutil
from pathlib import Path
import argparse
import yaml

# Configuration
DRY_RUN = True
POSTS_DIR = "04_Blog/blog/content/posts"
BACKUP_DIR = "04_Blog/obsidian_originals"

# Frontmatter fields to keep
KEEP_FIELDS = {
    'title', 'date', 'draft', 'description', 'lastmod',
    'featureimage', 'featureimagecaption', 'heroStyle'
}

# Tag prefixes to extract for Hugo
TAG_PREFIXES = ['topic', 'where']

def extract_frontmatter(content):
    """
    Extract YAML frontmatter from markdown content.
    
    Returns: (frontmatter_dict, content_without_frontmatter)
    """
    # Match frontmatter between --- delimiters
    match = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)$', content, re.DOTALL)
    
    if not match:
        return {}, content
    
    try:
        frontmatter = yaml.safe_load(match.group(1))
        content_body = match.group(2)
        return frontmatter or {}, content_body
    except yaml.YAMLError as e:
        print(f"  Warning: Could not parse frontmatter: {e}")
        return {}, content

def extract_inline_tags(content):
    """
    Extract inline tags from content.
    
    Returns: (list of tags, content with tag lines removed)
    """
    tags = set()
    lines = content.split('\n')
    cleaned_lines = []
    
    for line in lines:
        # Check if line is primarily tags (starts with # and contains multiple tags)
        tag_pattern = r'#[\w/]+'
        found_tags = re.findall(tag_pattern, line)
        
        # If line is mostly tags, extract them and skip the line
        if found_tags and len(''.join(found_tags)) > len(line) * 0.5:
            for tag in found_tags:
                # Only extract tags with topic/ or where/ prefix
                for prefix in TAG_PREFIXES:
                    if tag.startswith(f'#{prefix}/'):
                        # Extract all parts after prefix
                        parts = tag[len(prefix)+2:].split('/')
                        # Add each part as a tag
                        for part in parts:
                            if part:
                                tags.add(part.replace('_', '-'))
            # Skip this line (don't add to cleaned content)
            continue
        
        cleaned_lines.append(line)
    
    return sorted(list(tags)), '\n'.join(cleaned_lines)

def check_malformed_wikilinks(content):
    """
    Check for malformed wikilinks (missing closing brackets).
    Returns list of malformed links found.
    """
    malformed = []
    
    # Find patterns like [[text] (missing closing bracket)
    # Look for [[ followed by text and then ] but not ]]
    pattern = r'\[\[([^\]]+)\](?!\])'
    matches = re.finditer(pattern, content)
    
    for match in matches:
        malformed.append(f"[[{match.group(1)}]")
    
    return malformed

def convert_wikilinks(content):
    """
    Convert wikilinks to plain text.
    
    [[Link]] -> Link
    [[Link|Display Text]] -> Display Text
    [[../path/to/Link]] -> Link
    """
    # Handle [[Link|Display Text]]
    content = re.sub(r'\[\[([^\]|]+)\|([^\]]+)\]\]', r'\2', content)
    
    # Handle [[../path/to/Link]] - extract just the final part
    def replace_path_link(match):
        link = match.group(1)
        # Get the last part after final /
        parts = link.split('/')
        return parts[-1]
    
    content = re.sub(r'\[\[([^\]]+)\]\]', replace_path_link, content)
    
    return content

def clean_frontmatter(frontmatter, extracted_tags):
    """
    Clean frontmatter:
    - Keep only allowed fields
    - Add extracted tags
    - Fix featureimage quotes
    """
    cleaned = {}
    
    # Keep only allowed fields
    for key in KEEP_FIELDS:
        if key in frontmatter and frontmatter[key] is not None:
            cleaned[key] = frontmatter[key]
    
    # Fix featureimage quotes
    if 'featureimage' in cleaned:
        img = str(cleaned['featureimage'])
        # Remove surrounding quotes (both single and double)
        img = img.strip('\'"')
        cleaned['featureimage'] = img
    
    # Add tags if any were extracted
    if extracted_tags:
        cleaned['tags'] = extracted_tags
    
    # Ensure draft is boolean
    if 'draft' in cleaned:
        if isinstance(cleaned['draft'], str):
            cleaned['draft'] = cleaned['draft'].lower() in ('true', 'yes')
    
    return cleaned

def format_frontmatter(frontmatter):
    """Format frontmatter as YAML string."""
    return yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True, sort_keys=False)

def is_post_ready(filepath):
    """
    Check if a post is ready to publish.
    Must have #status/ready_to_publish tag and draft: false
    """
    try:
        content = filepath.read_text(encoding='utf-8')
        
        # Check for tag
        if '#status/ready_to_publish' not in content:
            return False
        
        # Check frontmatter for draft: false
        frontmatter, _ = extract_frontmatter(content)
        draft = frontmatter.get('draft', True)
        
        # Handle string or boolean
        if isinstance(draft, str):
            draft = draft.lower() in ('true', 'yes')
        
        return not draft
        
    except Exception as e:
        print(f"  Error reading {filepath}: {e}")
        return False

def find_ready_posts(posts_dir):
    """Find all posts ready to publish."""
    posts_dir = Path(posts_dir)
    ready_posts = []
    
    if not posts_dir.exists():
        print(f"Error: Posts directory not found: {posts_dir}")
        return []
    
    # Look for index.md files in subdirectories
    for post_folder in posts_dir.iterdir():
        if not post_folder.is_dir():
            continue
        
        index_file = post_folder / 'index.md'
        if index_file.exists() and is_post_ready(index_file):
            ready_posts.append(index_file)
    
    return ready_posts

def backup_post(post_path, posts_dir, backup_dir):
    """
    Backup original post to obsidian_originals directory.
    Maintains the same directory structure.
    """
    posts_dir = Path(posts_dir)
    backup_dir = Path(backup_dir)
    post_path = Path(post_path)
    
    # Get relative path from posts_dir
    try:
        rel_path = post_path.parent.relative_to(posts_dir)
    except ValueError:
        print(f"  Warning: Post not in posts directory: {post_path}")
        return False
    
    # Create backup path
    backup_post_dir = backup_dir / rel_path
    backup_post_path = backup_post_dir / 'index.md'
    
    # Create backup directory
    backup_post_dir.mkdir(parents=True, exist_ok=True)
    
    # Copy all files from post directory (including images)
    for item in post_path.parent.iterdir():
        backup_item = backup_post_dir / item.name
        if item.is_file():
            shutil.copy2(item, backup_item)
    
    return backup_post_path

def process_post(post_path, dry_run=True):
    """
    Process a single post:
    1. Read content
    2. Check for malformed wikilinks
    3. Extract frontmatter and inline tags
    4. Convert wikilinks
    5. Clean frontmatter
    6. Write back
    """
    try:
        # Read original content
        content = post_path.read_text(encoding='utf-8')
        original_content = content
        
        # Check for malformed wikilinks
        malformed = check_malformed_wikilinks(content)
        
        # Extract frontmatter
        frontmatter, body = extract_frontmatter(content)
        
        # Extract inline tags and clean body
        extracted_tags, body = extract_inline_tags(body)
        
        # Convert wikilinks
        body = convert_wikilinks(body)
        
        # Clean frontmatter
        cleaned_frontmatter = clean_frontmatter(frontmatter, extracted_tags)
        
        # Reconstruct content
        new_content = f"---\n{format_frontmatter(cleaned_frontmatter)}---\n{body}"
        
        # Show changes
        print(f"\n{'='*70}")
        print(f"Post: {post_path.parent.name}")
        print(f"{'='*70}")
        
        # Warn about malformed wikilinks
        if malformed:
            print(f"⚠ WARNING: Found {len(malformed)} malformed wikilink(s):")
            for link in malformed:
                print(f"  - {link} (missing closing ]])")
            print("  Please fix these in the original Obsidian file!")
        
        if extracted_tags:
            print(f"Extracted tags: {', '.join(extracted_tags)}")
        
        # Show frontmatter changes
        old_keys = set(frontmatter.keys())
        new_keys = set(cleaned_frontmatter.keys())
        removed = old_keys - new_keys
        added = new_keys - old_keys
        
        if removed:
            print(f"Removed frontmatter: {', '.join(removed)}")
        if added:
            print(f"Added frontmatter: {', '.join(added)}")
        
        # Count changes
        wikilink_count = len(re.findall(r'\[\[([^\]]+)\]\]', original_content))
        if wikilink_count > 0:
            print(f"Converted {wikilink_count} wikilink(s) to plain text")
        
        if not dry_run:
            # Write cleaned content
            post_path.write_text(new_content, encoding='utf-8')
            print("✓ Post cleaned successfully")
        else:
            print("[DRY RUN] Would write cleaned version")
        
        return True
        
    except Exception as e:
        print(f"✗ Error processing {post_path}: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(
        description='Prepare Obsidian blog posts for Hugo publishing',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
What this script does:
1. Finds posts with #status/ready_to_publish and draft: false
2. Backs up originals to obsidian_originals/ directory
3. Cleans Hugo versions:
   - Converts [[wikilinks]] to plain text
   - Extracts #topic/ and #where/ tags to frontmatter
   - Removes inline tag lines
   - Cleans frontmatter (removes author, published, etc.)
   - Fixes featureimage quote issues

Examples:
  # Preview what will be cleaned (dry run)
  python prepare_for_hugo.py

  # Actually clean the posts
  python prepare_for_hugo.py --live

  # Custom directories
  python prepare_for_hugo.py --posts-dir /path/to/posts --backup-dir /path/to/backup --live
        """
    )
    
    parser.add_argument(
        '--posts-dir',
        default=POSTS_DIR,
        help=f'Hugo posts directory (default: {POSTS_DIR})'
    )
    parser.add_argument(
        '--backup-dir',
        default=BACKUP_DIR,
        help=f'Backup directory for originals (default: {BACKUP_DIR})'
    )
    parser.add_argument(
        '--live',
        action='store_true',
        help='Actually modify files (default is dry run)'
    )
    
    args = parser.parse_args()
    
    posts_dir = Path(args.posts_dir).expanduser()
    backup_dir = Path(args.backup_dir).expanduser()
    dry_run = not args.live
    
    print("=" * 70)
    print("Hugo Post Preparation Script")
    print("=" * 70)
    print(f"Posts directory: {posts_dir}")
    print(f"Backup directory: {backup_dir}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print("=" * 70)
    print()
    
    # Find ready posts
    print("Scanning for posts ready to publish...")
    ready_posts = find_ready_posts(posts_dir)
    
    if not ready_posts:
        print("No posts found with #status/ready_to_publish and draft: false")
        return
    
    print(f"Found {len(ready_posts)} post(s) ready to publish")
    print()
    
    # Process each post
    success_count = 0
    
    for post_path in ready_posts:
        print(f"\nProcessing: {post_path.parent.name}/index.md")
        
        # Backup original
        if not dry_run:
            backup_path = backup_post(post_path, posts_dir, backup_dir)
            print(f"✓ Backed up to: {backup_path}")
        else:
            print(f"[DRY RUN] Would backup to obsidian_originals/")
        
        # Process post
        if process_post(post_path, dry_run):
            success_count += 1
    
    # Summary
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Posts processed: {success_count}/{len(ready_posts)}")
    
    if dry_run:
        print()
        print("⚠ This was a DRY RUN - no files were modified.")
        print("Run with --live to actually prepare posts for Hugo.")
    else:
        print()
        print("✓ Posts prepared for Hugo!")
        print(f"✓ Original versions backed up to: {backup_dir}")
    
    print("=" * 70)

if __name__ == "__main__":
    main()
