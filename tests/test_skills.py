"""Tests for the Agent Skills loader."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.skills import load_skill, list_skills, load_supporting_file


def test_list_skills():
    skills = list_skills()
    names = [s["name"] for s in skills]
    assert "default-crawl" in names
    assert "ecommerce-crawl" in names
    for s in skills:
        assert "name" in s
        assert "description" in s
        assert "argument_hint" in s
    print(f"✓ list_skills returned: {names}")


def test_load_default_skill():
    skill = load_skill("default-crawl", arguments="https://example.com")
    assert skill.name == "default-crawl"
    assert "requests" in skill.content
    assert "beautifulsoup4" in skill.content
    assert "https://example.com" in skill.content  # $ARGUMENTS replaced
    assert "$ARGUMENTS" not in skill.content
    assert skill.description != ""
    print(f"✓ default-crawl loaded: {skill.name}")


def test_load_ecommerce_skill():
    skill = load_skill("ecommerce-crawl", arguments="https://shop.example.com 5")
    assert skill.name == "ecommerce-crawl"
    assert "products" in skill.content.lower()
    assert "https://shop.example.com 5" in skill.content  # $ARGUMENTS
    assert "5" in skill.content  # $1 replaced with max_pages
    print(f"✓ ecommerce-crawl loaded: {skill.name}")


def test_fallback_to_default():
    skill = load_skill("nonexistent-skill")
    default = load_skill("default-crawl")
    assert skill.name == default.name
    print("✓ Unknown skill falls back to default-crawl")


def test_supporting_files():
    skill = load_skill("ecommerce-crawl")
    assert len(skill.supporting_files) > 0
    assert "reference.md" in skill.supporting_files
    assert "examples/sample-output.json" in skill.supporting_files
    print(f"✓ Supporting files: {skill.supporting_files}")


def test_load_supporting_file():
    content = load_supporting_file("ecommerce-crawl", "reference.md")
    assert "pagination" in content.lower()
    print("✓ load_supporting_file works")


def test_frontmatter_parsing():
    skill = load_skill("default-crawl")
    assert skill.argument_hint == "<url>"
    skill2 = load_skill("ecommerce-crawl")
    assert skill2.argument_hint == "<url> [max_pages]"
    print("✓ Frontmatter parsed correctly")


def test_positional_arguments():
    skill = load_skill("ecommerce-crawl", arguments="https://shop.example.com 5")
    # $1 should be replaced with "5" (the max_pages argument)
    assert "5" in skill.content
    print("✓ Positional $N arguments substituted")
