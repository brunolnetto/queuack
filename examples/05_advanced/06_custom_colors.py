#!/usr/bin/env python3
"""
Custom Mermaid Color Schemes for DAG Visualization

Demonstrates customizing DAG visualizations with different color themes
based on context (development, production, presentations, accessibility).

# Difficulty: advanced

Shows:
- Using pre-built color schemes
- Creating custom color schemes
- Status-based coloring
- Theme selection for different audiences
- Generating visualizations for documentation
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from queuack import (
    DAG,
    DuckQueue,
    MermaidColorScheme,
)


# ==============================================================================
# Sample DAG
# ==============================================================================

def create_sample_dag(queue):
    """Create a sample ETL pipeline DAG."""
    dag = DAG("etl_pipeline", queue=queue)

    def extract_api():
        """Extract data from API."""
        return {"records": 1000, "source": "api"}

    def extract_db():
        """Extract data from database."""
        return {"records": 5000, "source": "database"}

    def transform(context):
        """Transform combined data."""
        api_data = context.upstream("extract_api")
        db_data = context.upstream("extract_db")
        return {
            "total_records": api_data["records"] + db_data["records"],
            "transformed": True
        }

    def validate(context):
        """Validate transformed data."""
        data = context.upstream("transform")
        return {"valid": data["total_records"] > 0}

    def load(context):
        """Load data to warehouse."""
        valid = context.upstream("validate")
        if valid["valid"]:
            return {"status": "loaded", "records": 6000}
        return {"status": "skipped"}

    # Build the DAG
    dag.add_node(extract_api, name="extract_api")
    dag.add_node(extract_db, name="extract_db")
    dag.add_node(transform, name="transform", upstream=["extract_api", "extract_db"])
    dag.add_node(validate, name="validate", upstream=["transform"])
    dag.add_node(load, name="load", upstream=["validate"])

    return dag


# ==============================================================================
# Example 1: Pre-Built Themes
# ==============================================================================

def example_prebuilt_themes():
    """Demonstrate all pre-built color schemes."""
    print("\n" + "="*70)
    print("1️⃣  PRE-BUILT THEMES")
    print("="*70)

    queue = DuckQueue(db_path=":memory:")
    dag = create_sample_dag(queue)

    # Execute the DAG so we have status colors
    print("\nExecuting DAG...")
    dag.execute()

    themes = {
        "default": MermaidColorScheme.default(),
        "blue_professional": MermaidColorScheme.blue_professional(),
        "dark_mode": MermaidColorScheme.dark_mode(),
        "pastel": MermaidColorScheme.pastel(),
        "high_contrast": MermaidColorScheme.high_contrast(),
        "grayscale": MermaidColorScheme.grayscale(),
    }

    print("\n📊 Available Themes:\n")

    for name, scheme in themes.items():
        mermaid = dag.export_mermaid(color_scheme=scheme)

        # Save to file
        output_file = f"dag_{name}.mmd"
        with open(output_file, 'w') as f:
            f.write(mermaid)

        print(f"  ✓ {name:20s} → {output_file}")
        print(f"    Colors: done={scheme.done}, running={scheme.running}, failed={scheme.failed}")

    print("\n💡 Tip: Paste .mmd file contents into https://mermaid.live to visualize")

    queue.close()


# ==============================================================================
# Example 2: Custom Brand Colors
# ==============================================================================

def example_custom_brand():
    """Create a custom color scheme matching company branding."""
    print("\n" + "="*70)
    print("2️⃣  CUSTOM BRAND COLORS")
    print("="*70)

    # Company brand colors (example)
    company_colors = MermaidColorScheme(
        pending="#F5F5F5",      # Light gray - not started
        ready="#FDB714",        # Brand yellow - ready to go
        running="#1A73E8",      # Brand blue - in progress
        done="#34A853",         # Brand green - success
        failed="#EA4335",       # Brand red - error
        skipped="#9AA0A6",      # Gray - skipped
        stroke_color="#202124", # Dark gray border
        stroke_width=2
    )

    queue = DuckQueue(db_path=":memory:")
    dag = create_sample_dag(queue)
    dag.execute()

    mermaid = dag.export_mermaid(color_scheme=company_colors)

    print("\n🎨 Custom Brand Theme:")
    print(f"   Pending:  {company_colors.pending}")
    print(f"   Ready:    {company_colors.ready}")
    print(f"   Running:  {company_colors.running}")
    print(f"   Done:     {company_colors.done}")
    print(f"   Failed:   {company_colors.failed}")

    output_file = "dag_company_brand.mmd"
    with open(output_file, 'w') as f:
        f.write(mermaid)

    print(f"\n   Saved to: {output_file}")

    queue.close()


# ==============================================================================
# Example 3: Context-Specific Themes
# ==============================================================================

def example_context_specific():
    """Use different themes for different contexts."""
    print("\n" + "="*70)
    print("3️⃣  CONTEXT-SPECIFIC THEMES")
    print("="*70)

    queue = DuckQueue(db_path=":memory:")
    dag = create_sample_dag(queue)
    dag.execute()

    contexts = {
        "development": {
            "scheme": MermaidColorScheme.default(),
            "description": "Bright colors for easy debugging"
        },
        "production": {
            "scheme": MermaidColorScheme.blue_professional(),
            "description": "Professional look for dashboards"
        },
        "presentation": {
            "scheme": MermaidColorScheme.pastel(),
            "description": "Soft colors for slides/reports"
        },
        "accessibility": {
            "scheme": MermaidColorScheme.high_contrast(),
            "description": "High contrast for visibility"
        },
        "print": {
            "scheme": MermaidColorScheme.grayscale(),
            "description": "Black & white for printing"
        },
    }

    print("\n📁 Context-Specific Visualizations:\n")

    for context, info in contexts.items():
        mermaid = dag.export_mermaid(color_scheme=info["scheme"])
        output_file = f"dag_{context}.mmd"

        with open(output_file, 'w') as f:
            f.write(mermaid)

        print(f"  {context:15s} → {output_file:25s} ({info['description']})")

    queue.close()


# ==============================================================================
# Example 4: Dynamic Theme Selection
# ==============================================================================

def example_dynamic_selection():
    """Select theme dynamically based on environment or user preference."""
    print("\n" + "="*70)
    print("4️⃣  DYNAMIC THEME SELECTION")
    print("="*70)

    import os

    # Simulate different environments
    for env_mode in ["light", "dark", "print"]:
        print(f"\n🌍 Environment: {env_mode}")

        queue = DuckQueue(db_path=":memory:")
        dag = create_sample_dag(queue)
        dag.execute()

        # Select theme based on environment
        if env_mode == "dark":
            scheme = MermaidColorScheme.dark_mode()
            print("   Using: Dark Mode (easier on eyes)")
        elif env_mode == "print":
            scheme = MermaidColorScheme.grayscale()
            print("   Using: Grayscale (printer-friendly)")
        else:
            scheme = MermaidColorScheme.default()
            print("   Using: Default (bright colors)")

        mermaid = dag.export_mermaid(color_scheme=scheme)
        output_file = f"dag_env_{env_mode}.mmd"

        with open(output_file, 'w') as f:
            f.write(mermaid)

        print(f"   Saved: {output_file}")

        queue.close()


# ==============================================================================
# Example 5: Advanced Customization
# ==============================================================================

def example_advanced_customization():
    """Advanced color scheme with special styling."""
    print("\n" + "="*70)
    print("5️⃣  ADVANCED CUSTOMIZATION")
    print("="*70)

    # Create scheme with streaming task highlighting
    advanced_scheme = MermaidColorScheme(
        pending="#EEEEEE",
        ready="#FFB74D",         # Amber - ready
        running="#42A5F5",       # Blue - running
        done="#66BB6A",          # Green - success
        failed="#EF5350",        # Red - failed
        skipped="#BDBDBD",       # Gray - skipped
        streaming="#26C6DA",     # Cyan - streaming tasks (special)
        subdag="#7E57C2",        # Purple - sub-DAGs (special)
        stroke_color="#424242",
        stroke_width=2
    )

    print("\n🎨 Advanced Features:")
    print(f"   • Status colors: 6 states")
    print(f"   • Streaming tasks: {advanced_scheme.streaming} (dashed border)")
    print(f"   • Sub-DAG tasks: {advanced_scheme.subdag} (thick border)")
    print(f"   • Custom stroke: {advanced_scheme.stroke_color} @ {advanced_scheme.stroke_width}px")

    queue = DuckQueue(db_path=":memory:")
    dag = create_sample_dag(queue)
    dag.execute()

    mermaid = dag.export_mermaid(color_scheme=advanced_scheme)

    # Show style definitions
    print("\n📝 Generated CSS Classes:")
    for line in advanced_scheme.get_style_definitions()[:3]:
        print(f"   {line.strip()}")
    print("   ...")

    output_file = "dag_advanced.mmd"
    with open(output_file, 'w') as f:
        f.write(mermaid)

    print(f"\n   Saved to: {output_file}")

    queue.close()


# ==============================================================================
# Main
# ==============================================================================

def main():
    """Run all color scheme examples."""
    print("🦆"*35)
    print("  Mermaid Color Scheme Customization")
    print("  Beautiful DAG Visualizations")
    print("🦆"*35)

    example_prebuilt_themes()
    example_custom_brand()
    example_context_specific()
    example_dynamic_selection()
    example_advanced_customization()

    print("\n" + "="*70)
    print("📚 SUMMARY")
    print("="*70)
    print("""
Generated Mermaid diagrams with various color schemes:

1. Pre-built themes (6 options)
   - default, blue_professional, dark_mode
   - pastel, high_contrast, grayscale

2. Custom brand colors
   - Match your company's style guide

3. Context-specific
   - Development, production, presentation, print

4. Dynamic selection
   - Choose based on environment/user preference

5. Advanced features
   - Streaming task highlighting
   - Sub-DAG special styling

All .mmd files can be visualized at: https://mermaid.live

For documentation: Copy Mermaid code into Markdown files:

    ```mermaid
    [paste content here]
    ```

For monitoring: Use color schemes that match your dashboard theme
For presentations: Use pastel or professional themes
For accessibility: Use high contrast theme
For printing: Use grayscale theme
    """)
    print("="*70 + "\n")


if __name__ == "__main__":
    main()
