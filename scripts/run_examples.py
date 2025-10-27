#!/usr/bin/env python3
"""
Queuack Examples CLI Runner

Auto-discovers and runs examples from the examples/ folder.

Usage:
    python run_examples.py                  # Interactive mode
    python run_examples.py list             # List all examples
    python run_examples.py run basic/simple_queue
    python run_examples.py run-category basic
    python run_examples.py demo             # Run curated demos
"""

import re
import subprocess
import os
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set

import click

# ============================================================================
# Constants
# ============================================================================

CATEGORY_ORDER = [
    "basic",
    "workers",
    "dag_workflows",
    "real_world",
    "advanced",
    "integration",
]

DIFFICULTY_COLORS = {
    "beginner": "green",
    "intermediate": "yellow",
    "advanced": "red",
}

SEPARATOR_SINGLE = "─" * 60
SEPARATOR_DOUBLE = "=" * 60

# ============================================================================
# Path Setup
# ============================================================================

# Add project root to Python path
script_dir = Path(__file__).parent
project_root = script_dir.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


# ============================================================================
# Display Helpers
# ============================================================================

def _display_width(s: str) -> int:
    """Return the terminal display width of a string, counting wide chars as 2."""
    w = 0
    for ch in s:
        if unicodedata.east_asian_width(ch) in ("F", "W"):
            w += 2
        else:
            w += 1
    return w


def _pad_display(s: str, target: int) -> str:
    """Pad string with spaces to reach a target display width."""
    cur = _display_width(s)
    if cur >= target:
        return s
    return s + (" " * (target - cur))


def _display_examples_table(
    examples_by_cat: Dict[str, List["Example"]],
    category_filter: Optional[str] = None,
    difficulty_filter: Optional[str] = None,
    silent: bool = False  # NEW: Don't print, just build mapping
) -> Dict[str, str]:
    """Display examples in consistent numbered table format.
    
    Args:
        examples_by_cat: Examples grouped by category
        category_filter: Optional category to filter by
        difficulty_filter: Optional difficulty to filter by
        silent: If True, only build mapping without printing
    
    Returns:
        Mapping dict for numeric key lookups (e.g., "1.1" -> "basic/simple_queue")
    """
    if not examples_by_cat:
        if not silent:
            click.echo("❌ No examples found")
        return {}
    
    mapping = {}
    indent = "  "
    row_indent = indent + "  "
    
    for order_num, cat in enumerate(CATEGORY_ORDER, 1):
        examples = examples_by_cat.get(cat, [])
        
        # Apply filters
        if category_filter and cat != category_filter:
            continue
        if not examples:
            continue
        
        # Category header
        if not silent:
            cat_title = cat.upper().replace('_', ' ')
            click.echo(f"\n{indent}📁 {order_num}. {cat_title}")
            click.echo(f"{indent}{SEPARATOR_DOUBLE}")
        
        example_counter = 1
        for ex in sorted(examples, key=lambda x: x.path.name):
            # Apply difficulty filter
            if difficulty_filter and ex.difficulty != difficulty_filter:
                continue
            
            key = f"{cat}/{ex.name}"
            numbered_key = f"{order_num}.{example_counter}"
            
            # Build mapping
            mapping[numbered_key] = key
            mapping[key] = key
            
            if not silent:
                # Format row
                diff_label = f"[{ex.difficulty}]"
                diff_colored = click.style(
                    diff_label,
                    fg=DIFFICULTY_COLORS.get(ex.difficulty, "white")
                )
                worker = "👷" if ex.requires_worker else " "
                worker_padded = _pad_display(worker, 2)
                
                # Print row with consistent spacing
                click.echo(
                    f"{row_indent}{numbered_key:<6} "
                    f"{worker_padded} "
                    f"{diff_colored:<23}  "  # Allow space for ANSI codes
                    f"{ex.description}"
                )
            
            example_counter += 1
    
    # Footer
    if not silent:
        click.echo(f"\n{indent}{SEPARATOR_DOUBLE}")
        click.echo(f"{indent}Legend: 👷 = Requires worker process")
    
    return mapping

# ============================================================================
# Data Models
# ============================================================================

@dataclass
class Example:
    """Represents a runnable example."""
    
    path: Path
    category: str
    name: str
    description: str
    difficulty: str
    requires_worker: bool = False
    cleanup_db: bool = True


class ExampleRegistry:
    """Auto-discovers examples from filesystem."""
    
    def __init__(self, examples_dir: Path):
        self.examples_dir = examples_dir
        self.examples: Dict[str, Example] = {}
        self._discover_examples()
    
    def _discover_examples(self):
        """Auto-discover all Python files in examples/ subfolders."""
        if not self.examples_dir.exists():
            click.echo(
                f"⚠️  Examples directory not found: {self.examples_dir}",
                err=True
            )
            return

        # Find all category folders (01_basic, 02_workers, etc.)
        for category_dir in sorted(self.examples_dir.glob("*_*")):
            if not category_dir.is_dir():
                continue

            # Extract category name (e.g., "01_basic" -> "basic")
            if match := re.match(r"\d+_(.+)", category_dir.name):
                category = match.group(1)

                # Find all Python files in this category (including subdirectories)
                # Use ** for recursive globbing to handle nested folders like 04_real_world/01_etl/
                for py_file in sorted(category_dir.rglob("*.py")):
                    if not py_file.name.startswith("_"):
                        self._register_file(py_file, category)
    
    def _register_file(self, py_file: Path, category: str):
        """Register a single example file."""
        # Extract name from filename (e.g., "01_simple_queue.py" -> "simple_queue")
        filename = py_file.stem
        name = (
            match.group(1)
            if (match := re.match(r"\d+_(.+)", filename))
            else filename
        )
        
        # Parse docstring for metadata
        metadata = self._parse_docstring(py_file)
        
        # Create lookup key
        key = f"{category}/{name}"
        
        self.examples[key] = Example(
            path=py_file,
            category=category,
            name=name,
            description=metadata.get("description", "No description"),
            difficulty=metadata.get("difficulty", "intermediate"),
            requires_worker=metadata.get("requires_worker", False),
            cleanup_db=metadata.get("cleanup_db", True),
        )
    
    def _parse_docstring(self, py_file: Path) -> Dict[str, any]:
        """Parse metadata from file docstring.
        
        Looks for special markers:
            # Description: <text>
            # Difficulty: beginner|intermediate|advanced
            # Requires: worker
        """
        # Default description from filename (strip numeric prefix)
        default_name = re.sub(r"^\d+[_\-\.\s]*", "", py_file.stem)
        
        metadata = {
            "description": default_name.replace("_", " ").title(),
            "difficulty": "intermediate",
            "requires_worker": False,
            "cleanup_db": True,
        }
        
        try:
            content = py_file.read_text()
            lines = content.split("\n")[:20]  # Check first 20 lines
            
            for line in lines:
                line = line.strip()
                
                # Description marker
                if line.startswith("# Description:") or (
                    line.startswith('"""') and "Description:" in line
                ):
                    desc = line.split(":", 1)[1].strip(' "')
                    desc = re.sub(r"^\d+[_\-\.\s]*", "", desc).strip()
                    metadata["description"] = desc
                
                # Difficulty marker
                elif "# Difficulty:" in line or "Difficulty:" in line:
                    for level in ["beginner", "intermediate", "advanced"]:
                        if level in line.lower():
                            metadata["difficulty"] = level
                            break
                
                # Worker requirement
                elif "# Requires:" in line and "worker" in line.lower():
                    metadata["requires_worker"] = True
                
                # DAG examples typically need workers
                elif "dag." in line.lower() or "with queue.dag" in line.lower():
                    metadata["requires_worker"] = True
            
            # Heuristic: detect worker patterns if not explicitly marked
            if not metadata["requires_worker"]:
                has_worker_creation = re.search(r"\bWorker\s*\(", content)
                has_worker_run = re.search(r"worker\.run\s*\(", content)
                has_claim_loop = self._detect_claim_loop(content)
                
                if has_worker_creation and has_worker_run:
                    # Self-contained worker
                    metadata["requires_worker"] = False
                elif has_worker_creation and not has_worker_run and not has_claim_loop:
                    # Expects external worker
                    metadata["requires_worker"] = True
                elif has_claim_loop:
                    # Self-contained claim loop
                    metadata["requires_worker"] = False
        
        except Exception:
            pass  # Use defaults
        
        return metadata
    
    def _detect_claim_loop(self, content: str) -> bool:
        """Detect if content has manual claim loops."""
        # Check for while/for loops with queue.claim
        if re.search(
            r"while.*\n\s*.*queue\.claim|for.*\n\s*.*queue\.claim",
            content,
            re.MULTILINE
        ):
            return True
        
        # More flexible: check lines near loop keywords
        lines = content.split("\n")
        for i, line in enumerate(lines):
            if re.search(r"^\s*(while|for)\b", line):
                # Look ahead up to 5 lines
                for j in range(i + 1, min(i + 6, len(lines))):
                    if "queue.claim" in lines[j]:
                        return True
        
        return False
    
    def get(self, key: str) -> Optional[Example]:
        """Get example by key."""
        return self.examples.get(key)
    
    def list_by_category(self) -> Dict[str, List[Example]]:
        """Group examples by category."""
        result = {}
        for ex in self.examples.values():
            result.setdefault(ex.category, []).append(ex)
        return result
    
    def search(self, term: str) -> List[tuple[str, Example]]:
        """Search examples by keyword."""
        term = term.lower()
        return [
            (key, ex)
            for key, ex in self.examples.items()
            if term in key.lower()
            or term in ex.description.lower()
            or term in ex.category.lower()
        ]
    
    def get_categories(self) -> Set[str]:
        """Get all unique categories."""
        return set(ex.category for ex in self.examples.values())


# ============================================================================
# Helper Functions
# ============================================================================

def get_examples_dir() -> Path:
    """Find examples directory relative to this script."""
    script_dir = Path(__file__).resolve().parent  # Add .resolve() for absolute path
    
    # The script is in scripts/, examples/ is a sibling directory
    project_root = script_dir.parent  # Go up to project root
    examples_dir = project_root / "examples"
    
    if examples_dir.exists() and examples_dir.is_dir():
        return examples_dir
    
    # Fallback: check if we're already in examples/ or project root
    candidates = [
        script_dir / "examples",  # Current dir has examples/
        script_dir,                # Current dir IS examples/
    ]
    
    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            # Verify it actually contains example files
            if list(candidate.glob("*_*/*.py")):
                return candidate
    
    # Last resort: return expected path even if it doesn't exist
    # (will show helpful error message)
    return project_root / "examples"


def _run_simple(example: Example, no_cleanup: bool):
    """Run any example - library handles workers internally.
    
    Shows live stdout/stderr and tracks execution time.
    """
    import time
    
    # Set PYTHONPATH to include the project root
    env = os.environ.copy()
    project_root = Path(__file__).resolve().parent.parent
    env["PYTHONPATH"] = str(project_root)
    
    start_time = time.perf_counter()
    
    # Run without capture_output to show live output
    result = subprocess.run(
        [sys.executable, str(example.path)],
        cwd=example.path.parent,
        env=env,
        # Remove capture_output to show live output
        text=True
    )
    
    duration = time.perf_counter() - start_time
    
    # Show duration
    click.echo(f"\n⏱️  Duration: {duration:.2f}s")
    
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode,
            [sys.executable, str(example.path)]
        )


def _cleanup_databases(directory: Path):
    """Remove database files created during examples."""
    for pattern in ["*.db", "*.duckdb"]:
        for db_file in directory.glob(pattern):
            try:
                db_file.unlink()
            except Exception:
                pass


# ============================================================================
# CLI Commands
# ============================================================================

@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """🦆 Queuack Examples - Interactive Learning Tool
    
    Explore Queuack features through practical examples.
    """
    ctx.ensure_object(dict)
    examples_dir = get_examples_dir()
    ctx.obj["registry"] = ExampleRegistry(examples_dir)
    ctx.obj["examples_dir"] = examples_dir
    
    # If no subcommand, launch interactive mode
    if ctx.invoked_subcommand is None:
        ctx.invoke(interactive)


@cli.command()
@click.option("--category", "-c", help="Filter by category")
@click.option("--difficulty", "-d", help="Filter by difficulty")
@click.pass_context
def list(ctx, category, difficulty):
    """List all available examples."""
    registry = ctx.obj["registry"]
    examples_by_cat = registry.list_by_category()
    
    if not examples_by_cat:
        click.echo(f"❌ No examples found in {ctx.obj['examples_dir']}")
        click.echo("Make sure you have .py files in numbered folders like 01_basic/")
        return
    
    # Display table
    _display_examples_table(examples_by_cat, category, difficulty)
    
    # Usage hints
    click.echo(f"\n  Run an example:")
    click.echo(f"    python run_examples.py run <key>")
    click.echo(f"    python run_examples.py run <number>")
    click.echo(f"\n  Examples:")
    click.echo(f"    python run_examples.py run 1.1")
    click.echo(f"    python run_examples.py run basic/simple_queue\n")


@cli.command()
@click.argument("example_key")
@click.option("--no-cleanup", is_flag=True, help="Keep database file after run")
@click.pass_context
def run(ctx, example_key, no_cleanup):
    """Run a specific example.
    
    EXAMPLE_KEY can be either a numbered key (1.1) or full key (basic/simple_queue)
    """
    registry = ctx.obj["registry"]
    
    # Resolve numbered key if provided (silent mapping build)
    if re.match(r'^\d+\.\d+$', example_key):
        examples_by_cat = registry.list_by_category()
        mapping = _display_examples_table(examples_by_cat, silent=True)
        example_key = mapping.get(example_key, example_key)
    
    example = registry.get(example_key)
    
    if not example:
        click.echo(f"❌ Example '{example_key}' not found", err=True)
        click.echo("Run 'python run_examples.py list' to see available examples")
        return 1
    
    # Display example info
    click.echo(f"\n{SEPARATOR_DOUBLE}")
    click.echo(f"🦆 Running: {example.name}")
    click.echo(f"📝 {example.description}")
    click.echo(f"📊 Difficulty: {example.difficulty}")
    click.echo(f"📁 File: {example.path.relative_to(ctx.obj['examples_dir'])}")
    if example.requires_worker:
        click.echo(f"👷 Worker: Managed by library")
    click.echo(f"{SEPARATOR_DOUBLE}\n")
    
    if not example.path.exists():
        click.echo(f"❌ File not found: {example.path}", err=True)
        return 1
    
    # Run the example
    try:
        _run_simple(example, no_cleanup)
        click.echo("\n✅ Example completed successfully!")
    except KeyboardInterrupt:
        click.echo("\n⚠️  Interrupted by user")
        return 130
    except subprocess.CalledProcessError as e:
        click.echo(f"\n❌ Example failed with exit code {e.returncode}", err=True)
        return 1
    except Exception as e:
        click.echo(f"\n❌ Error running example: {e}", err=True)
        import traceback
        traceback.print_exc()
        return 1
    finally:
        if example.cleanup_db and not no_cleanup:
            _cleanup_databases(example.path.parent)


@cli.command()
@click.argument("category")
@click.option("--delay", default=2, help="Delay between examples (seconds)")
@click.option("--no-cleanup", is_flag=True, help="Keep database files")
@click.option("--continue-on-error", is_flag=True, help="Continue if one fails")
@click.pass_context
def run_category(ctx, category, delay, no_cleanup, continue_on_error):
    """Run all examples in a category."""
    import time
    
    registry = ctx.obj["registry"]
    examples_by_cat = registry.list_by_category()
    
    if category not in examples_by_cat:
        click.echo(f"❌ Category '{category}' not found", err=True)
        categories = ', '.join(sorted(examples_by_cat.keys()))
        click.echo(f"Available: {categories}")
        return 1
    
    examples = examples_by_cat[category]
    if not examples:
        click.echo(f"❌ No examples in '{category}'", err=True)
        return 1
    
    # Header
    click.echo(f"\n{SEPARATOR_DOUBLE}")
    click.echo(f"🦆 Running category: {category.upper()}")
    click.echo(f"📊 {len(examples)} examples")
    click.echo(f"{SEPARATOR_DOUBLE}\n")
    
    successful = 0
    failed = 0
    total_start = time.perf_counter()
    
    for i, example in enumerate(sorted(examples, key=lambda x: x.path.name), 1):
        click.echo(f"\n{SEPARATOR_SINGLE}")
        click.echo(f"Example {i}/{len(examples)}: {example.name}")
        click.echo(f"{SEPARATOR_SINGLE}")
        click.echo(f"📝 {example.description}")
        click.echo(f"📊 Difficulty: {example.difficulty}")
        click.echo(f"📁 {example.path.relative_to(ctx.obj['examples_dir'])}")
        
        if not click.confirm("\nRun this example?", default=True):
            click.echo("⏭️  Skipped.")
            continue
        
        try:
            click.echo(f"\n🚀 Running {example.name}...")
            _run_simple(example, no_cleanup)
            click.echo(f"✅ {example.name} completed!")
            successful += 1
        except KeyboardInterrupt:
            click.echo(f"\n⚠️  Interrupted during {example.name}")
            if not continue_on_error:
                return 130
            failed += 1
        except Exception as e:
            click.echo(f"\n❌ {example.name} failed: {e}", err=True)
            if not continue_on_error:
                return 1
            failed += 1
        finally:
            if example.cleanup_db and not no_cleanup:
                _cleanup_databases(example.path.parent)
        
        # Delay between examples
        if i < len(examples) and delay > 0:
            click.echo(f"\n⏳ Waiting {delay}s before next example...")
            time.sleep(delay)
    
    total_duration = time.perf_counter() - total_start
    
    # Summary
    click.echo(f"\n{SEPARATOR_DOUBLE}")
    click.echo(f"📊 Category '{category}' complete!")
    click.echo(f"✅ Successful: {successful}")
    if failed > 0:
        click.echo(f"❌ Failed: {failed}")
    click.echo(f"⏱️  Total time: {total_duration:.2f}s")
    click.echo(f"{SEPARATOR_DOUBLE}")


@cli.command()
@click.pass_context
def categories(ctx):
    """Show all categories with descriptions."""
    registry = ctx.obj["registry"]
    examples_by_cat = registry.list_by_category()
    
    click.echo("\n📚 Queuack Example Categories\n")
    
    # Sort categories by desired order
    def sort_key(cat):
        try:
            return CATEGORY_ORDER.index(cat)
        except ValueError:
            return len(CATEGORY_ORDER)
    
    for idx, cat in enumerate(sorted(examples_by_cat.keys(), key=sort_key), 1):
        examples = examples_by_cat.get(cat, [])
        title = cat.replace("_", " ").title()
        
        click.echo(f"{idx}. {click.style(title, bold=True)}")
        click.echo(f"   {len(examples)} examples")
        
        # Show first example as preview
        if examples:
            first = sorted(examples, key=lambda x: x.path.name)[0]
            click.echo(f"   Example: {first.name} - {first.description}")
        click.echo()
    
    click.echo("Run 'python run_examples.py list' to see all examples")


@cli.command()
@click.argument("search_term")
@click.pass_context
def search(ctx, search_term):
    """Search examples by keyword."""
    registry = ctx.obj["registry"]
    matches = registry.search(search_term)
    
    if not matches:
        click.echo(f"❌ No examples found matching '{search_term}'")
        return
    
    click.echo(f"\n  Found {len(matches)} examples matching '{search_term}':\n")
    
    for key, ex in matches:
        diff = click.style(
            f"[{ex.difficulty}]",
            fg=DIFFICULTY_COLORS.get(ex.difficulty, "white")
        )
        click.echo(f"    {diff} {key:<35} {ex.description}")
    
    click.echo("\n  Run: python run_examples.py run <key>")


@cli.command()
@click.argument("example_key")
@click.pass_context
def info(ctx, example_key):
    """Show detailed information about an example."""
    registry = ctx.obj["registry"]
    example = registry.get(example_key)
    
    if not example:
        click.echo(f"❌ Example '{example_key}' not found", err=True)
        return 1
    
    click.echo(f"\n{SEPARATOR_DOUBLE}")
    click.echo(f"📋 Example: {example.name}")
    click.echo(f"{SEPARATOR_DOUBLE}\n")
    
    click.echo(f"Category:     {example.category}")
    click.echo(f"Difficulty:   {example.difficulty}")
    click.echo(f"Description:  {example.description}")
    click.echo(f"File:         {example.path}")
    click.echo(f"Worker:       {'Yes' if example.requires_worker else 'No'}")
    
    # Show code preview
    if example.path.exists():
        click.echo(f"\n{SEPARATOR_SINGLE}")
        click.echo("Code Preview:")
        click.echo(f"{SEPARATOR_SINGLE}\n")
        
        with open(example.path) as f:
            lines = f.readlines()[:30]
            for i, line in enumerate(lines, 1):
                click.echo(f"{i:3d} | {line.rstrip()}")
            
            if len(lines) >= 30:
                click.echo("\n... (truncated)")
    
    click.echo(f"\n{SEPARATOR_DOUBLE}")
    click.echo(f"Run: python run_examples.py run {example_key}")


@cli.command()
@click.pass_context
def debug(ctx):
    """Debug: Show registry information."""
    registry = ctx.obj["registry"]
    examples_dir = ctx.obj["examples_dir"]
    
    click.echo(f"\nExamples directory: {examples_dir}")
    click.echo(f"Directory exists: {examples_dir.exists()}")
    
    if examples_dir.exists():
        click.echo(f"\nContents:")
        for item in sorted(examples_dir.iterdir()):
            click.echo(f"  {item.name} {'[DIR]' if item.is_dir() else ''}")
    
    click.echo(f"\nRegistry has {len(registry.examples)} examples")
    
    if registry.examples:
        click.echo("\nRegistered examples:")
        for key, ex in sorted(registry.examples.items()):
            click.echo(f"  {key}")
    else:
        click.echo("\n❌ No examples registered!")
    
    click.echo(f"\nCategories: {registry.get_categories()}")

@cli.command()
@click.pass_context
def interactive(ctx):
    """Interactive mode - browse and run examples."""
    registry = ctx.obj["registry"]
    
    while True:
        click.clear()
        click.echo(f"\n{SEPARATOR_DOUBLE}")
        click.echo("🦆 Queuack Examples - Interactive Mode")
        click.echo(f"{SEPARATOR_DOUBLE}")
        
        click.echo("\n1. List all examples")
        click.echo("2. Search examples")
        click.echo("3. Browse by category")
        click.echo("4. Run category")
        click.echo("5. Demo tour")
        click.echo("6. Exit")
        
        choice = click.prompt("\nSelect option", type=int, default=1)
        
        if choice == 1:
            click.clear()
            examples_by_cat = registry.list_by_category()
            mapping = _display_examples_table(examples_by_cat)  # Show with output
            
            click.echo(f"\n  Enter example key or number (or press Enter to return)\n")
            key = click.prompt("Run example", default="", show_default=False)
            
            if key.strip():
                actual_key = mapping.get(key.strip(), key.strip())
                try:
                    ctx.invoke(run, example_key=actual_key, no_cleanup=False)
                except Exception:
                    pass
                input("\nPress Enter to continue...")
        
        elif choice == 2:
            term = click.prompt("Search term")
            matches = registry.search(term)
            
            click.clear()
            if not matches:
                click.echo(f"\n❌ No examples found matching '{term}'")
                input("\nPress Enter to continue...")
                continue
            
            click.echo(f"\n  Found {len(matches)} examples:\n")
            
            mapping = {}
            for i, (key, ex) in enumerate(matches, 1):
                mapping[str(i)] = key
                mapping[key] = key
                
                diff = click.style(
                    f"[{ex.difficulty}]",
                    fg=DIFFICULTY_COLORS.get(ex.difficulty, "white")
                )
                worker = _pad_display("👷" if ex.requires_worker else " ", 2)
                click.echo(f"    {i:<3} {worker} {diff:<23} {key:<35} {ex.description}")
            
            click.echo(f"\n  Enter number or key (or press Enter to return)\n")
            key = click.prompt("Run example", default="", show_default=False)
            
            if key.strip():
                actual_key = mapping.get(key.strip(), key.strip())
                try:
                    ctx.invoke(run, example_key=actual_key, no_cleanup=False)
                except Exception:
                    pass
                input("\nPress Enter to continue...")
        
        elif choice == 3:
            # Browse by category (similar logic, use _display_examples_table)
            click.clear()
            ctx.invoke(categories)
            
            sel = click.prompt(
                "\nSelect category (number or name, or Enter to return)",
                default="",
                show_default=False
            )
            if not sel.strip():
                continue
            
            # Category browsing logic...
            # (Keep existing logic with _display_examples_table)
        
        elif choice == 4:
            click.clear()
            ctx.invoke(categories)
            cat = click.prompt(
                "\nSelect category (or Enter to return)",
                default="",
                show_default=False
            )
            if cat.strip() and cat.strip() in registry.list_by_category():
                ctx.invoke(
                    run_category,
                    category=cat.strip(),
                    delay=2,
                    no_cleanup=False,
                    continue_on_error=True
                )
            elif cat.strip():
                click.echo(f"❌ Category '{cat}' not found")
                input("\nPress Enter to continue...")
        
        elif choice == 5:
            ctx.invoke(demo)
        
        elif choice == 6:
            click.echo("\n👋 Goodbye!")
            break


@cli.command()
@click.option("--delay", default=3, help="Delay between demos (seconds)")
@click.pass_context
def demo(ctx, delay):
    """Run a curated demo tour - first example from each category."""
    registry = ctx.obj["registry"]
    
    # Auto-select first example from each category
    def sort_key(cat):
        try:
            return CATEGORY_ORDER.index(cat)
        except ValueError:
            return len(CATEGORY_ORDER)
    
    demos = []
    for cat in sorted(registry.get_categories(), key=sort_key):
        examples = registry.list_by_category().get(cat, [])
        if examples:
            first = sorted(examples, key=lambda x: x.path.name)[0]
            demos.append(f"{cat}/{first.name}")
    
    if not demos:
        click.echo("❌ No examples found for demo tour")
        return
    
    click.echo("🎬 Starting Queuack Demo Tour")
    click.echo(f"Running {len(demos)} examples with {delay}s between each")
    click.echo("Skip individual demos or cancel the entire tour\n")
    
    for i, demo_key in enumerate(demos, 1):
        example = registry.get(demo_key)
        if not example:
            continue
        
        click.echo(f"\n{SEPARATOR_DOUBLE}")
        click.echo(f"Demo {i}/{len(demos)}: {example.name}")
        click.echo(f"Category: {example.category.replace('_', ' ').title()}")
        click.echo(f"Difficulty: {example.difficulty}")
        click.echo(f"{SEPARATOR_DOUBLE}")
        
        choice = click.prompt("Run this demo? (y/n/cancel)", default="y")
        
        if choice.lower() in ["y", "yes", ""]:
            ctx.invoke(run, example_key=demo_key, no_cleanup=False)
            input("\nPress Enter to continue...")
        elif choice.lower() == "cancel":
            click.echo("🛑 Demo tour cancelled!")
            return
        else:
            click.echo("Skipped.")
        
        if i < len(demos) and delay > 0:
            click.echo(f"\n⏳ Waiting {delay}s...")
            import time
            time.sleep(delay)
    
    click.echo("\n🎉 Demo tour complete!")


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    cli(obj={})