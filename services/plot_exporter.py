"""Plot export helpers — image (PNG/JPG) and CSV."""
from __future__ import annotations

import csv
from pathlib import Path


def export_plot_csv(plot_data: list[dict], path: str) -> None:
    """Write plot series to a CSV file.

    Each signal becomes a pair of columns (Timestamp, Value). Signals may have
    different lengths and sampling rates, so columns are not aligned — each
    signal is stored with its own timestamps.

    Args:
        plot_data: list of dicts returned by ``PlotViewModel.get_plot_data()``.
        path:      destination file path (will be overwritten if it exists).
    """
    if not plot_data:
        return

    labels = [entry["label"] for entry in plot_data]
    series = [(entry["x"], entry["y"]) for entry in plot_data]
    max_rows = max(len(x) for x, _ in series) if series else 0

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        header = []
        for label in labels:
            header.append(f"{label} - Timestamp")
            header.append(f"{label} - Value")
        writer.writerow(header)

        for i in range(max_rows):
            row = []
            for xs, ys in series:
                if i < len(xs):
                    row.append(xs[i])
                    row.append(ys[i])
                else:
                    row.append("")
                    row.append("")
            writer.writerow(row)


def export_plot_image(widget, path: str) -> None:
    """Capture a plot widget as a PNG/JPG image.

    Uses ``QWidget.grab()`` to render exactly what is visible on screen,
    including axes, legend, and cursor overlays.

    Args:
        widget: the plot QWidget to capture.
        path:   destination file path — extension determines format
                (``*.png``, ``*.jpg``, ``*.bmp``).
    """
    pixmap = widget.grab()
    ext = Path(path).suffix.lower().lstrip(".")
    fmt = ext.upper() if ext in ("png", "jpg", "jpeg", "bmp") else "PNG"
    if not pixmap.save(path, fmt):
        raise OSError(f"Failed to save plot image to {path!r}")
