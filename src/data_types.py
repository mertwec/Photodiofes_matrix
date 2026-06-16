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
    v_x: float | None = None     # угол отклонения центра по x, град (приходит из потока)
    v_y: float | None = None     # угол отклонения центра по y, град (приходит из потока)

    radius: float | None = None
    no_signal: bool = False  # нет сигнала: точка (0, 0), рисуется красной
    lost: bool = False  # потеря позиции (nz < NZ_ANGLE_MIN, Задача №8): точка у края дисплея, жёлтая, углы — прочерк

    ts: str | None = None               # время кадра из T (мс) в формате H:M:S
    angle_x: float | None = None        # Угол отклонения центра по x, град. Рассчитывается из FOC + радиус.
    angle_y: float | None = None        # Угол отклонения центра по y, град. Рассчитывается из FOC + радиус
    x_norm: float | None = None         # разностный сигнал D (право−лево), [-1, +1]
    s: tuple[float, float, float, float] | None = None  # сырые s1..s4 кадра (АЦП)
