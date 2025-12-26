"""
Docstring для get_angle
photodiodes matrix:

ph1 | ph2
---------
ph3 | ph4

ph = [0,1] # diapazone
"""
from src.data_types import Point2D

def light_direction_to_point(matrix_pd: list[list[float]], size: int) -> Point2D | None:
    """
    Docstring для light_direction_to_point
    Преобразует матрицу фотодиодов в точку направления засветки. для матрицы 2x2.
    
    :param matrix_pd: Описание
    :type matrix_pd: list[list[float]]
    :param size: Описание
    :type size: int
    :return: Описание
    :rtype: Point2D | None
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


def light_direction_to_point_univ(matrix_pd: list[list[float]], size: int) -> Point2D | None:
    
    dimension = len(matrix_pd)

    S = 0.0
    sx = 0.0
    sy = 0.0

    for i in range(dimension):
        # y: сверху +1, снизу -1
        y = 1.0 - (2*i + 1) / dimension
        for j in range(dimension):
            # x: слева -1, справа +1
            x = -1.0 + (2*j + 1) / dimension

            w = matrix_pd[i][j]
            S += w
            sx += w * x
            sy += w * y

    if S == 0:
        return None

    # нормализованное направление [-1, +1]
    x_norm = sx / S
    y_norm = sy / S

    half = size / 2

    X = int(x_norm * half)
    Y = int(y_norm * half)

    return Point2D(X, Y)