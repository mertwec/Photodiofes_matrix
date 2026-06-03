from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit
from scipy.special import erf


@dataclass
class CalibResult:
    phi_c: float           # средн. φc по X и Y (единицы — как v_x/v_y в логе)
    phi_range: float       # макс. |угол| в логе: знаменатель нормировки на дисплее
    phi_c_x: float | None  # φc по оси X
    phi_c_y: float | None  # φc по оси Y

    def spot_r_px(self, size: int) -> float:
        """Радиус пятна в пикселях для дисплея size×size.

        Линейно нормирует φc на диапазон свипа: пятно занимает
        ту же долю экрана, что φc занимает от phi_range.
        """
        return self.phi_c / self.phi_range * (size / 2)

    def __str__(self) -> str:
        cx = f"{self.phi_c_x:.2f}" if self.phi_c_x else "—"
        cy = f"{self.phi_c_y:.2f}" if self.phi_c_y else "—"
        return f"φc={self.phi_c:.2f} (X:{cx} Y:{cy}), range={self.phi_range:.1f}"


def _fit_axis(
    phi: np.ndarray,
    r: np.ndarray,
    sn: np.ndarray | None = None,
) -> float | None:
    """Фит одной оси r = erf(φ/φc). Возвращает φc или None."""
    mask = (np.abs(r) >= 0.02) & (np.abs(r) <= 0.92)
    if sn is not None:
        mask &= sn > 0.05
    if mask.sum() < 4:
        return None
    try:
        popt, _ = curve_fit(
            lambda p, pc: erf(p / pc),
            phi[mask], r[mask],
            p0=[5.0], bounds=(0.1, 100.0), maxfev=5000,
        )
        return float(popt[0])
    except Exception:
        return None


def calibrate_phi_c(df: pd.DataFrame) -> CalibResult | None:
    """
    Оценивает φc (меру размера пятна) по скану: фитит rx = erf(v_x/φc).

    Требует столбцы s1..s4 и v_x, v_y в df (v_x/v_y — истинный угол/эталон).
    Возвращает None если данных или столбцов недостаточно для устойчивого фита
    (нет свипа, нет v_x/v_y, маска отфильтровала < 4 точек).

    Физика — см. AI_ANSWER.md §2–3. Раскладка s↔ph: ph1=s1, ph2=s4, ph3=s2, ph4=s3
    (матрица [[b1,b4],[b2,b3]]), поэтому rx = (b4+b3−b1−b2)/S.
    """
    required = {"s1", "s2", "s3", "s4", "v_x", "v_y"}
    if not required.issubset(df.columns):
        return None

    adc = float(df[["s1", "s2", "s3", "s4"]].to_numpy().max())
    b1 = adc - df["s1"]; b2 = adc - df["s2"]
    b3 = adc - df["s3"]; b4 = adc - df["s4"]
    S = b1 + b2 + b3 + b4
    rx = ((b4 + b3 - b1 - b2) / S).to_numpy()
    ry = ((b1 + b4 - b2 - b3) / S).to_numpy()
    sn = (S / S.max()).to_numpy()

    phi_x = df["v_x"].to_numpy()
    phi_y = df["v_y"].to_numpy()

    pc_x = _fit_axis(phi_x, rx, sn)
    pc_y = _fit_axis(phi_y, ry, sn)
    vals = [v for v in (pc_x, pc_y) if v is not None]
    if not vals:
        return None

    phi_c = float(np.mean(vals))
    phi_range = float(np.abs(np.concatenate([phi_x, phi_y])).max())
    if phi_range < 1e-6:
        return None

    return CalibResult(phi_c=phi_c, phi_range=phi_range, phi_c_x=pc_x, phi_c_y=pc_y)


def fit_phi_c_from_signals(
    phi_x: np.ndarray,
    rx: np.ndarray,
    phi_y: np.ndarray,
    ry: np.ndarray,
    sn: np.ndarray | None = None,
) -> CalibResult | None:
    """
    Вариант calibrate_phi_c для уже вычисленных массивов (phi, r).

    Используется онлайн-режимом, где rx/ry считаются покадрово в потоке
    и не нужно повторно разворачивать DataFrame.
    sn — нормированная яркость (S/S_max); если None, фильтр по яркости отключён.
    """
    pc_x = _fit_axis(phi_x, rx, sn)
    pc_y = _fit_axis(phi_y, ry, sn)
    vals = [v for v in (pc_x, pc_y) if v is not None]
    if not vals:
        return None

    phi_c = float(np.mean(vals))
    phi_range = float(np.abs(np.concatenate([phi_x, phi_y])).max())
    if phi_range < 1e-6:
        return None

    return CalibResult(phi_c=phi_c, phi_range=phi_range, phi_c_x=pc_x, phi_c_y=pc_y)
