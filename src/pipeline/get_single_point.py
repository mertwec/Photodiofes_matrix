"""
Docstring для get_angle
photodiodes matrix:

ph1 | ph4
---------
ph2 | ph3

ph = [0,1] # range value
"""

import math
from typing import Generator, Iterable

import pandas as pd
from scipy.special import erfinv

from config import cfg
from src.data_types import CompensationModel, Frame, Point2D
from src.utils.converter import format_duration_hms


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
    x_norm = (p2 + p4 - p1 - p3) / S  # вправо +
    y_norm = (p1 + p2 - p3 - p4) / S  # вверх +

    X = int(x_norm * size / 2)
    Y = int(y_norm * size / 2)

    return Point2D(X, Y)


def deflection_angles(
    x_norm: float,
    y_norm: float,
    w_mm: float,
    foc: float,
) -> tuple[float | None, float | None]:
    """
    Углы отклонения центра луча по x/y (градусы) из нормированных разностей и
    радиуса пятна.

    По нож-модели нормированная разность D (право−лево = x_norm, верх−низ =
    y_norm) связана со смещением центра d и радиусом пятна w (уровень 1/e²):

        D = erf(√2 · d / w)   ⇒   d = w · erfinv(D) / √2.

    Угол отклонения от оптической оси: θ = atan(d / FOC) (FOC — фокусное
    расстояние). Так θ зависит и от фокуса, и от радиуса пятна. Возвращает
    (None, None), если радиус/фокус неположительны.
    """
    if w_mm <= 0 or foc <= 0:
        return None, None

    def ang(d_norm: float) -> float:
        d_norm = max(-cfg.D_MAX, min(cfg.D_MAX, d_norm))
        d_mm = w_mm * float(erfinv(d_norm)) / math.sqrt(2.0)  # смещение центра, мм
        return math.degrees(math.atan(d_mm / foc))

    return ang(x_norm), ang(y_norm)


def quadrant_fracs(
    raw: Iterable[float],
    val_max: float,
    val_min: float,
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


def make_point(
    rows: Iterable[dict],
    size: int = cfg.SIZE_DISPLAY,
    adc_max: float = cfg.ADC_MAX,
    val_max: float | None = None,
    val_min: float | None = None,
    fixed_radius: float | None = None,
    comp_model: CompensationModel | None = None,
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
    Нужны ТОЛЬКО для детекции потери позиции (Задача №8): по ним считаются доли
    засветки квадрантов (quadrant_fracs) и число засвеченных nz. Если не заданы —
    детекция потери позиции отключена.

    fixed_radius (Задача №5) — источник радиуса пятна: постоянный,
    из калибровки (calib_radius.spot_radius_from_calib по CALIBRATE.json), одинаков
    для всех кадров с сигналом. Без калибровки
    radius=None — рисуется только точка, без круга (и без углов отклонения,
    т.к. для них нужен w).

    comp_model (Задача №13) — компенсационный полином углов. Если задан, в зоне
    |x_norm|,|y_norm| ≤ comp_model.d_max углы берутся из него (compensation.predict
    напрямую от x_norm/y_norm — радиус/w не нужны), а не из нож-модели. Вне зоны
    валидности экстраполировать нельзя — откат на нож-модель (нужен radius). None —
    углы только по нож-модели, как раньше.

    Потеря позиции (Задача №8): если сигнал пропал на ≥2 квадрантах
    (nz < cfg.NZ_ANGLE_MIN), угол измерить нельзя — кадр помечается lost=True,
    точка переносится на край дисплея по направлению последнего измеренного
    кадра (дисплей рисует её жёлтой, вместо углов — прочерк), круг не рисуется.
    """
    fracs_on = val_max is not None and val_min is not None
    half = size / 2
    last_dir: tuple[float, float] | None = None  # направление последнего измерения
    # Задача №13: ленивый импорт predict — иначе цикл compensation→get_single_point.
    comp_predict = None
    if comp_model is not None:
        from src.compensation import predict as comp_predict
    for row in rows:
        ts = format_duration_hms(row.get("T"))  # время кадра H:M:S из T (мс)
        s_raw = (row["s1"], row["s2"], row["s3"], row["s4"])  # для вывода на дисплей
        # Яркость = max(0, adc_max - raw). Клампим нулём: при отсутствии сигнала
        # устройство шлёт 4096 (> ADC_MAX) — без клампа это дало бы отрицательную
        # яркость и исказило бы направление в частично засвеченных кадрах.
        b1 = max(0.0, adc_max - row["s1"])
        b2 = max(0.0, adc_max - row["s2"])
        b3 = max(0.0, adc_max - row["s3"])
        b4 = max(0.0, adc_max - row["s4"])

        S = b1 + b2 + b3 + b4
        if S <= 0:
            # Сигнала нет (все датчики ≥ adc_max): красная точка в центре (0,0)
            # без окружности — это и есть визуальный признак «сигнала нет».
            yield Frame(
                point=Point2D(0, 0),
                v_x=row.get("v_x"),
                v_y=row.get("v_y"),
                radius=None,
                no_signal=True,
                ts=ts,
                s=s_raw,
            )
            continue

        matrix = [
            [b1, b4],
            [b2, b3],
        ]
        point = light_direction_to_point(matrix, size)
        # Нормированные разности (как в light_direction_to_point): это сигналы D
        # для нож-модели — нужны для углов отклонения центра.
        x_norm = (b4 + b3 - b1 - b2) / S  # право − лево
        y_norm = (b1 + b4 - b2 - b3) / S  # верх − низ

        # Засвеченность квадрантов — для детекции потери позиции (Задача №8).
        nz = None
        if fracs_on:
            fracs = quadrant_fracs(s_raw, val_max, val_min)
            if fracs is None:
                fracs_on = False  # некорректный диапазон val_max/val_min
            else:
                nz = sum(f > cfg.FRAC_EPS for f in fracs)

        if nz is not None and nz < cfg.NZ_ANGLE_MIN:
            # Задача №8: сигнал пропал на ≥2 квадрантах — угол не измерить.
            # Точка на краю дисплея по последнему измеренному направлению
            # (если его нет или оно нулевое — по текущему); дисплей рисует её
            # жёлтой, вместо углов показывает прочерк.
            dx, dy = x_norm, y_norm
            if last_dir is not None and max(abs(last_dir[0]), abs(last_dir[1])) > 0:
                dx, dy = last_dir
            m = max(abs(dx), abs(dy))
            if m > 0:
                point = Point2D(dx / m * half, dy / m * half)
            yield Frame(
                point=point,
                v_x=row.get("v_x"),
                v_y=row.get("v_y"),
                radius=None,
                lost=True,
                ts=ts,
                x_norm=x_norm,
                y_norm=y_norm,
                s=s_raw,
            )
            continue

        last_dir = (x_norm, y_norm)
        # Задача №5: радиус пятна — только постоянный, из калибровки. Без
        # CALIBRATE.json radius=None: рисуется только точка, без круга.
        radius = fixed_radius

        # Углы отклонения центра по x/y.
        angle_x = angle_y = None
        if comp_predict is not None:
            # Задача №13: полином обучен на D при опорном cfg.ADC_MAX. В log-режиме
            # adc_max = максимум лога и сместил бы шкалу D, поэтому для полинома D
            # пересчитываем по cfg.ADC_MAX (в stream это тот же adc_max). Полином
            # даёт угол напрямую из D — радиус/w не нужны.
            cb1 = max(0.0, cfg.ADC_MAX - row["s1"])
            cb2 = max(0.0, cfg.ADC_MAX - row["s2"])
            cb3 = max(0.0, cfg.ADC_MAX - row["s3"])
            cb4 = max(0.0, cfg.ADC_MAX - row["s4"])
            cS = cb1 + cb2 + cb3 + cb4
            if cS > 0:
                xn = (cb4 + cb3 - cb1 - cb2) / cS  # право − лево
                yn = (cb1 + cb4 - cb2 - cb3) / cS  # верх − низ
                # Только в зоне валидности |D| ≤ d_max — вне неё не экстраполируем.
                if abs(xn) <= comp_model.d_max and abs(yn) <= comp_model.d_max:
                    angle_x, angle_y = comp_predict(comp_model, xn, yn)
        if angle_x is None and radius is not None:
            # Откат на нож-модель (Задача №5): без полинома или вне его зоны.
            # Радиус пятна из калибровки → w в мм (зона датчика DET_SIZE_MM ↔ size).
            w_mm = radius * cfg.DET_SIZE_MM / size
            angle_x, angle_y = deflection_angles(x_norm, y_norm, w_mm, cfg.FOC)

        yield Frame(
            point=point,
            v_x=row.get("v_x"),
            v_y=row.get("v_y"),
            radius=radius,
            ts=ts,
            angle_x=angle_x,
            angle_y=angle_y,
            x_norm=x_norm,
            y_norm=y_norm,
            s=s_raw,
        )


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
        {col: getattr(row, col) for col in cols} for row in df.itertuples(index=False)
    )
    return rows, adc_max
