#!/usr/bin/env python3
"""
Queuack Examples CLI Runner

Auto-discovers and runs examples from the examples/ folder.

Usage:
    python run_examples.py                  # Interactive mode
    python run_examples.py list             # List all examples
    python run_examples.py run basic/simple_queue
    python run_examples.py run-category basic  # Run all examples in basic category
    python run_examples.py demo             # Run curated demos
"""

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set

import click


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
                f"⚠️  Examples directory not found: {self.examples_dir}", err=True
            )
            return

        # Find all category folders (01_basic, 02_workers, etc.)
        for category_dir in sorted(self.examples_dir.glob("*_*")):
            if not category_dir.is_dir():
                continue

            # Extract category name (e.g., "01_basic" -> "basic")
            dir_name = category_dir.name
            match = re.match(r"\d+_(.+)", dir_name)
            if not match:
                continue

            category = match.group(1)

            # Find all Python files in this category
            for py_file in sorted(category_dir.glob("*.py")):
                if py_file.name.startswith("_"):
                    continue  # Skip private files

                self._register_file(py_file, category)

    def _register_file(self, py_file: Path, category: str):
        """Register a single example file."""

        # Extract name from filename (e.g., "01_simple_queue.py" -> "simple_queue")
        filename = py_file.stem
        match = re.match(r"\d+_(.+)", filename)
        name = match.group(1) if match else filename

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
        metadata = {
            "description": py_file.stem.replace("_", " ").title(),
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
                if (
                    line.startswith("# Description:")
                    or line.startswith('"""')
                    and "Description:" in line
                ):
                    desc = line.split(":", 1)[1].strip(' "')
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

        except Exception:
            pass  # Use defaults

        return metadata

    def get(self, key: str) -> Optional[Example]:
        """Get example by key."""
        return self.examples.get(key)

    def list_by_category(self) -> Dict[str, List[Example]]:
        """Group examples by category."""
        result = {}
        for ex in self.examples.values():
            if ex.category not in result:
                result[ex.category] = []
            result[ex.category].append(ex)
        return result

    def search(self, term: str) -> List[tuple[str, Example]]:
        """Search examples by keyword."""
        term = term.lower()
        matches = []

        for key, ex in self.examples.items():
            if (
                term in key.lower()
                or term in ex.description.lower()
                or term in ex.category.lower()
            ):
                matches.append((key, ex))

        return matches

    def get_categories(self) -> Set[str]:
        """Get all unique categories."""
        return set(ex.category for ex in self.examples.values())


# ============================================================================
# CLI Commands
# ============================================================================


def get_examples_dir() -> Path:
    """Find examples directory relative to this script."""
    script_dir = Path(__file__).parent

    # Check if we're in project root (examples/ subfolder exists)
    examples_dir = script_dir / "examples"
    if examples_dir.exists():
        return examples_dir

    # Check if we're in examples/ folder already
    if script_dir.name == "examples":
        return script_dir

    # Check parent directory
    parent_examples = script_dir.parent / "examples"
    if parent_examples.exists():
        return parent_examples

    # Default to ./examples
    return script_dir / "examples"


@click.group()
@click.pass_context
def cli(ctx):
    """🦆 Queuack Examples - Interactive Learning Tool

    Explore Queuack features through practical examples.
    """
    ctx.ensure_object(dict)
    examples_dir = get_examples_dir()
    ctx.obj["registry"] = ExampleRegistry(examples_dir)
    ctx.obj["examples_dir"] = examples_dir


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

    # Difficulty colors
    diff_colors = {"beginner": "green", "intermediate": "yellow", "advanced": "red"}

    # Desired category order for listing
    desired_order = [
        "basic",
        "workers",
        "dag_workflows",
        "real_world",
        "advanced",
        "integration",
    ]

    def sort_key(cat):
        try:
            return desired_order.index(cat)
        except ValueError:
            return len(desired_order)  # Unknown categories at the end

    for cat, examples in sorted(examples_by_cat.items(), key=lambda x: sort_key(x[0])):
        # Filter by category
        if category and cat != category:
            continue

        click.echo(f"\n📁 {cat.upper().replace('_', ' ')}")
        click.echo("=" * 60)

        for ex in sorted(examples, key=lambda x: x.path.name):
            # Filter by difficulty
            if difficulty and ex.difficulty != difficulty:
                continue

            # Format display
            key = f"{cat}/{ex.name}"
            diff = click.style(
                f"[{ex.difficulty}]", fg=diff_colors.get(ex.difficulty, "white")
            )
            worker = "👷" if ex.requires_worker else "  "

            click.echo(f"  {worker} {diff} {key:<35} {ex.description}")

    click.echo("\n" + "=" * 60)
    click.echo("Legend: 👷 = Requires worker process")
    click.echo("\nRun an example: python run_examples.py run <key>")


@cli.command()
@click.argument("example_key")
@click.option("--no-cleanup", is_flag=True, help="Keep database file after run")
@click.option(
    "--worker-delay", default=2, help="Seconds to wait before starting worker"
)
@click.pass_context
def run(ctx, example_key, no_cleanup, worker_delay):
    """Run a specific example.

    Example: python run_examples.py run basic/simple_queue
    """

    registry = ctx.obj["registry"]
    example = registry.get(example_key)

    if not example:
        click.echo(f"❌ Example '{example_key}' not found", err=True)
        click.echo("Run 'python run_examples.py list' to see available examples")
        return 1

    click.echo(f"\n{'=' * 60}")
    click.echo(f"🦆 Running: {example.name}")
    click.echo(f"📝 {example.description}")
    click.echo(f"📊 Difficulty: {example.difficulty}")
    click.echo(f"📁 File: {example.path.relative_to(ctx.obj['examples_dir'])}")
    click.echo(f"{'=' * 60}\n")

    if not example.path.exists():
        click.echo(f"❌ File not found: {example.path}", err=True)
        return 1

    # Run the example
    try:
        if example.requires_worker:
            _run_with_worker(example, worker_delay, no_cleanup)
        else:
            _run_simple(example, no_cleanup)

        click.echo("\n✅ Example completed successfully!")

    except KeyboardInterrupt:
        click.echo("\n⚠️  Interrupted by user")
        return 130
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
@click.option("--no-cleanup", is_flag=True, help="Keep database files after run")
@click.option(
    "--worker-delay", default=2, help="Seconds to wait before starting worker"
)
@click.option(
    "--continue-on-error",
    is_flag=True,
    help="Continue running other examples if one fails",
)
@click.pass_context
def run_category(ctx, category, delay, no_cleanup, worker_delay, continue_on_error):
    """Run all examples in a category.

    Example: python run_examples.py run-category basic
    """

    registry = ctx.obj["registry"]
    examples_by_cat = registry.list_by_category()

    if category not in examples_by_cat:
        click.echo(f"❌ Category '{category}' not found", err=True)
        click.echo(f"Available categories: {', '.join(sorted(examples_by_cat.keys()))}")
        return 1

    examples = examples_by_cat[category]
    if not examples:
        click.echo(f"❌ No examples found in category '{category}'", err=True)
        return 1

    click.echo(f"\n{'=' * 60}")
    click.echo(f"🦆 Running all examples in category: {category.upper()}")
    click.echo(f"📊 {len(examples)} examples to run")
    click.echo(f"{'=' * 60}\n")

    successful = 0
    failed = 0

    for i, example in enumerate(sorted(examples, key=lambda x: x.path.name), 1):
        click.echo(f"\n{'─' * 60}")
        click.echo(f"Example {i}/{len(examples)}: {example.name}")
        click.echo(f"{'─' * 60}")

        click.echo(f"📝 {example.description}")
        click.echo(f"📊 Difficulty: {example.difficulty}")
        click.echo(f"📁 File: {example.path.relative_to(ctx.obj['examples_dir'])}")

        if not click.confirm("\nRun this example?", default=True):
            click.echo("⏭️  Skipped.")
            continue

        try:
            click.echo(f"\n🚀 Running {example.name}...")

            if example.requires_worker:
                _run_with_worker(example, worker_delay, no_cleanup)
            else:
                _run_simple(example, no_cleanup)

            click.echo(f"✅ {example.name} completed successfully!")
            successful += 1

        except KeyboardInterrupt:
            click.echo(f"\n⚠️  Interrupted during {example.name}")
            if not continue_on_error:
                click.echo("Stopping execution.")
                return 130
            failed += 1

        except Exception as e:
            click.echo(f"\n❌ {example.name} failed: {e}", err=True)
            if not continue_on_error:
                click.echo("Stopping execution due to error.")
                return 1
            failed += 1

        finally:
            if example.cleanup_db and not no_cleanup:
                _cleanup_databases(example.path.parent)

        # Delay between examples (except for the last one)
        if i < len(examples) and delay > 0:
            click.echo(f"\n⏳ Waiting {delay} seconds before next example...")
            import time

            time.sleep(delay)

    click.echo(f"\n{'=' * 60}")
    click.echo(f"📊 Category '{category}' run complete!")
    click.echo(f"✅ Successful: {successful}")
    if failed > 0:
        click.echo(f"❌ Failed: {failed}")
    click.echo(f"{'=' * 60}")


@cli.command()
@click.option("--delay", default=3, help="Delay between demos (seconds)")
@click.pass_context
def demo(ctx, delay):
    """Run a curated sequence of demos."""

    registry = ctx.obj["registry"]

    # Auto-select demos: first example from each category
    demos = []
    
    # Desired category order for listing
    desired_order = [
        "basic",
        "workers",
        "dag_workflows",
        "real_world",
        "advanced",
        "integration",
    ]

    def sort_key(cat):
        try:
            return desired_order.index(cat)
        except ValueError:
            return len(desired_order)  # Unknown categories at the end

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
    click.echo("You can skip individual demos or cancel the entire tour\n")

    for i, demo_key in enumerate(demos, 1):
        example = registry.get(demo_key)
        if not example:
            continue

        click.echo(f"\n{'=' * 60}")
        click.echo(f"Demo {i}/{len(demos)}: {example.name}")
        click.echo(f"Category: {example.category.replace('_', ' ').title()}")
        click.echo(f"Difficulty: {example.difficulty}")
        click.echo(f"{'=' * 60}")

        while True:
            choice = click.prompt("Run this demo? (y/n/cancel)").lower().strip()
            if choice in ['y', 'yes']:
                ctx.invoke(run, example_key=demo_key, no_cleanup=False, worker_delay=2)
                input("\nPress Enter to continue to next demo...")
                break
            elif choice in ['n', 'no']:
                click.echo("Skipped.")
                break
            elif choice == 'cancel':
                click.echo("🛑 Demo tour cancelled!")
                return
            else:
                click.echo("Please enter 'y', 'n', or 'cancel'")

        if i < len(demos):
            click.echo(f"\n⏳ Waiting {delay} seconds before next demo...")
            import time
            time.sleep(delay)

    click.echo("\n🎉 Demo tour complete!")


@cli.command()
@click.pass_context
def categories(ctx):
    """Show all categories with descriptions."""

    registry = ctx.obj["registry"]
    examples_by_cat = registry.list_by_category()

    click.echo("\n📚 Queuack Example Categories\n")

    # Desired category order for listing
    desired_order = [
        "basic",
        "workers",
        "dag_workflows",
        "real_world",
        "advanced",
        "integration",
    ]

    def sort_key(cat):
        try:
            return desired_order.index(cat)
        except ValueError:
            return len(desired_order)  # Unknown categories at the end

    for cat in sorted(examples_by_cat.keys(), key=sort_key):
        examples = examples_by_cat.get(cat, [])

        # Format category name nicely
        title = cat.replace("_", " ").title()

        click.echo(f"{click.style(title, bold=True)}")
        click.echo(f"  {len(examples)} examples")

        # Show first example as preview
        if examples:
            first = sorted(examples, key=lambda x: x.path.name)[0]
            click.echo(f"  Example: {first.name} - {first.description}")

        click.echo()

    click.echo("Run 'python run_examples.py list' to see all examples")


@cli.command()
@click.argument("search_term")
@click.pass_context
def search(ctx, search_term):
    """Search examples by keyword.

    Example: python run_examples.py search "pipeline"
    """

    registry = ctx.obj["registry"]
    matches = registry.search(search_term)

    if not matches:
        click.echo(f"No examples found matching '{search_term}'")
        return

    click.echo(f"\nFound {len(matches)} examples matching '{search_term}':\n")

    diff_colors = {"beginner": "green", "intermediate": "yellow", "advanced": "red"}

    for key, ex in matches:
        diff = click.style(
            f"[{ex.difficulty}]", fg=diff_colors.get(ex.difficulty, "white")
        )
        click.echo(f"  {diff} {key:<35} {ex.description}")

    click.echo("\nRun: python run_examples.py run <key>")


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

    click.echo(f"\n{'=' * 60}")
    click.echo(f"📋 Example: {example.name}")
    click.echo(f"{'=' * 60}\n")

    click.echo(f"Category:     {example.category}")
    click.echo(f"Difficulty:   {example.difficulty}")
    click.echo(f"Description:  {example.description}")
    click.echo(f"File:         {example.path}")
    click.echo(f"Worker:       {'Yes' if example.requires_worker else 'No'}")

    # Show file preview
    if example.path.exists():
        click.echo(f"\n{'─' * 60}")
        click.echo("Code Preview:")
        click.echo(f"{'─' * 60}\n")

        with open(example.path) as f:
            lines = f.readlines()[:30]  # First 30 lines
            for i, line in enumerate(lines, 1):
                click.echo(f"{i:3d} | {line.rstrip()}")

            if len(lines) >= 30:
                click.echo("\n... (truncated)")

    click.echo(f"\n{'=' * 60}")
    click.echo(f"Run: python run_examples.py run {example_key}")


@cli.command()
@click.pass_context
def interactive(ctx):
    """Interactive mode - browse and run examples."""

    registry = ctx.obj["registry"]

    while True:
        os.system('clear')
        click.echo("\n" + "=" * 60)
        click.echo("🦆 Queuack Examples - Interactive Mode")
        click.echo("=" * 60)

        click.echo("\n1. List all examples")
        click.echo("2. Search examples")
        click.echo("3. Browse by category")
        click.echo("4. Run all examples in a category")
        click.echo("5. Run demo tour")
        click.echo("6. Exit")

        choice = click.prompt("\nSelect option", type=int, default=1)

        if choice == 1:
            os.system('clear')
            mapping = _display_numbered_examples(registry)

            while True:
                choice = click.prompt("\nRun an example? (y/n/back)").lower().strip()
                if choice in ['y', 'yes']:
                    key = click.prompt("Enter example key or number (e.g., 1.1 or basic/simple_queue)")
                    actual_key = mapping.get(key, key)  # Use mapping if it's a number, otherwise use as-is
                    ctx.invoke(run, example_key=actual_key)
                    input("\nPress Enter to continue...")
                    break
                elif choice in ['n', 'no']:
                    break
                elif choice == 'back':
                    break
                else:
                    click.echo("Please enter 'y', 'n', or 'back'")

        elif choice == 2:
            term = click.prompt("Search term")
            registry = ctx.obj["registry"]
            matches = registry.search(term)
            os.system('clear')
            mapping = _display_numbered_search_results(matches)

            if matches:
                while True:
                    choice = click.prompt("\nRun an example? (y/n/back)").lower().strip()
                    if choice in ['y', 'yes']:
                        key = click.prompt("Enter example key or number")
                        actual_key = mapping.get(key, key)  # Use mapping if it's a number, otherwise use as-is
                        ctx.invoke(run, example_key=actual_key)
                        input("\nPress Enter to continue...")
                        break
                    elif choice in ['n', 'no']:
                        break
                    elif choice == 'back':
                        break
                    else:
                        click.echo("Please enter 'y', 'n', or 'back'")
            else:
                input("\nPress Enter to continue...")

        elif choice == 3:
            os.system('clear')
            ctx.invoke(categories)

            cat = click.prompt("Select category (or 'back' to return)")
            if cat.lower().strip() == 'back':
                continue
                
            registry = ctx.obj["registry"]
            examples_by_cat = registry.list_by_category()
            
            if cat in examples_by_cat:
                os.system('clear')
                # Display category examples with numbers
                click.echo(f"\n📁 {cat.upper().replace('_', ' ')}")
                click.echo("=" * 60)
                
                mapping = {}
                # Find the category number
                desired_order = [
                    "basic", "workers", "dag_workflows", "real_world", "advanced", "integration"
                ]
                try:
                    cat_num = desired_order.index(cat) + 1
                except ValueError:
                    cat_num = len(desired_order) + 1
                
                for i, ex in enumerate(sorted(examples_by_cat[cat], key=lambda x: x.path.name), 1):
                    key = f"{cat}/{ex.name}"
                    numbered_key = f"{cat_num}.{i}"
                    mapping[numbered_key] = key
                    mapping[str(i)] = key  # Also allow just the number
                    mapping[key] = key
                    
                    diff_colors = {"beginner": "green", "intermediate": "yellow", "advanced": "red"}
                    diff = click.style(
                        f"[{ex.difficulty}]", fg=diff_colors.get(ex.difficulty, "white")
                    )
                    worker = "👷" if ex.requires_worker else "  "
                    click.echo(f"  {numbered_key:<6} {worker} {diff} {ex.description}")
                
                click.echo("\n" + "=" * 60)
                click.echo("Legend: 👷 = Requires worker process")

                while True:
                    choice = click.prompt("\nRun a specific example? (y/n/back)").lower().strip()
                    if choice in ['y', 'yes']:
                        key = click.prompt("Enter example number or key (e.g., 3.1 or linear_pipeline)")
                        actual_key = mapping.get(key, key)
                        ctx.invoke(run, example_key=actual_key)
                        input("\nPress Enter to continue...")
                        break
                    elif choice in ['n', 'no']:
                        break
                    elif choice == 'back':
                        break
                    else:
                        click.echo("Please enter 'y', 'n', or 'back'")
            else:
                click.echo(f"❌ Category '{cat}' not found")

        elif choice == 4:
            # Run all examples in a category
            os.system('clear')
            ctx.invoke(categories)
            cat = click.prompt("Select category (or 'back' to return)")
            if cat.lower().strip() == 'back':
                continue
            if cat in registry.list_by_category():
                ctx.invoke(
                    run_category,
                    category=cat,
                    delay=2,
                    no_cleanup=False,
                    worker_delay=2,
                    continue_on_error=True,
                )
            else:
                click.echo(f"❌ Category '{cat}' not found")

        elif choice == 5:
            ctx.invoke(demo)

        elif choice == 6:
            click.echo("\n👋 Goodbye!")
            break


# ============================================================================
# Helper Functions
# ============================================================================


def _display_numbered_examples(registry):
    """Display examples with numbered prefixes and return mapping."""
    examples_by_cat = registry.list_by_category()

    if not examples_by_cat:
        click.echo(f"❌ No examples found")
        return {}

    # Difficulty colors
    diff_colors = {"beginner": "green", "intermediate": "yellow", "advanced": "red"}

    # Desired category order for listing
    desired_order = [
        "basic",
        "workers",
        "dag_workflows",
        "real_world",
        "advanced",
        "integration",
    ]

    def sort_key(cat):
        try:
            return desired_order.index(cat)
        except ValueError:
            return len(desired_order)  # Unknown categories at the end

    mapping = {}
    category_counter = 1

    for cat, examples in sorted(examples_by_cat.items(), key=lambda x: sort_key(x[0])):
        click.echo(f"\n📁 {cat.upper().replace('_', ' ')}")
        click.echo("=" * 60)

        example_counter = 1
        for ex in sorted(examples, key=lambda x: x.path.name):
            # Format display
            key = f"{cat}/{ex.name}"
            numbered_key = f"{category_counter}.{example_counter}"
            mapping[numbered_key] = key
            mapping[key] = key  # Also allow the original key

            diff = click.style(
                f"[{ex.difficulty}]", fg=diff_colors.get(ex.difficulty, "white")
            )
            worker = "👷" if ex.requires_worker else "  "

            click.echo(f"  {numbered_key:<6} {worker} {diff} {ex.description}")

            example_counter += 1

        category_counter += 1

    click.echo("\n" + "=" * 60)
    click.echo("Legend: 👷 = Requires worker process")
    click.echo("\nRun an example: python run_examples.py run <key> or <number>")

    return mapping


def _display_numbered_search_results(matches):
    """Display search results with numbered prefixes and return mapping."""
    if not matches:
        return {}

    click.echo(f"\nFound {len(matches)} examples:\n")

    diff_colors = {"beginner": "green", "intermediate": "yellow", "advanced": "red"}
    mapping = {}

    for i, (key, ex) in enumerate(matches, 1):
        numbered_key = str(i)
        mapping[numbered_key] = key
        mapping[key] = key  # Also allow the original key

        diff = click.style(
            f"[{ex.difficulty}]", fg=diff_colors.get(ex.difficulty, "white")
        )
        worker = "👷" if ex.requires_worker else "  "
        click.echo(f"  {numbered_key:<3} {worker} {diff} {key:<35} {ex.description}")

    click.echo("\nRun: python run_examples.py run <key> or <number>")
    return mapping


def _run_simple(example: Example, no_cleanup: bool):
    """Run a simple example (no worker needed)."""

    # Set PYTHONPATH to include the project root so examples can import queuack
    env = os.environ.copy()
    project_root = example.path.parent.parent.parent  # examples/ -> queuack/
    env["PYTHONPATH"] = str(project_root)

    result = subprocess.run(
        [sys.executable, str(example.path)], cwd=example.path.parent, env=env
    )

    if result.returncode != 0:
        raise Exception(f"Example exited with code {result.returncode}")


def _run_with_worker(example: Example, worker_delay: int, no_cleanup: bool):
    """Run example with a worker process."""

    import time

    click.echo(f"Starting example (worker will start in {worker_delay}s)...\n")

    # Set PYTHONPATH to include the project root so examples can import queuack
    env = os.environ.copy()
    project_root = example.path.parent.parent.parent  # examples/ -> queuack/
    env["PYTHONPATH"] = str(project_root)

    # Start example in background
    example_proc = subprocess.Popen(
        [sys.executable, str(example.path)], cwd=example.path.parent, env=env
    )

    # Wait a bit for jobs to be enqueued
    time.sleep(worker_delay)

    # Start worker
    click.echo(f"\n{'─' * 60}")
    click.echo("Starting worker process...")
    click.echo(f"{'─' * 60}\n")

    # Create a simple worker script
    worker_script = """
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from queuack import DuckQueue, Worker

# Find the database file
db_files = list(Path('.').glob('*.db'))
if db_files:
    queue = DuckQueue(str(db_files[0]))
    worker = Worker(queue, concurrency=2)
    print(f"Worker processing {db_files[0]}...")
    
    # Run for limited time
    import time
    start = time.time()
    while time.time() - start < 30:  # 30 second timeout
        stats = queue.stats()
        pending = stats.get('pending', 0) + stats.get('claimed', 0)
        if pending == 0:
            print("✓ All jobs completed!")
            break
        
        job = queue.claim()
        if job:
            try:
                result = job.execute()
                queue.ack(job.id, result=result)
            except Exception as e:
                queue.ack(job.id, error=str(e))
        else:
            time.sleep(0.5)
else:
    print("No database file found")
"""

    worker_file = example.path.parent / "_worker_temp.py"
    worker_file.write_text(worker_script)

    try:
        worker_proc = subprocess.Popen(
            [sys.executable, str(worker_file)], cwd=example.path.parent
        )

        # Wait for completion
        example_proc.wait()
        worker_proc.wait(timeout=35)

    except subprocess.TimeoutExpired:
        click.echo("\n⚠️  Worker timeout - terminating...")
        worker_proc.terminate()
        worker_proc.wait(timeout=5)

    except KeyboardInterrupt:
        click.echo("\n⚠️  Interrupted - cleaning up...")
        example_proc.terminate()
        worker_proc.terminate()
        raise

    finally:
        # Cleanup worker script
        if worker_file.exists():
            worker_file.unlink()


def _cleanup_databases(directory: Path):
    """Remove database files created during examples."""
    for pattern in ["*.db", "*.duckdb"]:
        for db_file in directory.glob(pattern):
            try:
                db_file.unlink()
            except Exception:
                pass


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    cli(obj={})
