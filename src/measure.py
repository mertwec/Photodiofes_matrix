"""
Режим фиксации данных (Задача №7).

Поток данных отображается как в stream (live-точка направления засветки), но
БЕЗ окружности пятна. Точки измерения фиксируются вручную с клавиатуры:

  • «g» — усреднить значения квадрантов s1..s4 по следующим cfg.MEASURE_HOLD
    кадрам (тем же average_s, что и калибровка) и в ОТДЕЛЬНОМ потоке запросить
    в терминале углы по x и y (input). Точка кладётся в словарь под следующим
    свободным ключом i0, i1, … и, как только приняты ОБА угла, ВЕСЬ словарь
    сразу сохраняется в DATA/MEASURE/MEASURE.json (автосохранение). После
    этого сбрасывается входной буфер COM-порта (flush_event): пока оператор
    вводил углы, буфер копился — дальше читаем то, что приходит сейчас, а не
    хвост буфера.
  • «s» — сохранить накопленный словарь вручную (дублирует автосохранение).
  • «q» — выход.

С флагом --continue (run_measure(cont=True)) при старте подгружаются уже снятые
точки из MEASURE.json — нумерация и запись продолжаются, файл дополняется. Без
флага сессия начинается с нуля (первое сохранение перезапишет старый файл).

Почему ввод в отдельном потоке: input() блокирует. Окно matplotlib продолжает
крутиться в главном потоке, поэтому live-точка не подвисает, пока пользователь
печатает углы в терминале. ВАЖНО: matplotlib не потокобезопасен — из фонового
потока его не трогаем; поток только спрашивает input(), пишет в словарь и файл
под локом и взводит flush_event.
"""

import json
import threading
import time
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt

from config import cfg
from src.calibration import average_s
from src.utils.converter import deg_to_dm, dm_to_deg
from src.visualization.display import draw_quadrant_labels


def _read_point(row: dict, half: float) -> tuple[tuple[float, ...], float, float]:
    """
    Строка датчиков → (кортеж сырых s1..s4, x_px, y_px) для отрисовки live-точки.

    Направление считается как в light_direction_to_point / калибровке: яркость
    b = max(0, ADC_MAX - raw), нормированные разности право−лево / верх−низ с той
    же раскладкой ph↔s, что и в make_point.
    """
    s = (float(row["s1"]), float(row["s2"]), float(row["s3"]), float(row["s4"]))
    b1, b2, b3, b4 = (max(0.0, cfg.ADC_MAX - v) for v in s)
    P = b1 + b2 + b3 + b4
    if P > 0:
        x_norm = (b4 + b3 - b1 - b2) / P  # право − лево
        y_norm = (b1 + b4 - b2 - b3) / P  # верх − низ
    else:
        x_norm = y_norm = 0.0
    return s, x_norm * half, y_norm * half


def _ask_angle(axis: str) -> str:
    """
    Запросить в терминале угол по оси axis в записи «градусы.минуты» (DD.MM).

    Оператор вводит float, где целая часть — градусы, дробная — угловые минуты
    (0.20 = 0°20', -1.40 = -1°40', 1.5 = 1°50'). Возвращается канонизированная
    строка DD.MM — в том же виде угол лежит в MEASURE.json; при построении
    полинома dm_to_deg переводит её в настоящие градусы (см. compensation.py).
    """
    hint = "  Нужно число «градусы.минуты», например 0.20 (=0°20') или -1.40"
    while True:
        ans = input(f"{axis} (град.мин): ").strip().replace(",", ".")
        if not ans:
            print(hint)
            continue
        try:
            return deg_to_dm(dm_to_deg(ans))
        except ValueError:
            print(hint)


def save_measure(points: dict, out_dir: Path | str) -> Path:
    """
    Сохранить накопленные точки в DATA/MEASURE/MEASURE.json. Возвращает путь.

    Формат (см. TASK.md, Задача №7): {created, fov, points: {i0: {s, angle_x,
    angle_y}, …}}. s — усреднённые сырые значения квадрантов s1..s4. angle_x/
    angle_y — строки в записи «градусы.минуты» (DD.MM, напр. "0.20" = 0°20');
    в градусы их переводит converter.dm_to_deg (см. compensation.points_to_arrays).
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "MEASURE.json"
    payload = {"created": ts, "fov": cfg.FOC, "points": points}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_measure(out_dir: Path | str) -> dict:
    """Прочитать ранее снятые точки из MEASURE.json (для --continue). {} если файла нет."""
    path = Path(out_dir) / "MEASURE.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("points", {})


def _next_key(points: dict) -> str:
    """Следующий свободный ключ iN (устойчив к продолжению и пропускам ключей)."""
    n = len(points)
    while f"i{n}" in points:
        n += 1
    return f"i{n}"


def _set_point_color(point, color: str) -> None:
    point.set_markerfacecolor(color)
    point.set_markeredgecolor(color)


def run_measure(
    rows,
    size: int,
    out_dir: Path | str,
    flush_event: threading.Event | None = None,
    cont: bool = False,
) -> None:
    """
    Интерактивный режим фиксации данных.

    :param rows: генератор строк датчиков (read_serial_rows).
    :param size: размер дисплея, px.
    :param out_dir: каталог для MEASURE.json.
    :param flush_event: событие сброса входного буфера UART (read_serial_rows);
        взводится после завершения ввода углов, чтобы дальше читать текущие
        данные, а не накопившийся за время ввода буфер. None — нет порта (--test).
    :param cont: --continue — подгрузить уже снятые точки из MEASURE.json и
        продолжить запись (нумерация и содержимое сохраняются). False — с нуля.
    """
    half = size / 2
    plt.ion()
    plt.style.use("dark_background")
    # 's' — дефолтный хоткей matplotlib «сохранить фигуру»; освобождаем его под
    # наше сохранение (ctrl+s у matplotlib остаётся).
    plt.rcParams["keymap.save"] = [
        k for k in plt.rcParams.get("keymap.save", []) if k != "s"
    ]
    # 'g' — наш хоткей записи; снимаем дефолтную matplotlib-сетку с 'g'.
    plt.rcParams["keymap.grid"] = [
        k for k in plt.rcParams.get("keymap.grid", []) if k != "g"
    ]

    fig, ax = plt.subplots(figsize=(7, 7))
    lim = half + 5
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.set_aspect("equal", adjustable="box")
    ax.axvline(0, color="green", linestyle="--", linewidth=1)
    ax.axhline(0, color="green", linestyle="--", linewidth=1)
    draw_quadrant_labels(ax, half)
    ax.text(
        0,
        lim - 4,
        "measure   g: фиксация+автосохранение   s: сохранить   q: выход",
        color="white",
        fontsize=10,
        ha="center",
        va="top",
    )
    info = ax.text(
        -lim + 4, -lim + 4, "", color="lightgray", fontsize=9, ha="left", va="bottom"
    )
    # Сырые значения каналов s1..s4 в столбик — слева сверху.
    s_text = ax.text(
        -lim + 4,
        lim - 10,
        "",
        color="lightgray",
        fontsize=9,
        ha="left",
        va="top",
        family="monospace",
    )
    (point,) = ax.plot([0], [0], "o", markersize=8, color="white", zorder=5)

    latest: list = []  # сырые s1..s4 последнего пришедшего кадра
    accum: list = []   # буфер усреднения s1..s4 по cfg.MEASURE_HOLD кадрам после «g»
    # --continue: продолжаем уже снятый MEASURE.json (нумерация и запись с конца).
    points: dict = load_measure(out_dir) if cont else {}
    if cont:
        print(
            f"[measure] --continue: загружено точек {len(points)} из MEASURE.json"
            if points
            else "[measure] --continue: прежних точек нет — начинаем с нуля"
        )
    lock = threading.Lock()
    # capturing — идёт ввод углов в терминале; pending — идёт усреднение кадров.
    state = {
        "running": True,
        "capturing": False,
        "pending": False,
        "msg": "ожидание данных…",
    }

    def _capture(s_vals: list[float]) -> None:
        """
        Фоновый поток: запросить углы x/y, записать точку в словарь и сразу
        сохранить файл (автосохранение — как только приняты оба значения).
        """
        try:
            angle_x = _ask_angle("x")
            angle_y = _ask_angle("y")
            with lock:
                key = _next_key(points)
                points[key] = {"s": s_vals, "angle_x": angle_x, "angle_y": angle_y}
                n = len(points)
                path = save_measure(points, out_dir)
            print(f"  ✓ {key}: s={s_vals}  angle_x={angle_x}  angle_y={angle_y}")
            print(f"  [Сохранено] {path}  (точек: {n})")
            state["msg"] = f"{key} сохранено: {path.name} (точек: {n})"
        finally:
            # Пока вводились углы, UART копился в буфере — сбрасываем его,
            # чтобы дальше читать текущие данные (в т.ч. при отмене ввода).
            if flush_event is not None:
                flush_event.set()
            state["capturing"] = False

    def on_key(event) -> None:
        if event.key == "q":
            state["running"] = False
        elif event.key == "z":
            if state["capturing"] or state["pending"]:
                print("  Уже идёт фиксация — дождитесь её завершения.")
                return
            if not latest:
                print("  Нет данных для фиксации.")
                return
            # Запускаем усреднение: следующие cfg.MEASURE_HOLD кадров копятся в
            # accum (в главном цикле), затем поток _capture спросит углы по
            # усреднённому s. Держите луч неподвижно, пока идёт захват.
            accum.clear()
            state["pending"] = True
            state["msg"] = f"усреднение {cfg.MEASURE_HOLD} кадров…"
            print(f"\n[Фиксация] усреднение {cfg.MEASURE_HOLD} кадров — держите луч…")
        elif event.key == "s":
            with lock:
                if not points:
                    print("  Нечего сохранять.")
                    return
                path = save_measure(points, out_dir)
                n = len(points)
            print(f"\n[Сохранено] {path}  (точек: {n})")
            state["msg"] = f"сохранено: {path.name} (точек: {n})"

    fig.canvas.mpl_connect("key_press_event", on_key)

    try:
        for row in rows:
            if not state["running"] or not plt.fignum_exists(fig.number):
                break
            s, x_px, y_px = _read_point(row, half)
            latest = s  # запоминаем последний кадр для фиксации по «g»
            # Усреднение по cfg.MEASURE_HOLD кадрам после «g» (переиспользуем
            # average_s из калибровки): копим кадры, по достижении порога стартуем
            # поток ввода углов с усреднённым s.
            if state["pending"]:
                accum.append(s)
                state["msg"] = f"усреднение {len(accum)}/{cfg.MEASURE_HOLD} кадров…"
                if len(accum) >= cfg.MEASURE_HOLD:
                    s_avg = average_s(accum)
                    accum.clear()
                    state["pending"] = False
                    state["capturing"] = True
                    state["msg"] = "введите углы x, y в терминале…"
                    print(f"[Фиксация] s={s_avg} — введите углы:")
                    threading.Thread(target=_capture, args=(s_avg,), daemon=True).start()
            point.set_data([x_px], [y_px])
            s_text.set_text("\n".join(f"s{i} = {v:.0f}" for i, v in enumerate(s, 1)))
            # Точка зелёная во время усреднения/ввода углов — кадр(ы) фиксируются.
            _set_point_color(
                point, "lime" if (state["capturing"] or state["pending"]) else "white"
            )
            info.set_text(f"точек: {len(points)}   {state['msg']}")
            fig.canvas.draw_idle()
            fig.canvas.flush_events()
            time.sleep(0.01)
    finally:
        plt.ioff()
        plt.close(fig)
