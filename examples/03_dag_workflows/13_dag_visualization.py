"""13_dag_visualization.py - Export and visualize DAG structure

This example demonstrates DAG visualization:
- Export DAG to Mermaid diagram format
- Visualize execution order and dependencies
- Show job status with color coding
- Generate documentation from DAG structure

Key Concepts:
- DAG visualization: See workflow structure
- Mermaid diagrams: Standard diagram format
- Status coloring: Visual status indicators
- Documentation generation: Auto-generate workflow docs

Real-world Use Cases:
- Workflow documentation
- Team communication about pipelines
- Debugging complex DAGs
- Presenting workflows to stakeholders

# Difficulty: beginner
"""

from queuack import DAG
from queuack.mermaid_colors import MermaidColorScheme


def step_a():
    print("Step A")
    return "A"


def step_b():
    print("Step B")
    return "B"


def step_c():
    print("Step C")
    return "C"


def step_d():
    print("Step D")
    return "D"


print("🦆 DAG Visualization Example")
print("=============================")
print("This example shows how to export DAG structure as diagrams.")
print()

with DAG("visualization_demo") as dag:
    # Build a small DAG
    a = dag.add_node(step_a, name="step_a")
    b = dag.add_node(step_b, name="step_b", depends_on="step_a")
    c = dag.add_node(step_c, name="step_c", depends_on="step_a")
    d = dag.add_node(step_d, name="step_d", depends_on=["step_b", "step_c"])
    
    # Export to Mermaid format (before execution)
    print("📊 DAG Structure (Mermaid format):")
    print("===================================")
    mermaid = dag.export_mermaid()
    print(mermaid)
    print()
    
    print("💡 Tip: Copy the above Mermaid code to visualize at:")
    print("   https://mermaid.live/")
    print()
    
    # Also show with custom color scheme
    print("🎨 Same DAG with custom colors:")
    print("================================")
    dark_scheme = MermaidColorScheme.dark_mode()
    mermaid_dark = dag.export_mermaid(color_scheme=dark_scheme)
    print(mermaid_dark)
    print()
    
    # Execute the DAG
    dag.submit()
    dag.wait_for_completion()
    
    # Export again after execution to show status colors
    print("\n📊 DAG After Execution (with status colors):")
    print("=============================================")
    mermaid_final = dag.export_mermaid()
    print(mermaid_final)

print("\n✅ Visualization example complete!")
print()
print("💡 Available color schemes:")
print("   - MermaidColorScheme.default()")
print("   - MermaidColorScheme.dark_mode()")
print("   - MermaidColorScheme.blue_professional()")
print("   - MermaidColorScheme.pastel()")
print("   - MermaidColorScheme.high_contrast()")
print("   - MermaidColorScheme.grayscale()")