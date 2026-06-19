"""
Графики снятых данных MEASURE.json (Задача №7).

Два вида графиков (выбор в cli_model.py show --kind):

* raw — два подграфика рядом: слева по X угол θx, справа θy; по Y в обоих сырые
  отсчёты АЦП всех четырёх каналов s1..s4 (четыре серии на подграфик).
* linearity — зависимость угла θ от разностного сигнала D (= свёртка четырёх АЦП,
  как в make_point), на которой визуально видна линейность/нелинейность: верхний
  ряд θ от сырого D (нож-модель даёт erf-кривую), нижний — θ от erfinv(D) (базис
  модели, должен быть прямой). На каждой панели — линейная подгонка + RMS и R².

Чисто офлайн: только matplotlib, без UART и без потокового дисплея (display.py).
Раскладку ph↔s применяет diffs_from_s (как в make_point); s1..s4 в режиме raw —
сырые, как лежат в MEASURE.json.
"""

import numpy as np
import matplotlib.pyplot as plt
from scipy.special import erfinv

from config import cfg
from src.compensation import diffs_from_s, points_to_arrays, predict

# Цвета каналов s1..s4 (фиксированы для обоих подграфиков режима raw).
_S_COLORS = ("deepskyblue", "gold", "lime", "tomato")


def plot_measure_data(
    points: dict, title: str | None = None, block: bool = True
) -> None:
    """
    raw: два графика — s1..s4 (ось Y) от θx и от θy (ось X), по подграфику на угол.

    :param points: словарь {iN: {s:[s1..s4], angle_x, angle_y}} из MEASURE.json.
    :param title: общий заголовок окна (например, путь к файлу и число точек).
    :param block: блокировать ли выполнение до закрытия окна (plt.show(block=...)).
    """
    if not points:
        raise ValueError("нет точек для отображения (пустой MEASURE.json)")

    _, s, ax_ang, ay_ang = points_to_arrays(points)

    plt.style.use("dark_background")
    fig, axes = plt.subplots(1, 2, figsize=(13, 6))
    if title:
        fig.suptitle(title)

    for axp, ang, ang_lbl in ((axes[0], ax_ang, "θx"), (axes[1], ay_ang, "θy")):
        for i in range(4):
            axp.scatter(
                ang, s[:, i], s=9, c=_S_COLORS[i], alpha=0.8, label=f"s{i + 1}"
            )
        axp.set_title(f"АЦП от {ang_lbl}")
        axp.set_xlabel(f"{ang_lbl}, °")
        axp.set_ylabel("отсчёты АЦП")
        axp.grid(True, alpha=0.3)
        axp.legend(loc="best", fontsize=8)

    fig.tight_layout()
    plt.show(block=block)


def _line_fit(x, y):
    """Линейная подгонка y≈a·x+b; вернуть (a, b), RMS остатка и R²."""
    a, b = np.polyfit(x, y, 1)
    resid = y - (a * x + b)
    rms = float(np.sqrt(np.mean(resid**2)))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - float(np.sum(resid**2)) / ss_tot if ss_tot else float("nan")
    return (a, b), rms, r2


def _linearity_panel(axp, sig, ang, xlabel: str) -> None:
    """Одна панель θ(сигнал): точки + прямая подгонка + подпись RMS/R²."""
    order = np.argsort(sig)
    sig, ang = sig[order], ang[order]
    (a, b), rms, r2 = _line_fit(sig, ang)
    axp.scatter(sig, ang, s=14, c="deepskyblue", alpha=0.85, label="данные")
    axp.plot(sig, a * sig + b, color="tomato", lw=1.5, label="линейная подгонка")
    axp.set_xlabel(xlabel)
    axp.set_ylabel("угол θ, °")
    axp.grid(True, alpha=0.3)
    axp.legend(loc="upper left", fontsize=8)
    axp.text(
        0.97, 0.05, f"RMS={rms:.3f}°\nR²={r2:.4f}",
        transform=axp.transAxes, ha="right", va="bottom",
        fontsize=9, color="gold",
        bbox=dict(boxstyle="round", facecolor="black", alpha=0.5),
    )


def plot_angle_linearity(
    points: dict, title: str | None = None, block: bool = True
) -> None:
    """
    linearity: θ от разностного сигнала D — видна линейность/нелинейность.

    Сетка 2x2: столбцы — оси x и y; верхний ряд θ от сырого D (нож-модель даёт
    erf-кривую → отклонение точек от прямой = нелинейность), нижний — θ от
    erfinv(clip(D, ±COMP_DMAX)) (базис компенсации, при идеальной нож-модели —
    прямая). Берём только чистые свипы (для оси x: θy=0; для y: θx=0), где
    одномерный закон θ(D) определён без кросс-засветки.

    :param points: словарь {iN: {s:[s1..s4], angle_x, angle_y}} из MEASURE.json.
    :param title: общий заголовок окна.
    :param block: блокировать ли выполнение до закрытия окна.
    """
    if not points:
        raise ValueError("нет точек для отображения (пустой MEASURE.json)")

    _, s, ax_ang, ay_ang = points_to_arrays(points)
    Dx, Dy, _ = diffs_from_s(s)  # раскладка ph↔s и ADC_MAX как в make_point
    d_max = cfg.COMP_DMAX

    # Чистые свипы: ось x — точки с θy=0; ось y — точки с θx=0.
    mx = ay_ang == 0.0
    my = ax_ang == 0.0
    for name, mask in (("x", mx), ("y", my)):
        if mask.sum() < 2:
            raise ValueError(f"мало точек чистого свипа по оси {name} ({int(mask.sum())})")

    plt.style.use("dark_background")
    fig, axes = plt.subplots(2, 2, figsize=(12, 9))
    if title:
        fig.suptitle(title)

    cols = (
        ("x", mx, Dx, ax_ang, "θx"),
        ("y", my, Dy, ay_ang, "θy"),
    )
    for c, (name, mask, D, ang, ang_lbl) in enumerate(cols):
        d = D[mask]
        th = ang[mask]
        u = erfinv(np.clip(d, -d_max, d_max))
        _linearity_panel(axes[0][c], d, th, f"D{name} (сырой сигнал)")
        axes[0][c].set_title(f"{ang_lbl} от D{name}  —  нож-модель ⇒ erf-кривая")
        _linearity_panel(axes[1][c], u, th, f"erfinv(D{name}) (базис модели)")
        axes[1][c].set_title(f"{ang_lbl} от erfinv(D{name})  —  должна быть прямой")

    fig.tight_layout()
    plt.show(block=block)


def plot_compensation_surface(
    points: dict, model, title: str | None = None, block: bool = True
) -> None:
    """
    surface: 3D-поверхности θx(Dx,Dy) и θy(Dx,Dy), задаваемые компенсационным
    полиномом, со снятыми точками и остаточными «стеблями» (измерение → поверхность).

    Две панели рядом: слева θx, справа θy. Полупрозрачная поверхность — это
    предсказание полинома (predict) на сетке (Dx,Dy) в пределах данных и зоны
    валидности |D|≤d_max; красные точки — измерения (Dx, Dy, истинный угол);
    тонкие серые отрезки — остаток от точки до поверхности (та же ошибка фита,
    что печатает cli_model verify).

    :param points: словарь {iN: {s:[s1..s4], angle_x, angle_y}} из MEASURE.json.
    :param model: CompensationModel (из COMPENSATION.json).
    :param title: общий заголовок окна.
    :param block: блокировать ли выполнение до закрытия окна.
    """
    from mpl_toolkits.mplot3d import Axes3D  # noqa: F401  регистрация проекции 3d

    if not points:
        raise ValueError("нет точек для отображения (пустой MEASURE.json)")

    _, s, ax_ang, ay_ang = points_to_arrays(points)
    Dx, Dy, _ = diffs_from_s(s)  # раскладка ph↔s и ADC_MAX как в make_point
    dm = model.d_max

    # Сетка (Dx,Dy) в пределах данных, ограниченная зоной валидности модели.
    gx = np.linspace(max(Dx.min(), -dm), min(Dx.max(), dm), 45)
    gy = np.linspace(max(Dy.min(), -dm), min(Dy.max(), dm), 45)
    GX, GY = np.meshgrid(gx, gy)
    TXg, TYg = predict(model, GX.ravel(), GY.ravel())
    TXg, TYg = TXg.reshape(GX.shape), TYg.reshape(GX.shape)
    # Предсказание в самих точках — концы остаточных стеблей.
    TXp, TYp = predict(model, Dx, Dy)

    plt.style.use("dark_background")
    fig = plt.figure(figsize=(13, 6))
    if title:
        fig.suptitle(f"{title}  —  поверхность полинома (degree {model.degree})")

    panels = (("θx", TXg, ax_ang, TXp), ("θy", TYg, ay_ang, TYp))
    for c, (lbl, Zg, ang, pred) in enumerate(panels):
        axp = fig.add_subplot(1, 2, c + 1, projection="3d")
        axp.plot_surface(
            GX, GY, Zg, cmap="viridis", alpha=0.6,
            linewidth=0, antialiased=True, rstride=2, cstride=2,
        )
        for xi, yi, ai, pi in zip(Dx, Dy, ang, pred):  # остаточные стебли
            axp.plot([xi, xi], [yi, yi], [ai, pi], color="gray", lw=0.6, alpha=0.7)
        axp.scatter(Dx, Dy, ang, c="tomato", s=14, label="измерения")
        axp.set_xlabel("Dx")
        axp.set_ylabel("Dy")
        axp.set_zlabel(f"{lbl}, °")
        axp.set_title(f"{lbl}(Dx, Dy)")

    fig.tight_layout()
    plt.show(block=block)
