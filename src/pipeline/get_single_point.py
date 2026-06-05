"""
Docstring для get_angle
photodiodes matrix in model:

ph1 | ph2
---------
ph3 | ph4


photodiodes matrix in real:
s1 | s4
s2 | s3

ph = [0,1] # range value
"""

import math
from typing import Any, Generator, Iterable

import numpy as np

from config import cfg
from src.data_types import Frame, Point2D
from src.pipeline.spot_geometry import solve_xyr2
import pandas as pd




def light_direction_to_point(matrix_pd: list[list[float]], size: int) -> Point2D | None:
    """
    Docstring для light_direction_to_point
    Преобразует матрицу фотодиодов в точку направления засветки. для матрицы 2x2.
    
    :param matrix_pd: Описание
    :param size: размер окна визуализации
    :rtype: Point2D | координаты точки визуализации
    """

    p1, p2 = matrix_pd[0]
    p3, p4 = matrix_pd[1]

    S = p1 + p2 + p3 + p4
    if S == 0:
        return None

    # нормализованное направление [-1, +1]
    x_norm = (p2 + p4 - p1 - p3) / S   # вправо +
    y_norm = (p1 + p2 - p3 - p4) / S   # вверх +

    X = int(x_norm * size / 2)
    Y = int(y_norm * size / 2)

    return Point2D(X, Y)




def format_duration_hms(t) -> str | None:
    """
    Время кадра из T в формате H:M:S.

    T — детекторное время в миллисекундах (счётчик от старта устройства),
    приходит int (лог) или строкой (UART, напр. '06800606'). Переводим в
    длительность: T/1000 секунд → ЧЧ:ММ:СС. Возвращает None, если T нет/не число.
    """
    if t is None:
        return None
    try:
        total_s = int(float(t)) // 1000
    except (TypeError, ValueError):
        return None
    h, rem = divmod(total_s, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def quadrant_fracs(
    raw: Iterable[float], val_max: float, val_min: float,
) -> list[float] | None:
    """
    Абсолютные доли засветки квадрантов b_i ∈ [0, 1] из сырых значений.

        b_i = clip((val_min - raw_i) / (val_min - val_max), 0, 1)
    где raw = val_max (≈20) — полная засветка квадранта (b=1),
        raw = val_min (≈3500) — нет засветки (b=0).

    Возвращает None, если диапазон некорректен (val_min ≤ val_max).
    """
    span = val_min - val_max
    if span <= 0:
        return None
    return [min(1.0, max(0.0, (val_min - r) / span)) for r in raw]


def spot_radius_px_fallback(fracs: list[float], size: int) -> float | None:
    """
    Грубая оценка радиуса пятна по сумме засветки (top-hat) — ФОЛБЭК для nz < 2.

    Геометрический решатель (solve_xyr2) требует ≥ 2 засвеченных квадрантов;
    при nz < 2 задача вырождена. Тогда показываем приблизительный радиус из
    суммарной доли f = mean(b_i), приравнивая засвеченную площадь к кругу:

        π·r² = f·size²   ⇒   r = size·√(f/π)

    Эта оценка занижает радиус при смещении пятна, поэтому такой кадр помечается
    как ненадёжный (круг рисуется серым). Клампится до 0.95·size/2; None при f=0.
    """
    f = sum(fracs) / len(fracs)
    if f <= 0:
        return None
    return min(size * math.sqrt(f / math.pi), 0.95 * size / 2)


def make_point(
    rows: Iterable[dict], size: int, adc_max: float,
    val_max: float | None = None, val_min: float | None = None,
) -> Generator[Frame, None, None]:
    """
    Единый конвертер сырых строк датчиков в кадры Frame(point, v_x, v_y, radius).

    На каждом dict {s1,s2,s3,s4[, v_x, v_y]} с сырыми значениями АЦП
    (0 — max засвет, adc_max — min засвет) считает яркости как max(0, adc_max - raw),
    собирает матрицу 2x2 в порядке модели (ph1=s1, ph2=s4, ph3=s2, ph4=s3)
    и возвращает Frame с точкой Point2D и (если есть) референсом v_x/v_y.

    Если сигнала нет (все датчики ≥ adc_max, устройство шлёт 4096), суммарная
    яркость = 0 и кадр получает point=Point2D(0, 0), radius=None — точка в центре
    без окружности как признак «нет сигнала».

    Делитель S в формуле направления сокращает любой линейный масштаб яркости,
    поэтому одна и та же функция подходит и для лога (adc_max берётся из df,
    см. df_to_raw_rows), и для UART (adc_max берётся из конфига).

    val_max/val_min — предельные сырые значения квадранта (cfg.S_VAL_MAX/S_VAL_MIN).
    Если оба заданы — радиус пятна считается геометрическим решателем (Поправка №2):
    из долей засветки s1..s4 строятся 4 площади пересечения с квадрантами детектора
    (R1=1) и совместно фитятся (x, y, R2) методом Нелдера–Мида (solve_xyr2). Радиус
    в пиксели: r_px = R2·size/2. Решатель «тёпло» стартует от прошлого кадра.

    Достоверность: при nz < 2 засвеченных квадрантов задача вырождена — берётся
    грубый фолбэк по сумме (spot_radius_px_fallback); при остатке F > cfg.F_RELIABLE
    фит ненадёжен. В обоих случаях Frame.spot_reliable=False (дисплей рисует круг
    серым). Если val_max/val_min не заданы — пятно не рисуется (radius=None).
    """
    spot_on = val_max is not None and val_min is not None
    half = size / 2
    warm: tuple[float, float, float] | None = None  # тёплый старт между кадрами
    for row in rows:
        ts = format_duration_hms(row.get("T"))  # время кадра H:M:S из T (мс)
        # Яркость = max(0, adc_max - raw). Клампим нулём: при отсутствии сигнала
        # устройство шлёт 4096 (> ADC_MAX) — без клампа это дало бы отрицательную
        # яркость и исказило бы направление в частично засвеченных кадрах.
        b1 = max(0.0, adc_max - row["s1"])
        b2 = max(0.0, adc_max - row["s2"])
        b3 = max(0.0, adc_max - row["s3"])
        b4 = max(0.0, adc_max - row["s4"])

        if b1 + b2 + b3 + b4 <= 0:
            # Сигнала нет (все датчики ≥ adc_max): красная точка в центре (0,0)
            # без окружности — это и есть визуальный признак «сигнала нет».
            warm = None
            yield Frame(point=Point2D(0, 0), v_x=row.get("v_x"),
                        v_y=row.get("v_y"), radius=None, no_signal=True, ts=ts)
            continue

        matrix = [
            [b1, b4],
            [b2, b3],
        ]
        point = light_direction_to_point(matrix, size)
        radius = None
        reliable = True
        if spot_on:
            fracs = quadrant_fracs(
                (row["s1"], row["s2"], row["s3"], row["s4"]), val_max, val_min,
            )
            if fracs is None:
                spot_on = False  # некорректный диапазон val_max/val_min
            else:
                f1, f2, f3, f4 = fracs
                nz = sum(f > cfg.FRAC_EPS for f in fracs)
                if nz >= 2:
                    # Площади квадрантов PDF (Q1 верх-право, Q2 верх-лево,
                    # Q3 низ-лево, Q4 низ-право) по раскладке ph↔s:
                    # ph2=s4, ph1=s1, ph3=s2, ph4=s3. Полный квадрант = π/4.
                    q = math.pi / 4.0
                    a_meas = (q * f4, q * f1, q * f2, q * f3)
                    x, y, r2, fres = solve_xyr2(a_meas, warm=warm)
                    warm = (x, y, r2)
                    radius = min(r2 * half, 0.95 * half)
                    reliable = fres <= cfg.F_RELIABLE
                else:
                    # nz < 2 — задача вырождена: грубый фолбэк, кадр ненадёжен.
                    warm = None
                    radius = spot_radius_px_fallback(fracs, size)
                    reliable = False
        yield Frame(point=point, v_x=row.get("v_x"), v_y=row.get("v_y"),
                    radius=radius, spot_reliable=reliable, ts=ts)


def df_to_raw_rows(df: pd.DataFrame) -> tuple[Iterable[dict], float]:
    """
    Адаптер DataFrame → (поток dict-строк, опорный adc_max).

    adc_max берётся как глобальный максимум по всем 4 датчикам в логе — это
    сохраняет относительные амплитуды между s1..s4 (см. комментарий к make_point).
    Колонки v_x, v_y пробрасываются дальше, если присутствуют в df.
    """
    adc_max = float(df[list(cfg.SENSOR_COLS)].to_numpy().max())
    extra = [c for c in ("T", "v_x", "v_y") if c in df.columns]
    cols = list(cfg.SENSOR_COLS) + extra
    rows = (
        {col: getattr(row, col) for col in cols}
        for row in df.itertuples(index=False)
    )
    return rows, adc_max
