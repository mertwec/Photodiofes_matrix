import time
from dataclasses import dataclass
from typing import Iterable

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Circle
from matplotlib.text import Text

from config import cfg
from src.data_types import Frame, Point2D
from src.utils.converter import format_duration_hms

# Вертикальная раскладка левой колонки подписей: отступ строки от верхней
# границы дисплея, px. Слоты неравномерные — вёрстка как была.
_ROW_TOP = 10  # «нет засветки» / радиус пятна (взаимоисключающие)
_ROW_ANG = 20  # углы θx/θy
_ROW_DX = 32  # разностный сигнал Dx
_ROW_DY = 38  # разностный сигнал Dy


def draw_quadrant_labels(ax, half: float) -> None:
    """
    Тёмно-серые подписи квадрантов S1..S4 в центрах четвертей дисплея.

    Раскладка — физическая, как у датчика (CSV/UART): s1|s4 сверху, s2|s3 снизу
    (см. ph↔s в get_single_point). half — половина размера дисплея, px.
    Используется всеми режимами (log/stream, calibr, measure).
    """
    q = half / 2
    for lbl, (x, y) in (
        ("S1", (-q, q)),
        ("S4", (q, q)),
        ("S2", (-q, -q)),
        ("S3", (q, -q)),
    ):
        ax.text(
            x, y, lbl, color="dimgray", fontsize=18, ha="center", va="center", zorder=1
        )


def _hud_text(
    ax: Axes,
    x: float,
    y: float,
    color: str,
    fontsize: float = 9,
    ha: str = "left",
    va: str = "top",
    text: str = "",
    **kw,
) -> Text:
    """
    Скрытая подпись-оверлей: общий шаблон для всех надписей дисплея.

    text задаётся сразу только для подписей с постоянным содержимым (статус);
    остальные создаются пустыми и наполняются покадрово из _Overlays.
    """
    return ax.text(
        x, y, text, color=color, fontsize=fontsize, ha=ha, va=va, visible=False, **kw
    )


def _setup_axes(size: int) -> tuple[Figure, Axes]:
    """
    Статическая сцена: тёмная тема, квадратная область size x size, оси, квадранты.

    Стиль переключается глобально (dark_background) и фигура создаётся заново —
    на каждый вызов display_points_stream, как и раньше.
    """
    plt.ion()
    plt.style.use("dark_background")

    fig, ax = plt.subplots(figsize=(7, 7))
    half = size / 2 + 5
    ax.set_xlim(-half, half)
    ax.set_ylim(-half, half)
    ax.set_aspect("equal", adjustable="box")
    ax.axvline(0, color="green", linestyle="--", linewidth=1)
    ax.axhline(0, color="green", linestyle="--", linewidth=1)
    draw_quadrant_labels(ax, size / 2)
    return fig, ax


@dataclass
class _Overlays:
    """
    Артисты дисплея: создаются один раз, покадрово обновляются из Frame.

    Каждая группа читает СВОИ поля кадра и сама решает, показываться ли, — набор
    отображаемого определяется только заполненностью Frame (radius=None → нет
    круга, angle_*=None → нет углов и т.д.). Один артист — один владеющий метод.
    """

    size: int  # размер дисплея, px — нужен для перевода радиуса px → мм

    point: Line2D
    label: Text
    status: Text
    spot: Circle
    radius: Text
    angles: Text
    dx: Text
    dy: Text
    v: Text
    clock: Text
    sensors: Text

    def update(self, frame: Frame, elapsed_ms: float) -> None:
        """Обновить все группы оверлеев по кадру."""
        self.update_point(frame)
        self.update_angles(frame)
        self.update_diffs(frame)
        self.update_reference(frame)
        self.update_sensors(frame)
        self.update_clock(elapsed_ms)

    def update_point(self, frame: Frame) -> None:
        """
        Точка направления засветки, подпись координат и круг пятна.

        point=None — фолбэк «No Light Detected» для возможных будущих источников;
        штатный признак «нет сигнала» — красная точка в центре (no_signal).
        """
        point = frame.point
        if point is None:
            self.point.set_data([], [])
            self.label.set_visible(False)
            self.status.set_visible(True)
            self.spot.set_visible(False)
            self.radius.set_visible(False)
            return

        self.point.set_data([point.x], [point.y])
        # Нет сигнала → красная точка в центре; потеря позиции (Задача №8,
        # nz ≤ NZ_ANGLE_MIN) → жёлтая точка у края; обычный кадр → белая.
        if frame.no_signal:
            color = "red"
        elif frame.lost:
            color = "yellow"
        else:
            color = "white"
        self.point.set_markerfacecolor(color)
        self.point.set_markeredgecolor(color)
        self.label.set_position((point.x + 1, point.y + 1))
        self.label.set_text(f"({point.x:.1f}, {point.y:.1f})")
        self.label.set_visible(True)
        self.status.set_visible(False)
        self._update_spot(frame, point)

    def _update_spot(self, frame: Frame, point: Point2D) -> None:
        """Круг пятна и его радиус в мм (радиус — только из калибровки, Задача №5)."""
        if not frame.radius:
            self.spot.set_visible(False)
            self.radius.set_visible(False)
            return

        self.spot.center = (point.x, point.y)
        self.spot.set_radius(frame.radius)
        self.spot.set_visible(True)

        # Радиус пятна в мм: вся зона датчика DET_SIZE_MM ↔ весь дисплей size,
        # поэтому r_мм = r_px · DET_SIZE_MM / size. В скобках — доля от полного
        # размера зоны датчика.
        r_mm = frame.radius * cfg.DET_SIZE_MM / self.size
        pct = frame.radius / self.size * 100.0
        self.radius.set_text(
            f"r ≈ {r_mm:.2f} мм ({pct:.0f}% зоны {cfg.DET_SIZE_MM:.0f} мм)"
        )
        self.radius.set_visible(True)

    def update_angles(self, frame: Frame) -> None:
        """
        Углы отклонения θx/θy (из фокуса и радиуса пятна либо из полинома).

        При потере позиции (Задача №8) угол сейчас не измеряется — держим
        последний измеренный жёлтым; если измерений ещё не было — прочерк.
        """
        measured = frame.angle_x is not None and frame.angle_y is not None
        if not measured and not frame.lost:
            self.angles.set_visible(False)
            return

        self.angles.set_text(
            f"θx={frame.angle_x:+.2f}°   θy={frame.angle_y:+.2f}°"
            if measured
            else "θx= —   θy= —"
        )
        self.angles.set_color("yellow" if frame.lost else "lightgreen")
        self.angles.set_visible(True)

    def update_diffs(self, frame: Frame) -> None:
        """Разностные сигналы Dx (право−лево) и Dy (верх−низ)."""
        show = frame.x_norm is not None and frame.y_norm is not None
        if show:
            self.dx.set_text(f"Dx={frame.x_norm:+.3f}")
            self.dy.set_text(f"Dy={frame.y_norm:+.3f}")
        self.dx.set_visible(show)
        self.dy.set_visible(show)

    def update_reference(self, frame: Frame) -> None:
        """Опорные v_x/v_y устройства — справочно (в расчётах не участвуют)."""
        show = frame.v_x is not None and frame.v_y is not None
        if show:
            self.v.set_text(f"Vx={frame.v_x:+.4f}   Vy={frame.v_y:+.4f}")
        self.v.set_visible(show)

    def update_sensors(self, frame: Frame) -> None:
        """Сырые значения каналов s1..s4 кадра в столбик."""
        if frame.s is None:
            self.sensors.set_visible(False)
            return
        self.sensors.set_text(
            "\n".join(f"s{i} = {v:.0f}" for i, v in enumerate(frame.s, 1))
        )
        self.sensors.set_visible(True)

    def update_clock(self, elapsed_ms: float) -> None:
        """Прошедшее время с первого кадра (часы хоста, формат H:M:S)."""
        self.clock.set_text(f"t: {format_duration_hms(elapsed_ms)}")
        self.clock.set_visible(True)


def _make_overlays(ax: Axes, size: int, legend: dict | None = None) -> _Overlays:
    """
    Создать артисты дисплея (изначально скрытые) и статическую легенду.

    ВАЖЕН ПОРЯДОК создания: у текста и круга пятна одинаковый zorder=3, поэтому
    перекрытие решается порядком добавления — подпись координат создаётся ДО
    круга и потому подкрашивается им, а не рисуется поверх.
    """
    half = size / 2 + 5

    # Фолбэк-статус для источников с point=None (штатное «нет сигнала» — красная
    # точка в центре). Выравнивание по базовой линии — как в исходной вёрстке.
    status = _hud_text(
        ax, -half + 5, half - _ROW_TOP, "red", 10, va="baseline",
        text="No Light Detected",
    )
    label = _hud_text(ax, 0, 0, "white", 8, va="bottom")
    (line,) = ax.plot([], [], "wo", markersize=6, zorder=4)

    # Окружность размера пятна (обновляется покадрово)
    spot = Circle(
        (0, 0),
        0.0,
        fill=True,
        facecolor="gold",
        edgecolor="yellow",
        alpha=0.18,
        linewidth=1.5,
        zorder=3,
        visible=False,
    )
    ax.add_patch(spot)

    # Легенда снизу слева — статический текст из dict, покадрово не меняется.
    if legend:
        ax.text(
            -half + 5,
            -half + 5,
            "  |  ".join(f"{k}: {v}" for k, v in legend.items()),
            color="lightgray",
            fontsize=8,
            ha="left",
            va="bottom",
        )

    return _Overlays(
        size=size,
        point=line,
        label=label,
        status=status,
        spot=spot,
        # Живой референс v_x, v_y — снизу справа.
        v=_hud_text(ax, half - 5, -half + 5, "cyan", ha="right", va="bottom"),
        # Прошедшее время с начала получения данных — сверху справа. Считается по
        # часам хоста, а НЕ из устройства: T — быстрый кольцевой счётчик
        # (≈1.15 мкс/тик, переполняется ~каждые 9 с), временем он быть не может.
        clock=_hud_text(ax, half - 5, half - _ROW_TOP, "lightgray", ha="right"),
        # Живой радиус пятна в мм — тот же слот, что и статус: обе подписи
        # взаимоисключающие (есть точка ⇔ нет «No Light Detected»).
        radius=_hud_text(ax, -half + 5, half - _ROW_TOP, "gold"),
        angles=_hud_text(ax, -half + 5, half - _ROW_ANG, "green", 10),
        dx=_hud_text(ax, -half + 5, half - _ROW_DX, "gold"),
        dy=_hud_text(ax, -half + 5, half - _ROW_DY, "gold"),
        # Сырые значения каналов s1..s4 в столбик — справа, под временем кадра.
        sensors=_hud_text(
            ax, half - 25, half - _ROW_ANG, "lightgray", family="monospace"
        ),
    )


def display_points_stream(
    frames: Iterable[Frame],
    size: int = 200,
    interval: float = 0.05,
    legend: dict | None = None,
) -> None:
    """
    Интерактивная визуализация потока кадров Frame.

    :param frames: итератор/генератор Frame (Frame.point=None — нет засветки).
    :param size: размер дисплея в пикселях (рабочая область — квадрат size x size).
    :param interval: пауза между кадрами в секундах.
    :param legend: словарь {key: value}, рендерится статической подписью снизу.

    Сцену строит _setup_axes, оверлеи — _make_overlays; здесь остаётся только
    цикл кадров: обновить оверлеи (_Overlays.update) и перерисовать. Если
    Frame.radius не None (постоянный радиус из калибровки, Задача №5), рисуется
    жёлтая окружность вокруг точки. Без калибровки radius=None — только точка,
    без круга. Окно закрывается клавишей 'q' или досрочным завершением генератора.
    """
    fig, ax = _setup_axes(size)
    hud = _make_overlays(ax, size, legend)

    state = {"running": True}

    def on_key(event):
        if event.key == "q":
            state["running"] = False

    fig.canvas.mpl_connect("key_press_event", on_key)

    t_start: float | None = None  # момент первого кадра — отсчёт прошедшего времени

    for frame in frames:
        if not state["running"] or not plt.fignum_exists(fig.number):
            break
        if t_start is None:
            t_start = time.monotonic()  # начало получения данных

        hud.update(frame, (time.monotonic() - t_start) * 1000)

        fig.canvas.draw_idle()
        fig.canvas.flush_events()
        time.sleep(interval)

    plt.ioff()
    plt.close(fig)
