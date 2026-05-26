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
    rows: Iterable[dict], size: int, adc_max: float
) -> Generator[Frame, None, None]:
    """
    Единый конвертер сырых строк датчиков в кадры Frame(point, v_x, v_y).

    На каждом dict {s1,s2,s3,s4[, v_x, v_y]} с сырыми значениями АЦП
    (0 — max засвет, adc_max — min засвет) считает яркости как (adc_max - raw),
    собирает матрицу 2x2 в порядке модели (ph1=s1, ph2=s4, ph3=s2, ph4=s3)
    и возвращает Frame с точкой Point2D и (если есть) референсом v_x/v_y.

    Делитель S в формуле направления сокращает любой линейный масштаб яркости,
    поэтому одна и та же функция подходит и для лога (adc_max берётся из df,
    см. df_to_raw_rows), и для UART (adc_max берётся из конфига).
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
        yield Frame(point=point, v_x=row.get("v_x"), v_y=row.get("v_y"))


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
