import matplotlib.pyplot as plt
from src.data_types import Point2D
import matplotlib.pyplot as plt


def display_single_light_point(point: Point2D | None, size:int = 200) -> None:
    """
    Displays the light direction point on a 2D plot.

    param:
    point (Point2D | None): The point representing the light direction.
    size (int): The size of the display in pixels.
    """
    size = size + 10
    plt.style.use('dark_background')
    plt.figure(figsize=(6, 6))
    plt.xlim(-size/2, size/2)
    plt.ylim(-size/2, size/2)
    plt.gca().set_aspect('equal', adjustable='box')
    plt.grid(True, which="minor")
    plt.axvline(
        x=0,
        color='green',
        linestyle='--',
        linewidth=1
    )

    # Рисуем горизонтальную осевую линию (ось X) через центр дисплея
    plt.axhline(
        y=0,
        color='green',
        linestyle='--',
        linewidth=1
    )

    if point is not None:
        plt.plot(point.x, point.y, 'go')  # Green dot for the light direction point
        plt.text(point.x + 2, point.y + 2, f"({point.x}, {point.y})", color='green')
    else:
        plt.text(- 10, 0, "No Light Detected", color='red', fontsize=12)

    plt.title("Light Direction Point Display")
    plt.xlabel("X (pixels)")
    plt.ylabel("Y (pixels)")
    plt.show()
