"""
Docstring для get_angle
photodiodes matrix:

ph1 | ph2
---------
ph3 | ph4

ph = [0,1] # diapazone
"""
from src.data_types import Point2D


def light_direction_to_point(matrix_pd:list[list[float]], size:int) -> Point2D | None:
    p1, p2, p3, p4 = matrix_pd[0][0], matrix_pd[0][1], matrix_pd[1][0], matrix_pd[1][1]
    S = p1 + p2 + p3 + p4
    
    if S == 0:
        return None  

    x = (p2 + p4 - p1 - p3) / S
    y = (p1 + p2 - p3 - p4) / S

    X = int((x + 1) * 0.5 * (size - 1))
    Y = int((1 - y) * 0.5 * (size - 1))

    return Point2D(X, Y)
