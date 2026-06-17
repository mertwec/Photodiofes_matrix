"""
Предварительная калибровка нож-сканированием по границе квадранта (Задача №4).

Эксперимент А из AI_ANSWER.md (§4): измеряем разностный сигнал детектора в трёх
положениях луча — центр (i0) и два крайних (i1 право, i2 лево) — и для каждого
записываем угол поворотного столика. По известному смещению (угол × фокус FOC) и
измеренному сигналу далее (офлайн) восстанавливается размер пятна `w = x / h⁻¹(D)`,
где `D = x_norm` — нормированная разность право/лево.

Процедура интерактивна: в окне matplotlib видна live-точка направления засветки;
в целевой зоне точка подсвечивается зелёным (подсказка). Фиксация — ТОЛЬКО по
явному подтверждению клавишей «w» (AI_ANALYSE.md §9.4: автофиксация по
пересечению порога снимала точку во время движения столика): оператор наводит
луч, останавливает столик, жмёт «w» — усредняются следующие cfg.CALIB_HOLD
кадров, затем в терминале запрашивается угол столика. После каждой точки сразу
пересчитывается и печатается текущая оценка радиуса w (мгновенный контроль
качества калибровки). Результат пишется в JSON.
"""

import json
import time
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt

from config import cfg
from src.pipeline.calib_radius import spot_radius_from_points
from src.pipeline.get_single_point import quadrant_fracs
from src.visualization.display import draw_quadrant_labels

# Шаги сканирования: (ключ, человекочитаемое название, тип условия фиксации).
# Порядок i1/i2 не важен (см. TASK.md).
_STEPS = (
    ("i0", "ЦЕНТР (луч по центру)", "center"),
    ("i1", "крайнее ПРАВОЕ", "right"),
    ("i2", "крайнее ЛЕВОЕ", "left"),
)


def average_s(samples: list) -> list[float]:
    """Поканальное среднее списка кортежей s1..s4 (округление до 0.1 АЦП).

    Общее усреднение захвата: используется и в калибровке (cfg.CALIB_HOLD кадров),
    и в режиме measure (cfg.MEASURE_HOLD кадров, Задача №7).
    """
    return [round(sum(c) / len(c), 1) for c in zip(*samples)]


def _read_metrics(row: dict, adc_max: float):
    """
    Строка датчиков → (s, x_norm, y_norm, P, sig).

    x_norm/y_norm — нормированное направление (как в light_direction_to_point);
    x_norm и есть разностный сигнал D по горизонтали (право − лево). sig — max доля
    засветки квадранта (индикатор присутствия луча). P — суммарная яркость.
    """
    s = (float(row["s1"]), float(row["s2"]), float(row["s3"]), float(row["s4"]))
    b1, b2, b3, b4 = (max(0.0, adc_max - v) for v in s)
    P = b1 + b2 + b3 + b4
    if P > 0:
        x_norm = (b4 + b3 - b1 - b2) / P  # право − лево  (= D)
        y_norm = (b1 + b4 - b2 - b3) / P  # верх − низ
    else:
        x_norm = y_norm = 0.0
    fracs = quadrant_fracs(s, cfg.S_VAL_MAX, cfg.S_VAL_MIN) or (0.0,)
    return s, x_norm, y_norm, P, max(fracs)


def _pos_ok(kind: str, x_norm: float, y_norm: float, sig: float) -> bool:
    """Достигнуто ли целевое положение для шага kind (с проверкой наличия луча)."""
    if sig < cfg.CALIB_MIN_FRAC:
        return False  # луча нет / слишком тускло
    if kind == "center":
        return abs(x_norm) < cfg.CALIB_CENTER_EPS and abs(y_norm) < cfg.CALIB_CENTER_EPS
    if kind == "right":
        return x_norm > cfg.CALIB_SIDE_EPS
    if kind == "left":
        return x_norm < -cfg.CALIB_SIDE_EPS
    return False


def _ask_angle(title: str) -> float:
    """Запросить в терминале угол поворотного столика (град)."""
    while True:
        ans = (
            input(f"  Введите угол столика для «{title}» (град): ")
            .strip()
            .replace(",", ".")
        )
        try:
            return float(ans)
        except ValueError:
            print("  Нужно число, например 2.0 или -2.0")


def save_calibration(results: dict, out_dir: Path | str) -> Path:
    """
    Сохранить результат калибровки в `CALIB_{timestamp}.json`. Возвращает путь.

    В JSON: углы столика `{"i0":.., "i1":.., "i2":..}` (как в TASK.md) + по каждой
    точке усреднённые s1..s4, x_norm (D), P и число усреднённых кадров — этого
    достаточно для последующего офлайн-расчёта размера пятна (AI_ANSWER.md §4.7).
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"CALIBRATE.json"
    angles = {k: results[k]["angle"] for k in results}  # {"i0":0.0,"i1":2.0,"i2":-2.0}
    payload = {
        "created": ts,
        "profile": "gauss_1e2",
        "fov": cfg.FOC,
        "angles": angles,
        "points": results,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _set_point_color(point, color: str) -> None:
    point.set_markerfacecolor(color)
    point.set_markeredgecolor(color)


def _report_radius(results: dict) -> None:
    """
    Мгновенный контроль (AI_ANALYSE.md §9.4): пересчитать и показать w по уже
    снятым точкам — брак калибровки виден сразу, пока стенд собран.
    """
    info = spot_radius_from_points(results)
    if info is None:
        return
    pp = "   ".join(
        f"{k}: w={v['w_mm']} мм"
        for k, v in info["per_point"].items()
        if v["w_mm"] is not None
    )
    print(
        f"  [w] текущая оценка: w = {info['w_mm']:.2f} мм "
        f"(r = {info['radius_px']:.1f} px)   {pp}"
    )
    for msg in info["warnings"]:
        print(f"  ⚠ {msg}")


def _run_step(rows, fig, point, hint_text, s_text, kind, adc_max, half, state):
    """
    Live-цикл одного шага: оператор наводит луч (в целевой зоне точка зеленеет —
    это подсказка), останавливает столик и подтверждает клавишей «w». После
    подтверждения усредняются следующие cfg.CALIB_HOLD кадров (AI_ANALYSE.md
    §9.4: фиксация только по явной команде, а не по пересечению порога —
    автофиксация снимала точку, пока столик ещё вращался).

    Возвращает усреднённую запись {s, x_norm, P, n} либо None (отмена/конец потока).
    """
    state["capture"] = False
    buf: list = []
    for row in rows:
        if not state["running"] or not plt.fignum_exists(fig.number):
            return None
        s, x_norm, y_norm, P, sig = _read_metrics(row, adc_max)
        point.set_data([x_norm * half], [y_norm * half])
        s_text.set_text("\n".join(f"s{i} = {v:.0f}" for i, v in enumerate(s, 1)))
        if state["capture"]:
            buf.append((s, x_norm, P, sig))
            _set_point_color(point, "lime")
            hint_text.set_text(f"захват {len(buf)}/{cfg.CALIB_HOLD}   x={x_norm:+.3f}")
        else:
            ok = _pos_ok(kind, x_norm, y_norm, sig)
            _set_point_color(point, "lime" if ok else "white")
            hint_text.set_text(
                f"наведите, остановите столик и нажмите «w»   x={x_norm:+.3f}"
            )
        fig.canvas.draw_idle()
        fig.canvas.flush_events()
        time.sleep(0.01)
        if len(buf) >= cfg.CALIB_HOLD:
            s_avg = average_s([r[0] for r in buf])
            x_avg = sum(r[1] for r in buf) / len(buf)
            P_avg = sum(r[2] for r in buf) / len(buf)
            # Контроль качества захвата: дрейф D — столик ещё двигался;
            # слабый сигнал — луч не на датчике.
            spread = max(r[1] for r in buf) - min(r[1] for r in buf)
            if spread > 0.02:
                print(
                    f"  ⚠ D дрейфовал во время захвата (размах {spread:.3f}) — "
                    "столик двигался? Точку стоит переснять."
                )
            if max(r[3] for r in buf) < cfg.CALIB_MIN_FRAC:
                print("  ⚠ слабый сигнал во время захвата — луч на датчике?")
            hint_text.set_text("ЗАФИКСИРОВАНО — введите угол в терминале")
            fig.canvas.draw_idle()
            fig.canvas.flush_events()
            return {
                "s": s_avg,
                "x_norm": round(x_avg, 4),
                "P": round(P_avg, 1),
                "n": len(buf),
            }
    return None


def run_calibration(
    rows, adc_max: float, size: int, out_dir: Path | str
) -> Path | None:
    """
    Провести интерактивную калибровку (3 шага) и сохранить JSON.

    :param rows: генератор строк датчиков (read_serial_rows).
    :param adc_max: опорный максимум АЦП.
    :param size: размер дисплея, px.
    :param out_dir: каталог для CALIB_*.json.
    :return: путь к сохранённому JSON или None, если калибровка прервана (клавиша q
             / закрытие окна / обрыв потока).
    """
    half = size / 2
    plt.ion()
    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(8, 8))
    lim = half + 5
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.set_aspect("equal", adjustable="box")
    ax.axvline(0, color="green", linestyle="--", linewidth=1)
    ax.axhline(0, color="green", linestyle="--", linewidth=1)
    draw_quadrant_labels(ax, half)
    # ориентиры зоны «крайних» положений (порог CALIB_SIDE_EPS)
    ax.axvline(+cfg.CALIB_SIDE_EPS * half, color="gray", linestyle=":", linewidth=1)
    ax.axvline(-cfg.CALIB_SIDE_EPS * half, color="gray", linestyle=":", linewidth=1)

    title_text = ax.text(
        0, lim - 8, "", color="white", fontsize=12, ha="center", va="top"
    )
    hint_text = ax.text(
        0, -lim + 8, "", color="lightgray", fontsize=10, ha="center", va="bottom"
    )
    # Сырые значения каналов s1..s4 в столбик — слева сверху.
    s_text = ax.text(
        -lim + 8,
        lim - 8,
        "",
        color="lightgray",
        fontsize=9,
        ha="left",
        va="top",
        family="monospace",
    )
    (point,) = ax.plot([0], [0], "o", markersize=12, color="white", zorder=5)

    state = {"running": True}

    def on_key(event):
        if event.key == "q":
            state["running"] = False
        elif event.key == "w":
            state["capture"] = True

    fig.canvas.mpl_connect("key_press_event", on_key)

    results: dict = {}
    try:
        for key, title, kind in _STEPS:
            print(
                f"\n[Калибровка] Шаг {key}: наведите луч — «{title}», "
                f"остановите столик и нажмите «w». (q — отмена)"
            )
            title_text.set_text(f"Сканирование {key}: {title}")
            rec = _run_step(
                rows, fig, point, hint_text, s_text, kind, adc_max, half, state
            )
            if rec is None:
                print("[Калибровка] Прервана.")
                return None
            rec["angle"] = _ask_angle(title)
            results[key] = rec
            print(
                f"  ✓ {key}: угол={rec['angle']}  x_norm={rec['x_norm']:+.3f}  s={rec['s']}"
            )
            _report_radius(results)
    finally:
        plt.ioff()
        plt.close(fig)

    path = save_calibration(results, out_dir)
    angles = {k: results[k]["angle"] for k in results}
    print(f"\n[Калибровка] Сохранено: {path}")
    print(f"[Калибровка] Углы столика: {angles}")
    return path
