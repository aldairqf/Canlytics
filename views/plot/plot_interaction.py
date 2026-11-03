from __future__ import annotations
class PlotInteraction:
    def __init__(self):
        self.selected: str | None = None

    def select(self, name: str):
        self.selected = name

    def clear(self):
        self.selected = None
