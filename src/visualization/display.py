import time
from typing import Iterable

import matplotlib.pyplot as plt
from matplotlib.patches import Circle

from config import cfg
from src.data_types import Frame
from src.utils.converter import format_duration_hms


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

    Если Frame.radius не None (постоянный радиус из калибровки, Задача №5),
    рисует жёлтую окружность радиуса radius вокруг точки. Без калибровки
    radius=None — только точка, без круга. Окно закрывается клавишей 'q' или
    досрочным завершением генератора.
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

    status_text = ax.text(
        -half + 5,
        half - 10,
        "No Light Detected",
        color="red",
        fontsize=10,
        visible=False,
    )
    point_label = ax.text(
        0,
        0,
        "",
        color="white",
        fontsize=8,
        ha="left",
        va="bottom",
        visible=False,
    )
    (line,) = ax.plot([], [], "wo", markersize=6, zorder=4)

    # Окружность размера пятна (обновляется покадрово)
    spot_circle = Circle(
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
    ax.add_patch(spot_circle)

    # Легенда снизу слева — статический текст из dict
    if legend:
        legend_text = "  |  ".join(f"{k}: {v}" for k, v in legend.items())
        ax.text(
            -half + 5,
            -half + 5,
            legend_text,
            color="lightgray",
            fontsize=8,
            ha="left",
            va="bottom",
        )

    # Живой референс v_x, v_y — снизу справа
    v_text = ax.text(
        half - 5,
        -half + 5,
        "",
        color="cyan",
        fontsize=9,
        ha="right",
        va="bottom",
        visible=False,
    )

    # Прошедшее время с начала получения данных (формат H:M:S) — сверху справа.
    # Считается по часам хоста от первого кадра, а НЕ из устройства: T — это
    # быстрый кольцевой счётчик (≈1.15 мкс/тик, переполняется ~каждые 9 с),
    # поэтому пересчитывать его во время нельзя.
    ts_text = ax.text(
        half - 5,
        half - 10,
        "",
        color="lightgray",
        fontsize=9,
        ha="right",
        va="top",
        visible=False,
    )

    # Живой радиус пятна в мм относительно зоны датчика (DET_SIZE_MM) — сверху слева.
    # Работает и для калибровки (постоянный радиус), и для потокового расчёта:
    # обе ветки кладут радиус в Frame.radius (px), здесь переводим px → мм.
    r_text = ax.text(
        -half + 5,
        half - 10,
        "",
        color="gold",
        fontsize=9,
        ha="left",
        va="top",
        visible=False,
    )

    # Углы отклонения центра по x/y (из фокуса и радиуса пятна) — сверху слева,
    # под строкой радиуса.
    ang_text = ax.text(
        -half + 5,
        half - 20,
        "",
        color="green",
        fontsize=10,
        ha="left",
        va="top",
        visible=False,
    )

    # Разностный сигнал D (право−лево, = x_norm) — сверху слева, под углами.
    dx_text = ax.text(
        -half + 5,
        half - 32,
        "",
        color="gold",
        fontsize=9,
        ha="left",
        va="top",
        visible=False,
    )

    dy_text = ax.text(
        -half + 5,
        half - 38,
        "",
        color="gold",
        fontsize=9,
        ha="left",
        va="top",
        visible=False,
    )

    # Сырые значения каналов s1..s4 в столбик — справа, под временем кадра.
    s_text = ax.text(
        half - 25,
        half - 20,
        "",
        color="lightgray",
        fontsize=9,
        ha="left",
        va="top",
        family="monospace",
        visible=False,
    )

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

        point = frame.point
        if point is None:
            line.set_data([], [])
            point_label.set_visible(False)
            status_text.set_visible(True)
            spot_circle.set_visible(False)
            r_text.set_visible(False)
            ang_text.set_visible(False)
        else:
            line.set_data([point.x], [point.y])
            # Нет сигнала → красная точка в центре; потеря позиции (Задача №8,
            # nz < NZ_ANGLE_MIN) → жёлтая точка у края; обычный кадр → белая.
            if frame.no_signal:
                color = "red"
            elif frame.lost:
                color = "yellow"
            else:
                color = "white"
            line.set_markerfacecolor(color)
            line.set_markeredgecolor(color)
            point_label.set_position((point.x + 1, point.y + 1))
            point_label.set_text(f"({point.x:.1f}, {point.y:.1f})")
            point_label.set_visible(True)
            status_text.set_visible(False)

            if frame.radius:
                spot_circle.center = (point.x, point.y)
                spot_circle.set_radius(frame.radius)
                spot_circle.set_visible(True)

                # Радиус пятна в мм: вся зона датчика DET_SIZE_MM ↔ весь дисплей
                # size, поэтому r_мм = r_px · DET_SIZE_MM / size. В скобках — доля
                # от полного размера зоны датчика.
                r_mm = frame.radius * cfg.DET_SIZE_MM / size
                pct = frame.radius / size * 100.0
                r_text.set_text(
                    f"r ≈ {r_mm:.2f} мм ({pct:.0f}% зоны {cfg.DET_SIZE_MM:.0f} мм)"
                )
                r_text.set_visible(True)
            else:
                spot_circle.set_visible(False)
                r_text.set_visible(False)

        if frame.v_x is not None and frame.v_y is not None:
            v_text.set_text(f"Vx={frame.v_x:+.4f}   Vy={frame.v_y:+.4f}")
            v_text.set_visible(True)
        else:
            v_text.set_visible(False)

        if frame.lost:
            # Потеря позиции: угол сейчас не измеряется — держим последний
            # измеренный (жёлтым). Если измерений ещё не было — прочерк.
            if frame.angle_x is not None and frame.angle_y is not None:
                ang_text.set_text(
                    f"θx={frame.angle_x:+.2f}°   θy={frame.angle_y:+.2f}°"
                )
            else:
                ang_text.set_text("θx= —   θy= —")
            ang_text.set_color("yellow")
            ang_text.set_visible(True)
        elif frame.angle_x is not None and frame.angle_y is not None:
            ang_text.set_text(f"θx={frame.angle_x:+.2f}°   θy={frame.angle_y:+.2f}°")
            ang_text.set_color("lightgreen")
            ang_text.set_visible(True)
        else:
            ang_text.set_visible(False)

        if frame.x_norm is not None and frame.y_norm is not None:
            dx_text.set_text(f"Dx={frame.x_norm:+.3f}")
            dy_text.set_text(f"Dy={frame.y_norm:+.3f}")
            dy_text.set_visible(True)
            dx_text.set_visible(True)
        else:
            dx_text.set_visible(False)
            dy_text.set_visible(False)

        # Прошедшее время с первого кадра (получения данных), часы хоста.
        ts_text.set_text(f"t: {format_duration_hms((time.monotonic() - t_start) * 1000)}")
        ts_text.set_visible(True)

        if frame.s is not None:
            s_text.set_text(
                "\n".join(f"s{i} = {v:.0f}" for i, v in enumerate(frame.s, 1))
            )
            s_text.set_visible(True)
        else:
            s_text.set_visible(False)

        fig.canvas.draw_idle()
        fig.canvas.flush_events()
        time.sleep(interval)

    plt.ioff()
    plt.close(fig)
