from dataclasses import asdict, dataclass, field, fields


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


@dataclass
class CompensationModel:
    """
    Коэффициенты компенсационного полинома (Задача №13).

    Полином в erfinv-базисе: u = erfinv(clip(D, ±d_max)). Углы считаются отдельно
    по осям как θ = Σ c_k · u_x^p · u_y^q  (p+q ≤ degree). Порядок мономов
    фиксирован (тот же, что строит src/compensation.py::poly_terms):

        degree=2 → [(0,0),(0,1),(0,2),(1,0),(1,1),(2,0)]
                 = [1, u_y, u_y², u_x, u_x·u_y, u_x²]

    coef_x[k] и coef_y[k] — множители k-го монома для θx и θy соответственно.
    Углы — в шкале СТОЛИКА (angle_space="stage"), фактор зеркала = 1 (см. §12.5).
    """

    degree: int
    coef_x: list[float]
    coef_y: list[float]
    d_max: float = 0.95
    basis: str = "erfinv"
    angle_space: str = "stage"

    # --- паспорт / диагностика (для отчёта, в расчёте не участвуют) ---
    n_points: int = 0                    # точек после фильтрации/отбраковки
    rmse_deg: dict | None = None         # обучающий RMSE {"x":.., "y":..}, град
    loo_rmse_deg: dict | None = None     # leave-one-out RMSE — паспортная точность, град
    source: str | None = None            # путь к MEASURE.json
    created: str | None = None           # метка времени фита
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Сериализация в JSON-словарь (+ явные мономы terms для прозрачности)."""
        d = asdict(self)
        d["terms"] = [
            [p, q] for p in range(self.degree + 1) for q in range(self.degree + 1 - p)
        ]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "CompensationModel":
        """Десериализация: лишние ключи (например terms) игнорируются."""
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})
