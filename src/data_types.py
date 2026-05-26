from dataclasses import dataclass

@dataclass
class Point2D:
    """2D point coordinates in pixels"""
    x: float
    y: float

    def __repr__(self):
        return f"P({self.x}, {self.y})"


@dataclass
class Frame:
    """Кадр: вычисленная точка направления + опциональный референс v_x, v_y."""
    point: Point2D | None
    v_x: float | None = None
    v_y: float | None = None
