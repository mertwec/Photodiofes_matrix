"""
Базовые функции компенсационного полинома (Задача №13).

Алгоритм — из DOCUMENTATION/AI_COMPENSATION.md (§12) и AI_POLINOME_CALIB.md (§11):

    сырые s1..s4 ─► нормированные разности Dx, Dy (раскладка ph↔s как в make_point)
                 ─► базис u = erfinv(clip(D, ±d_max))   (нож-модель почти линейна по u)
                 ─► МНК полином полной степени `degree` (6 коэф при degree=2)
                    ОТДЕЛЬНО по осям θx, θy
                 ─► честная ошибка = leave-one-out RMSE (диагональ hat-матрицы)

Модуль НЕ пишет в файлы и НЕ печатает (это делают src/pipeline/poly_compensation.py
и cli_model.py) — здесь только вычисления. Возвращает CompensationModel + info.
"""

import math

import numpy as np
from scipy.special import erfinv

from config import cfg
from src.data_types import CompensationModel
from src.pipeline.get_single_point import quadrant_fracs
from src.utils.converter import dm_to_deg


# --- базис и дизайн-матрица ---------------------------------------------------

def poly_terms(degree: int) -> list[tuple[int, int]]:
    """Мономы полной степени ≤ degree в фиксированном порядке (p — степень u_x).

    degree=2 → [(0,0),(0,1),(0,2),(1,0),(1,1),(2,0)] = [1, u_y, u_y², u_x, u_x·u_y, u_x²].
    Тот же порядок зашит в CompensationModel.to_dict (ключ "terms") и в predict.
    """
    return [(p, q) for p in range(degree + 1) for q in range(degree + 1 - p)]


def n_coef(degree: int) -> int:
    """Число коэффициентов полного 2D-полинома степени degree: (n+1)(n+2)/2."""
    return (degree + 1) * (degree + 2) // 2


def erfinv_basis(dx, dy, d_max: float):
    """(Dx, Dy) → (u_x, u_y) = erfinv(clip(D, ±d_max)). Скаляр или массив."""
    ux = erfinv(np.clip(dx, -d_max, d_max))
    uy = erfinv(np.clip(dy, -d_max, d_max))
    return ux, uy


def design_matrix(ux, uy, degree: int) -> np.ndarray:
    """Матрица плана V[i, k] = u_x^p · u_y^q по poly_terms(degree). Форма (N, k)."""
    ux = np.atleast_1d(np.asarray(ux, dtype=float))
    uy = np.atleast_1d(np.asarray(uy, dtype=float))
    cols = [ux**p * uy**q for (p, q) in poly_terms(degree)]
    return np.column_stack(cols)


# --- сигнал из сырых s --------------------------------------------------------

def diffs_from_s(s, adc_max: float | None = None):
    """
    Сырые s1..s4 → (Dx, Dy, P). Последняя ось массива s — это (s1, s2, s3, s4).

    Формула совпадает с make_point / measure._read_point / calibration (раскладка
    ph↔s, см. CLAUDE.md «Sensor layout convention»): яркость b = max(0, adc_max−s),
    Dx = (b4+b3−b1−b2)/P (право−лево), Dy = (b1+b4−b2−b3)/P (верх−низ).
    """
    if adc_max is None:
        adc_max = cfg.ADC_MAX
    s = np.asarray(s, dtype=float)
    b = np.maximum(0.0, adc_max - s)
    b1, b2, b3, b4 = b[..., 0], b[..., 1], b[..., 2], b[..., 3]
    P = b1 + b2 + b3 + b4
    with np.errstate(divide="ignore", invalid="ignore"):
        Dx = (b4 + b3 - b1 - b2) / P
        Dy = (b1 + b4 - b2 - b3) / P
    return Dx, Dy, P


def points_to_arrays(points: dict):
    """{iN: {s, angle_x, angle_y}} → (keys, s[N,4], angle_x[N], angle_y[N]).

    Углы в MEASURE.json хранятся в записи «градусы.минуты» (DD.MM, напр. '0.20'
    = 0°20'); dm_to_deg переводит их в настоящие градусы для МНК.
    """
    keys = list(points)
    s = np.array([points[k]["s"] for k in keys], dtype=float)
    ax = np.array([dm_to_deg(points[k]["angle_x"]) for k in keys], dtype=float)
    ay = np.array([dm_to_deg(points[k]["angle_y"]) for k in keys], dtype=float)
    return keys, s, ax, ay


# --- МНК по оси + LOO ---------------------------------------------------------

def _fit_axis(V: np.ndarray, y: np.ndarray):
    """МНК и точная leave-one-out ошибка через диагональ hat-матрицы.

    h_ii — рычаг (leverage) точки; LOO-остаток r_i/(1−h_ii) тождествен честному
    циклу «выкинуть точку — пофитить — предсказать», но без N перефитов.
    """
    coef, *_ = np.linalg.lstsq(V, y, rcond=None)
    resid = y - V @ coef
    rmse = float(np.sqrt(np.mean(resid**2)))
    h = np.einsum("ij,jk,ik->i", V, np.linalg.pinv(V.T @ V), V)
    h = np.clip(h, 0.0, 1.0 - 1e-9)
    loo = float(np.sqrt(np.mean((resid / (1.0 - h)) ** 2)))
    return coef, resid, rmse, loo


# --- основной фит -------------------------------------------------------------

def fit_from_points(
    points: dict,
    *,
    degree: int | None = None,
    d_max: float | None = None,
    adc_max: float | None = None,
    mad_k: float | None = None,
    reject_outliers: bool = True,
    source: str | None = None,
) -> tuple[CompensationModel, dict]:
    """
    Построить компенсационную модель по словарю точек MEASURE.json["points"].

    Шаги (см. §12.6 / §11.3): фильтрация (P>0, |D|≤d_max, nz≥NZ_ANGLE_MIN) →
    erfinv-базис → МНК по осям → отбраковка выбросов K·MAD → перефит.

    :return: (CompensationModel, info) — info с диагностикой для печати в CLI.
    """
    degree = cfg.COMP_DEGREE if degree is None else degree
    d_max = cfg.COMP_DMAX if d_max is None else d_max
    adc_max = cfg.ADC_MAX if adc_max is None else adc_max
    mad_k = cfg.COMP_MAD_K if mad_k is None else mad_k

    keys, s, ax, ay = points_to_arrays(points)
    N = len(keys)
    Dx, Dy, P = diffs_from_s(s, adc_max)

    # nz засвеченных квадрантов (как в Задаче №8) — отсев тёмных/частичных точек.
    nz = np.array([
        sum(f > cfg.FRAC_EPS
            for f in (quadrant_fracs(s[i], cfg.S_VAL_MAX, cfg.S_VAL_MIN) or []))
        for i in range(N)
    ])

    # --- фильтрация ---
    valid = np.ones(N, dtype=bool)
    dropped: list[tuple[str, str]] = []
    for i in range(N):
        if not P[i] > 0:
            valid[i] = False
            dropped.append((keys[i], "P≤0 (нет сигнала)"))
        elif abs(Dx[i]) > d_max or abs(Dy[i]) > d_max:
            valid[i] = False
            dropped.append((keys[i], f"|D|>{d_max} (насыщение): Dx={Dx[i]:+.3f} Dy={Dy[i]:+.3f}"))
        elif nz[i] < cfg.NZ_ANGLE_MIN:
            valid[i] = False
            dropped.append((keys[i], f"nz={nz[i]}<{cfg.NZ_ANGLE_MIN} (мало засвеченных квадрантов)"))

    warnings: list[str] = []
    k = n_coef(degree)
    nv = int(valid.sum())
    need = cfg.COMP_MIN_POINTS_PER_COEF * k
    if nv < need:
        warnings.append(
            f"мало точек: {nv} < {need} (={cfg.COMP_MIN_POINTS_PER_COEF}×{k} коэф.) — "
            "понизьте степень или доснимите точки"
        )
    if np.std(ay[valid]) < 1e-6:
        warnings.append(
            "std(angle_y)≈0 — нет 2-D покрытия: y- и перекрёстные члены недоопределены "
            "(стенд качал только по x)"
        )

    # --- фит по валидным точкам ---
    idx = np.where(valid)[0]
    ux, uy = erfinv_basis(Dx[idx], Dy[idx], d_max)
    V = design_matrix(ux, uy, degree)
    cx, rx, rmse_x, loo_x = _fit_axis(V, ax[idx])
    cy, ry, rmse_y, loo_y = _fit_axis(V, ay[idx])

    # --- отбраковка выбросов K·MAD (опечатки ввода углов в терминале) ---
    outliers: list[tuple[str, str, float]] = []
    if reject_outliers and len(idx) > k:
        out_mask = np.zeros(len(idx), dtype=bool)
        for axis_name, r in (("x", rx), ("y", ry)):
            mad = float(np.median(np.abs(r - np.median(r))) * 1.4826)
            if mad <= 0:
                continue
            bad = np.abs(r) > mad_k * mad
            for j in np.where(bad)[0]:
                outliers.append((keys[idx[j]], axis_name, float(r[j])))
            out_mask |= bad
        if out_mask.any():
            idx = idx[~out_mask]
            ux, uy = erfinv_basis(Dx[idx], Dy[idx], d_max)
            V = design_matrix(ux, uy, degree)
            cx, rx, rmse_x, loo_x = _fit_axis(V, ax[idx])
            cy, ry, rmse_y, loo_y = _fit_axis(V, ay[idx])
            warnings.append(
                f"отброшено выбросов: {int(out_mask.sum())} (|остаток|>{mad_k}·MAD)"
            )

    model = CompensationModel(
        degree=degree,
        coef_x=[float(c) for c in cx],
        coef_y=[float(c) for c in cy],
        d_max=float(d_max),

        n_points=int(len(idx)),
        rmse_deg={"x": round(rmse_x, 4), "y": round(rmse_y, 4)},
        loo_rmse_deg={"x": round(loo_x, 4), "y": round(loo_y, 4)},
        source=source,
        warnings=warnings,
    )
    info = {
        "n_total": N,
        "n_valid": nv,
        "n_used": int(len(idx)),
        "degree": degree,
        "n_coef": k,
        "d_max": float(d_max),
        "adc_max": float(adc_max),
        "dropped": dropped,
        "outliers": outliers,
        "d_range": (float(Dx.min()), float(Dx.max()), float(Dy.min()), float(Dy.max())),
        "std_y": float(np.std(ay)),
    }
    return model, info


# --- применение и проверка ----------------------------------------------------

def predict(model: CompensationModel, dx, dy):
    """(Dx, Dy) → (θx, θy) по модели. Скаляр на входе → скаляр на выходе.

    Это та же точка интеграции, что и в рантайме (make_point): подать x_norm/y_norm.
    Вне |D|≤d_max экстраполировать НЕЛЬЗЯ — вызывающий обязан проверить диапазон.
    """
    scalar = np.ndim(dx) == 0
    ux, uy = erfinv_basis(np.asarray(dx, float), np.asarray(dy, float), model.d_max)
    V = design_matrix(ux, uy, model.degree)
    tx = V @ np.asarray(model.coef_x, float)
    ty = V @ np.asarray(model.coef_y, float)
    if scalar:
        return float(tx[0]), float(ty[0])
    return tx, ty


def evaluate(model: CompensationModel, points: dict, adc_max: float | None = None) -> dict:
    """In-sample проверка: применить модель к точкам и сравнить с истинными углами.

    Считается только на точках в зоне валидности |D|≤d_max.
    """
    keys, s, ax, ay = points_to_arrays(points)
    Dx, Dy, P = diffs_from_s(s, adc_max)
    m = (np.abs(Dx) <= model.d_max) & (np.abs(Dy) <= model.d_max) & (P > 0)
    mi = np.where(m)[0]
    tx, ty = predict(model, Dx[m], Dy[m])
    ex, ey = tx - ax[m], ty - ay[m]
    order = np.argsort(-np.maximum(np.abs(ex), np.abs(ey)))
    worst = [(keys[mi[o]], float(ex[o]), float(ey[o])) for o in order[:5]]
    return {
        "n": int(m.sum()),
        "rmse_x": float(np.sqrt(np.mean(ex**2))),
        "rmse_y": float(np.sqrt(np.mean(ey**2))),
        "max_x": float(np.max(np.abs(ex))),
        "max_y": float(np.max(np.abs(ey))),
        "worst": worst,
    }


def holdout_rmse(
    points: dict,
    *,
    degree: int | None = None,
    d_max: float | None = None,
    adc_max: float | None = None,
    frac: float = 0.3,
    iters: int = 200,
    seed: int = 0,
) -> dict:
    """Out-of-sample проверка: случайные train/test разбиения (по умолч. 70/30)."""
    degree = cfg.COMP_DEGREE if degree is None else degree
    d_max = cfg.COMP_DMAX if d_max is None else d_max
    keys, s, ax, ay = points_to_arrays(points)
    Dx, Dy, P = diffs_from_s(s, adc_max)
    m = (np.abs(Dx) <= d_max) & (np.abs(Dy) <= d_max) & (P > 0)
    ux, uy = erfinv_basis(Dx[m], Dy[m], d_max)
    V = design_matrix(ux, uy, degree)
    AX, AY = ax[m], ay[m]
    n = V.shape[0]
    ntest = max(1, int(round(frac * n)))
    rng = np.random.default_rng(seed)
    ex, ey = [], []
    for _ in range(iters):
        perm = rng.permutation(n)
        te, tr = perm[:ntest], perm[ntest:]
        cx, *_ = np.linalg.lstsq(V[tr], AX[tr], rcond=None)
        cy, *_ = np.linalg.lstsq(V[tr], AY[tr], rcond=None)
        ex.append(np.sqrt(np.mean((V[te] @ cx - AX[te]) ** 2)))
        ey.append(np.sqrt(np.mean((V[te] @ cy - AY[te]) ** 2)))
    return {
        "x_mean": float(np.mean(ex)), "x_std": float(np.std(ex)),
        "y_mean": float(np.mean(ey)), "y_std": float(np.std(ey)),
        "n": n, "n_test": ntest, "iters": iters,
    }


def knife_baseline_rmse(
    points: dict,
    w_mm: float,
    *,
    foc: float | None = None,
    d_max: float | None = None,
    adc_max: float | None = None,
) -> dict:
    """Базовая (некомпенсированная) нож-модель — для сравнения «было/стало».

    θ = atan(w·erfinv(D)/(√2·FOC)) — текущая формула deflection_angles.
    """
    foc = float(cfg.FOC) if foc is None else foc
    d_max = cfg.COMP_DMAX if d_max is None else d_max
    keys, s, ax, ay = points_to_arrays(points)
    Dx, Dy, P = diffs_from_s(s, adc_max)
    m = (np.abs(Dx) <= d_max) & (np.abs(Dy) <= d_max) & (P > 0)

    def ang(D):
        d_mm = w_mm * erfinv(np.clip(D, -d_max, d_max)) / math.sqrt(2.0)
        return np.degrees(np.arctan(d_mm / foc))

    ex = ang(Dx[m]) - ax[m]
    ey = ang(Dy[m]) - ay[m]
    return {
        "n": int(m.sum()),
        "rmse_x": float(np.sqrt(np.mean(ex**2))),
        "rmse_y": float(np.sqrt(np.mean(ey**2))),
        "w_mm": float(w_mm), "foc": foc,
    }
