"""
Геометрическая оценка радиуса засвечиваемого пятна по 4 площадям пересечения
с квадрантами детектора (обратная задача 3D).

Источник: DOCUMENTATION/r2_estimation_algorithm.pdf — «Алгоритм оценки радиуса
перемещаемой окружности по площадям пересечения с квадрантами» (см. также
AI_ANSWER.md, Поправка №2).

Модель: детектор — круг C1 радиуса R1=1, разбитый осями на 4 квадранта;
пятно — круг C2 с центром (x, y) и радиусом R2. По измеренным площадям
пересечения A1..A4 (квадранты Q1 верх-право, Q2 верх-лево, Q3 низ-лево,
Q4 низ-право) совместно ищутся (x, y, R2): переопределённая система
(4 уравнения, 3 неизвестных) решается МНК методом Нелдера–Мида в R^3.

Почему радиус нельзя взять из суммы площадей: при смещении центра часть пятна
уходит за край детектора, и A_tot < π·R2² — формула √(A_tot/π) занижает R2.
R2 определяется только совместным фитом всех 4 площадей: изменение R2 меняет и
суммарную площадь, и её распределение по квадрантам (∂A/∂R2 линейно независим
от ∂A/∂x, ∂A/∂y — ранг якобиана 3).
"""

import math

import numpy as np
from scipy.optimize import minimize

from config import cfg

# Сетка многостарта (PDF, стр. 8): 9 позиций × 4 радиуса + аналитический старт.
_SXY = ((0.0, 0.0), (0.7, 0.7), (-0.7, 0.7), (-0.7, -0.7), (0.7, -0.7),
        (1.2, 0.0), (0.0, 1.2), (-1.2, 0.0), (0.0, -1.2))
_SR2 = (0.3, 0.5, 0.7, 0.9)


def forward_areas(
    x: float, y: float, R2: float, R1: float = 1.0, N: int | None = None,
) -> np.ndarray:
    """
    Прямая задача: площади пересечения круга (x, y, R2) с 4 квадрантами круга R1.

    Метод средних прямоугольников по горизонтальным полосам (правило средней
    точки убирает ложную асимметрию, когда узел сетки попадает на границу y=0).
    Векторизовано по полосам через numpy.

    :return: np.array([A_Q1, A_Q2, A_Q3, A_Q4]) =
             [верх-право, верх-лево, низ-лево, низ-право] в единицах R1=1.
    """
    if N is None:
        N = cfg.N_INT
    A = np.zeros(4)
    y_lo = max(y - R2, -R1)
    y_hi = min(y + R2, R1)
    if y_hi <= y_lo:
        return A                                        # нет пересечения по вертикали

    h = (y_hi - y_lo) / N
    yy = y_lo + (np.arange(N) + 0.5) * h                # середины полос
    aa = np.sqrt(np.clip(R1 * R1 - yy * yy, 0.0, None)) # полуширина детектора C1
    d2 = R2 * R2 - (yy - y) ** 2
    b = np.sqrt(np.clip(d2, 0.0, None))                 # полуширина пятна C2
    xL = np.maximum(x - b, -aa)
    xR = np.minimum(x + b, aa)
    seg = (d2 > 0.0) & (xR > xL)
    upper = yy >= 0.0

    # правая половина полосы (x>0): Q1 если верх, иначе Q4
    right = seg & (xR > 0.0)
    wr = (xR - np.maximum(xL, 0.0)) * h
    A[0] = np.sum(wr[right & upper])
    A[3] = np.sum(wr[right & ~upper])

    # левая половина полосы (x<0): Q2 если верх, иначе Q3
    left = seg & (xL < 0.0)
    wl = (np.minimum(xR, 0.0) - xL) * h
    A[1] = np.sum(wl[left & upper])
    A[2] = np.sum(wl[left & ~upper])
    return A


def _make_residual(A_meas: np.ndarray):
    """Целевая функция МНК F(x, y, R2) с клампом R2 в физический диапазон."""
    lo, hi = cfg.R2_CLIP

    def F(p) -> float:
        x, y, R2 = p
        if not (lo < R2 <= hi):
            return 1e6                                  # вне допустимого диапазона
        return float(np.sum((forward_areas(x, y, R2) - A_meas) ** 2))

    return F


def solve_xyr2(
    A_meas, warm: tuple[float, float, float] | None = None,
) -> tuple[float, float, float, float]:
    """
    Обратная задача: по 4 площадям [A_Q1, A_Q2, A_Q3, A_Q4] найти (x, y, R2).

    :param A_meas: измеренные площади квадрантов в единицах R1=1.
    :param warm: старт от решения предыдущего кадра (x, y, R2). Если он даёт
                 остаток < cfg.F_RELIABLE, многостарт пропускается (быстрый путь
                 для потока: пятно меняется плавно).
    :return: (x, y, R2, F), где F — остаток МНК. При F > cfg.F_RELIABLE оценку
             следует считать ненадёжной.
    """
    A_meas = np.asarray(A_meas, dtype=float)
    F = _make_residual(A_meas)
    opts = {"xatol": 1e-6, "fatol": cfg.NM_FATOL, "maxiter": cfg.NM_MAXITER}

    best = None
    # Быстрый путь: один старт от прошлого кадра. Принимаем сразу, если фит хорош.
    if warm is not None:
        r = minimize(F, list(warm), method="Nelder-Mead", options=opts)
        if r.fun < cfg.F_RELIABLE:
            x, y, R2 = r.x
            return float(x), float(y), float(R2), float(r.fun)
        best = r

    # Аналитическое приближение (PDF, стр. 7) + сетка многостарта (стр. 8).
    A1, A2, A3, A4 = A_meas
    A_tot = float(A_meas.sum())
    r2_0 = (min(0.95, max(0.05, 1.2 * math.sqrt(A_tot / math.pi)))
            if A_tot > 0 else 0.5)
    p0 = [1.5 * ((A1 + A4) - (A2 + A3)),    # x0: право − лево
          1.5 * ((A1 + A2) - (A3 + A4)),    # y0: верх − низ
          r2_0]
    starts = [p0] + [[sx, sy, sr] for sx, sy in _SXY for sr in _SR2]

    for s in starts:
        r = minimize(F, s, method="Nelder-Mead", options=opts)
        if best is None or r.fun < best.fun:
            best = r
        if best.fun < cfg.NM_FATOL:                     # глобальный минимум найден
            break

    # Финальное доуточнение из лучшего старта малым симплексом.
    best = minimize(F, best.x, method="Nelder-Mead", options=opts)
    x, y, R2 = best.x
    return float(x), float(y), float(R2), float(best.fun)
