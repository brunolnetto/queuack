"""
Mermaid diagram color scheme configuration.

Provides customizable color schemes for DAG visualizations with status-based
node coloring and special styles for different task types.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class MermaidColorScheme:
    """Configurable color scheme for Mermaid DAG diagrams.

    Provides status-based colors and optional task-type specific styling.
    All colors should be valid CSS colors (hex, rgb, or named colors).

    Attributes:
        pending: Color for tasks that haven't started yet
        ready: Color for tasks ready to execute (dependencies met)
        running: Color for currently executing tasks
        done: Color for successfully completed tasks
        failed: Color for failed tasks
        skipped: Color for skipped tasks
        streaming: Optional special color for streaming/generator tasks
        subdag: Optional special color for sub-DAG tasks

    Example:
        Default theme (bright, colorful):

        >>> scheme = MermaidColorScheme()
        >>> dag.export_mermaid(color_scheme=scheme)

        Custom dark theme:

        >>> dark_scheme = MermaidColorScheme(
        ...     pending="#404040",
        ...     ready="#FFA500",
        ...     running="#4169E1",
        ...     done="#228B22",
        ...     failed="#DC143C",
        ...     skipped="#696969"
        ... )

        Professional blue theme:

        >>> blue_scheme = MermaidColorScheme.blue_professional()
    """

    # Status-based colors
    pending: str = "#F0F0F0"      # Light gray - waiting
    ready: str = "#FFD700"         # Gold - ready to run
    running: str = "#87CEEB"       # Sky blue - in progress
    done: str = "#90EE90"          # Light green - success
    failed: str = "#FFB6C6"        # Light red - error
    skipped: str = "#D3D3D3"       # Gray - skipped

    # Task type colors (optional overrides)
    streaming: Optional[str] = None   # For generator/streaming tasks
    subdag: Optional[str] = None      # For sub-DAG tasks

    # Advanced styling options
    stroke_width: int = 2
    stroke_color: str = "#333"

    def get_style_definitions(self) -> list[str]:
        """Generate Mermaid classDef statements for this color scheme.

        Returns:
            List of Mermaid classDef statements

        Example:
            >>> scheme = MermaidColorScheme()
            >>> lines = scheme.get_style_definitions()
            >>> for line in lines:
            ...     print(line)
            classDef pending fill:#F0F0F0,stroke:#333,stroke-width:2px
            classDef ready fill:#FFD700,stroke:#333,stroke-width:2px
            ...
        """
        styles = []

        # Status-based styles
        for status in ['pending', 'ready', 'running', 'done', 'failed', 'skipped']:
            color = getattr(self, status)
            styles.append(
                f"    classDef {status} fill:{color},stroke:{self.stroke_color},"
                f"stroke-width:{self.stroke_width}px"
            )

        # Task type styles (if specified)
        if self.streaming:
            styles.append(
                f"    classDef streaming fill:{self.streaming},stroke:{self.stroke_color},"
                f"stroke-width:{self.stroke_width}px,stroke-dasharray: 5 5"
            )

        if self.subdag:
            styles.append(
                f"    classDef subdag fill:{self.subdag},stroke:{self.stroke_color},"
                f"stroke-width:3px"
            )

        return styles

    def get_status_class(self, status: str) -> str:
        """Get the Mermaid class name for a given status.

        Args:
            status: Status string (e.g., 'done', 'running')

        Returns:
            Mermaid class syntax (e.g., ':::done')
        """
        status_lower = status.lower()
        if status_lower in ['pending', 'ready', 'running', 'done', 'failed', 'skipped']:
            return f":::{status_lower}"
        return ""

    def get_task_type_class(self, task_type: str) -> str:
        """Get the Mermaid class name for a task type.

        Args:
            task_type: Type of task ('streaming', 'subdag', etc.)

        Returns:
            Mermaid class syntax or empty string if not configured
        """
        if task_type == 'streaming' and self.streaming:
            return ":::streaming"
        elif task_type == 'subdag' and self.subdag:
            return ":::subdag"
        return ""

    @classmethod
    def default(cls) -> "MermaidColorScheme":
        """Create default color scheme (bright, colorful).

        Returns:
            Default MermaidColorScheme instance
        """
        return cls()

    @classmethod
    def blue_professional(cls) -> "MermaidColorScheme":
        """Create professional blue-themed color scheme.

        Returns:
            Blue professional color scheme
        """
        return cls(
            pending="#E3F2FD",     # Very light blue
            ready="#64B5F6",       # Medium blue
            running="#2196F3",     # Bright blue
            done="#4CAF50",        # Green
            failed="#F44336",      # Red
            skipped="#9E9E9E",     # Gray
            streaming="#1976D2",   # Dark blue for streaming
            subdag="#0D47A1",      # Very dark blue for sub-DAGs
            stroke_color="#0D47A1"
        )

    @classmethod
    def dark_mode(cls) -> "MermaidColorScheme":
        """Create dark mode color scheme.

        Returns:
            Dark mode color scheme
        """
        return cls(
            pending="#424242",     # Dark gray
            ready="#FFA726",       # Orange
            running="#42A5F5",     # Light blue
            done="#66BB6A",        # Light green
            failed="#EF5350",      # Light red
            skipped="#757575",     # Medium gray
            streaming="#29B6F6",   # Cyan blue
            subdag="#1E88E5",      # Darker blue
            stroke_color="#E0E0E0",
            stroke_width=2
        )

    @classmethod
    def pastel(cls) -> "MermaidColorScheme":
        """Create soft pastel color scheme.

        Returns:
            Pastel color scheme
        """
        return cls(
            pending="#F5F5F5",     # Off white
            ready="#FFE082",       # Pastel yellow
            running="#81D4FA",     # Pastel blue
            done="#A5D6A7",        # Pastel green
            failed="#EF9A9A",      # Pastel red
            skipped="#E0E0E0",     # Light gray
            streaming="#80DEEA",   # Pastel cyan
            subdag="#9FA8DA",      # Pastel indigo
            stroke_color="#BDBDBD",
            stroke_width=1
        )

    @classmethod
    def high_contrast(cls) -> "MermaidColorScheme":
        """Create high contrast color scheme for accessibility.

        Returns:
            High contrast color scheme
        """
        return cls(
            pending="#FFFFFF",     # White
            ready="#FFFF00",       # Yellow
            running="#0000FF",     # Blue
            done="#00FF00",        # Green
            failed="#FF0000",      # Red
            skipped="#808080",     # Gray
            streaming="#00FFFF",   # Cyan
            subdag="#FF00FF",      # Magenta
            stroke_color="#000000",
            stroke_width=3
        )

    @classmethod
    def grayscale(cls) -> "MermaidColorScheme":
        """Create grayscale color scheme (no colors, only shades of gray).

        Returns:
            Grayscale color scheme
        """
        return cls(
            pending="#F0F0F0",     # Very light gray
            ready="#C0C0C0",       # Light gray
            running="#808080",     # Medium gray
            done="#606060",        # Dark gray
            failed="#404040",      # Darker gray
            skipped="#D0D0D0",     # Light-medium gray
            streaming="#707070",   # Medium-dark gray
            subdag="#505050",      # Very dark gray
            stroke_color="#000000",
            stroke_width=2
        )
