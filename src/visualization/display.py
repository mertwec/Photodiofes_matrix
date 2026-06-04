import time
from typing import Iterable

import matplotlib.pyplot as plt
from matplotlib.patches import Circle

from src.data_types import Frame


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

    Если Frame.radius не None, рисует жёлтую окружность с радиусом radius вокруг точки
    (визуализация физического размера пятна, откалиброванного из лога).
    Окно закрывается клавишей 'q' или досрочным завершением генератора.
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

    status_text = ax.text(
        -half + 5, half - 10,
        "No Light Detected",
        color="red", fontsize=10, visible=False,
    )
    point_label = ax.text(
        0, 0, "",
        color="white", fontsize=8, ha="left", va="bottom", visible=False,
    )
    (line,) = ax.plot([], [], "wo", markersize=6, zorder=4)

    # Окружность размера пятна (обновляется покадрово)
    spot_circle = Circle(
        (0, 0), 0.0,
        fill=True, facecolor="gold", edgecolor="yellow",
        alpha=0.18, linewidth=1.5, zorder=3, visible=False,
    )
    ax.add_patch(spot_circle)

    # Легенда снизу слева — статический текст из dict
    if legend:
        legend_text = "  |  ".join(f"{k}: {v}" for k, v in legend.items())
        ax.text(
            -half + 5, -half + 5, legend_text,
            color="lightgray", fontsize=8, ha="left", va="bottom",
        )

    # Живой референс v_x, v_y — снизу справа
    v_text = ax.text(
        half - 5, -half + 5, "",
        color="cyan", fontsize=9, ha="right", va="bottom", visible=False,
    )

    state = {"running": True}

    def on_key(event):
        if event.key == "q":
            state["running"] = False

    fig.canvas.mpl_connect("key_press_event", on_key)

    for frame in frames:
        if not state["running"] or not plt.fignum_exists(fig.number):
            break

        point = frame.point
        if point is None:
            line.set_data([], [])
            point_label.set_visible(False)
            status_text.set_visible(True)
            spot_circle.set_visible(False)
        else:
            line.set_data([point.x], [point.y])
            # Нет сигнала → красная точка в центре; обычный кадр → белая.
            color = "red" if frame.no_signal else "white"
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
            else:
                spot_circle.set_visible(False)

        if frame.v_x is not None and frame.v_y is not None:
            v_text.set_text(f"v_x={frame.v_x:+.4f}   v_y={frame.v_y:+.4f}")
            v_text.set_visible(True)
        else:
            v_text.set_visible(False)

        fig.canvas.draw_idle()
        fig.canvas.flush_events()
        time.sleep(interval)

    plt.ioff()
    plt.close(fig)
