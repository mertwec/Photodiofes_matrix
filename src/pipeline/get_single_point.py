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

from src.data_types import Frame, Point2D
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

SENSOR_COLS = ("s1", "s2", "s3", "s4")


def spot_radius_px(
    raw: Iterable[float], size: int,
    val_max: float, val_min: float,
) -> float | None:
    """
    Радиус пятна в пикселях по абсолютным долям засветки квадрантов.

    Поправка №1: углы v_x/v_y считаются некорректно, привязываться к ним нельзя.
    Вместо калибровки по свипу используем известные предельные значения квадранта:
        b_i = (val_min - raw_i) / (val_min - val_max),   b_i ∈ [0, 1]
    где raw = val_max (≈20) — полная засветка квадранта (b=1),
        raw = val_min (≈3500) — нет засветки (b=0).

    Модель top-hat: интенсивность пятна по площади равномерна, поэтому
    засвеченная доля детектора f = mean(b_i) равна доле его площади D² (D = size),
    покрытой пятном. Приравнивая к площади круга π·r²:

        π·r² = f·D²   ⇒   r = size·√(f/π)

    Результат клампится до 0.95·size/2, чтобы круг не вылезал за дисплей.
    Возвращает None, если диапазон некорректен или засветки нет (f = 0).
    """
    span = val_min - val_max
    if span <= 0:
        return None
    fracs = [min(1.0, max(0.0, (val_min - r) / span)) for r in raw]
    f = sum(fracs) / len(fracs)
    if f <= 0:
        return None
    r = size * math.sqrt(f / math.pi)
    return min(r, 0.95 * size / 2)


def make_point(
    rows: Iterable[dict], size: int, adc_max: float,
    val_max: float | None = None, val_min: float | None = None,
) -> Generator[Frame, None, None]:
    """
    Единый конвертер сырых строк датчиков в кадры Frame(point, v_x, v_y, radius).

    На каждом dict {s1,s2,s3,s4[, v_x, v_y]} с сырыми значениями АЦП
    (0 — max засвет, adc_max — min засвет) считает яркости как (adc_max - raw),
    собирает матрицу 2x2 в порядке модели (ph1=s1, ph2=s4, ph3=s2, ph4=s3)
    и возвращает Frame с точкой Point2D и (если есть) референсом v_x/v_y.

    Делитель S в формуле направления сокращает любой линейный масштаб яркости,
    поэтому одна и та же функция подходит и для лога (adc_max берётся из df,
    см. df_to_raw_rows), и для UART (adc_max берётся из конфига).

    val_max/val_min — предельные сырые значения квадранта (cfg.S_VAL_MAX/S_VAL_MIN).
    Если оба заданы — на каждый кадр считается радиус пятна (spot_radius_px) из
    абсолютных долей засветки s1..s4. Если хотя бы один None — пятно не рисуется
    (Frame.radius = None).
    """
    spot_on = val_max is not None and val_min is not None
    for row in rows:
        b1 = adc_max - row["s1"]
        b2 = adc_max - row["s2"]
        b3 = adc_max - row["s3"]
        b4 = adc_max - row["s4"]
        matrix = [
            [b1, b4],
            [b2, b3],
        ]
        point = light_direction_to_point(matrix, size)
        radius = None
        if spot_on:
            radius = spot_radius_px(
                (row["s1"], row["s2"], row["s3"], row["s4"]),
                size, val_max, val_min,
            )
        yield Frame(point=point, v_x=row.get("v_x"), v_y=row.get("v_y"),
                    radius=radius)


def df_to_raw_rows(df: pd.DataFrame) -> tuple[Iterable[dict], float]:
    """
    Адаптер DataFrame → (поток dict-строк, опорный adc_max).

    adc_max берётся как глобальный максимум по всем 4 датчикам в логе — это
    сохраняет относительные амплитуды между s1..s4 (см. комментарий к make_point).
    Колонки v_x, v_y пробрасываются дальше, если присутствуют в df.
    """
    adc_max = float(df[list(SENSOR_COLS)].to_numpy().max())
    extra = [c for c in ("v_x", "v_y") if c in df.columns]
    cols = list(SENSOR_COLS) + extra
    rows = (
        {col: getattr(row, col) for col in cols}
        for row in df.itertuples(index=False)
    )
    return rows, adc_max
