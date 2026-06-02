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


def make_point(
    rows: Iterable[dict], size: int, adc_max: float,
    spot_r_px: float | None = None,
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

    spot_r_px — радиус пятна в пикселях из calibrate_phi_c; если None, визуализация
    пятна отключена (Frame.radius = None).
    """
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
        yield Frame(point=point, v_x=row.get("v_x"), v_y=row.get("v_y"),
                    radius=spot_r_px)


def make_point_online(
    rows: Iterable[dict],
    size: int,
    adc_max: float,
    refit_every: int = 10,
) -> Generator[Frame, None, None]:
    """
    Как make_point, но динамически калибрует φc из входящих v_x/v_y.

    Накапливает пары (v_x, rx) / (v_y, ry) и переоценивает φc при двух триггерах:
      1. новый экстремум |rx| или |ry| (данные расширились → стоит пересчитать)
      2. каждые refit_every кадров (гарантированный периодический пересчёт)

    Пока данных < 8 или фит не сошёлся — radius=None (круг не рисуется).
    Прогресс калибровки выводится в консоль перезаписываемой строкой.
    Требует 6-польного потока (s1..s4, v_x, v_y).
    """
    from src.pipeline.calibration import fit_phi_c_from_signals

    phi_x_buf: list[float] = []
    rx_buf:    list[float] = []
    phi_y_buf: list[float] = []
    ry_buf:    list[float] = []
    S_buf:     list[float] = []

    spot_r_px: float | None = None
    rx_extreme = ry_extreme = 0.0
    frame_n = 0
    printed = False

    _EXTREMUM_DELTA = 0.02   # минимальное приращение |r| для триггера
    _MIN_POINTS     = 8      # меньше — фит нестабилен

    try:
        for row in rows:
            b1 = adc_max - row["s1"]
            b2 = adc_max - row["s2"]
            b3 = adc_max - row["s3"]
            b4 = adc_max - row["s4"]
            S  = b1 + b2 + b3 + b4

            point = light_direction_to_point([[b1, b4], [b2, b3]], size)

            if S > 0 and "v_x" in row and "v_y" in row:
                # rx/ry — те же формулы, что в light_direction_to_point
                # (ph2=b4, ph4=b3, ph1=b1, ph3=b2)
                rx_val = (b4 + b3 - b1 - b2) / S
                ry_val = (b1 + b4 - b2 - b3) / S

                phi_x_buf.append(row["v_x"])
                rx_buf.append(rx_val)
                phi_y_buf.append(row["v_y"])
                ry_buf.append(ry_val)
                S_buf.append(S)

                new_rx = abs(rx_val) > rx_extreme + _EXTREMUM_DELTA
                new_ry = abs(ry_val) > ry_extreme + _EXTREMUM_DELTA
                if new_rx: rx_extreme = abs(rx_val)
                if new_ry: ry_extreme = abs(ry_val)

                periodic = (frame_n % refit_every == 0)

                if (new_rx or new_ry or periodic) and len(phi_x_buf) >= _MIN_POINTS:
                    S_arr = np.array(S_buf)
                    calib = fit_phi_c_from_signals(
                        np.array(phi_x_buf), np.array(rx_buf),
                        np.array(phi_y_buf), np.array(ry_buf),
                        sn=S_arr / S_arr.max(),
                    )
                    if calib:
                        new_r = min(
                            calib.spot_r_px(size),
                            0.9 * size / 2,
                        )
                        if new_r != spot_r_px:
                            spot_r_px = new_r
                            print(
                                f"\r[online-fit] N={len(phi_x_buf):4d}  "
                                f"φc={calib.phi_c:.2f}  "
                                f"r_px={spot_r_px:.1f}  "
                                f"range={calib.phi_range:.1f}      ",
                                end="", flush=True,
                            )
                            printed = True

            yield Frame(
                point=point,
                v_x=row.get("v_x"),
                v_y=row.get("v_y"),
                radius=spot_r_px,
            )
            frame_n += 1
    finally:
        if printed:
            print()  # завершить строку после \r-обновлений


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
