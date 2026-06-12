"""
Режим фиксации данных (Задача №7).

Поток данных отображается как в stream (live-точка направления засветки), но
БЕЗ окружности пятна. Точки измерения фиксируются вручную с клавиатуры:

  • «w» — зафиксировать значения квадрантов s1..s4 из кадра, пришедшего в
    момент нажатия, и в ОТДЕЛЬНОМ потоке запросить в терминале углы по x и y
    (input). Точка кладётся в словарь под ключом i0, i1, … (по порядку
    нажатий) и, как только приняты ОБА угла, словарь сразу сохраняется в
    DATA/MEASURE/MEASURE.json (автосохранение). После этого сбрасывается
    входной буфер COM-порта (flush_event): пока оператор вводил углы, буфер
    копился — дальше читаем то, что приходит сейчас, а не хвост буфера.
  • «s» — сохранить накопленный словарь вручную (дублирует автосохранение).
  • «q» — выход.

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


def _ask_angle(axis: str) -> float:
    """Запросить в терминале угол по оси axis (град)."""
    while True:
        ans = input(f"{axis}: ").strip().replace(",", ".")
        try:
            return float(ans)
        except ValueError:
            print("  Нужно число, например 2.0 или -2.0")


def save_measure(points: dict, out_dir: Path | str) -> Path:
    """
    Сохранить накопленные точки в DATA/MEASURE/MEASURE.json. Возвращает путь.

    Формат (см. TASK.md, Задача №7): {created, fov, points: {i0: {s, angle_x,
    angle_y}, …}}. s — усреднённые сырые значения квадрантов s1..s4.
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "MEASURE.json"
    payload = {"created": ts, "fov": cfg.FOC, "points": points}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _set_point_color(point, color: str) -> None:
    point.set_markerfacecolor(color)
    point.set_markeredgecolor(color)


def run_measure(
    rows,
    size: int,
    out_dir: Path | str,
    flush_event: threading.Event | None = None,
) -> None:
    """
    Интерактивный режим фиксации данных.

    :param rows: генератор строк датчиков (read_serial_rows).
    :param size: размер дисплея, px.
    :param out_dir: каталог для MEASURE.json.
    :param flush_event: событие сброса входного буфера UART (read_serial_rows);
        взводится после завершения ввода углов, чтобы дальше читать текущие
        данные, а не накопившийся за время ввода буфер. None — нет порта (--test).
    """
    half = size / 2
    plt.ion()
    plt.style.use("dark_background")
    # 's' — дефолтный хоткей matplotlib «сохранить фигуру»; освобождаем его под
    # наше сохранение (ctrl+s у matplotlib остаётся).
    plt.rcParams["keymap.save"] = [
        k for k in plt.rcParams.get("keymap.save", []) if k != "s"
    ]

    fig, ax = plt.subplots(figsize=(7, 7))
    lim = half + 5
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.set_aspect("equal", adjustable="box")
    ax.axvline(0, color="green", linestyle="--", linewidth=1)
    ax.axhline(0, color="green", linestyle="--", linewidth=1)
    ax.text(
        0,
        lim - 4,
        "measure   w: фиксация+автосохранение   s: сохранить   q: выход",
        color="white",
        fontsize=10,
        ha="center",
        va="top",
    )
    info = ax.text(
        -lim + 4, -lim + 4, "", color="lightgray", fontsize=9, ha="left", va="bottom"
    )
    (point,) = ax.plot([0], [0], "o", markersize=8, color="white", zorder=5)

    latest: list = []  # сырые s1..s4 последнего пришедшего кадра
    points: dict = {}
    lock = threading.Lock()
    state = {"running": True, "capturing": False, "msg": "ожидание данных…"}

    def _capture(s_vals: list[float]) -> None:
        """
        Фоновый поток: запросить углы x/y, записать точку в словарь и сразу
        сохранить файл (автосохранение — как только приняты оба значения).
        """
        try:
            angle_x = _ask_angle("x")
            angle_y = _ask_angle("y")
            with lock:
                key = f"i{len(points)}"
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
        elif event.key == "w":
            if state["capturing"]:
                print("  Уже идёт ввод углов — завершите его в терминале.")
                return
            if not latest:
                print("  Нет данных для фиксации.")
                return
            # Берём s1..s4 из кадра, пришедшего к моменту нажатия «w» (без усреднения).
            s_vals = latest
            state["capturing"] = True
            state["msg"] = "введите углы x, y в терминале…"
            print(f"\n[Фиксация] s={s_vals} — введите углы:")
            threading.Thread(target=_capture, args=(s_vals,), daemon=True).start()
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
            latest = s  # запоминаем последний кадр для фиксации по «w»
            point.set_data([x_px], [y_px])
            # Во время ввода углов точка зелёная — индикатор, что кадр зафиксирован.
            _set_point_color(point, "lime" if state["capturing"] else "white")
            info.set_text(f"точек: {len(points)}   {state['msg']}")
            fig.canvas.draw_idle()
            fig.canvas.flush_events()
            time.sleep(0.01)
    finally:
        plt.ioff()
        plt.close(fig)
