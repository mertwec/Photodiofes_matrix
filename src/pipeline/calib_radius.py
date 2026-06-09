"""
Постоянный радиус засветки из калибровочных данных нож-сканирования (Задача №5).

По CALIBRATE.json (Задача №4) считаем ОДИН радиус пятна и используем его в
визуализации вместо покадрового геометрического решателя (solve_xyr2): радиус —
физическое свойство оптики, он постоянен.

Модель гаусс-ножа (profile "gauss_1e2"): нормированная разность право/лево
`D = x_norm` на границе квадрантов связана со смещением луча x и радиусом пятна w
(по уровню 1/e²):

    D = erf(√2 · x / w)      ⇒      w = √2 · x / erfinv(D)

Смещение из угла столика и фокуса: `x = FOV · tan(θ)` (θ — угол точки в градусах,
FOV — фокусное расстояние из калибровки). Это даёт ФИЗИЧЕСКИЙ радиус w [м/мм].

Радиус в пиксели: весь датчик (cfg.DET_SIZE_MM) ↔ весь дисплей (size), поэтому
    radius_px = w_mm · cfg.CALIB_PX_PER_MM (= w_mm · size / DET_SIZE_MM)
без клампа — возвращаем реальное значение.
"""

import json
import math
from pathlib import Path

from scipy.special import erfinv

from config import cfg
from src.utils.normalization import normalize_deg

# Рабочий диапазон |D| для устойчивой инверсии erfinv: у нуля 0/0, у ±1 → ∞.
_D_MIN, _D_MAX = 1e-3, 0.999


def spot_radius_from_calib(calib_path: Path | str) -> dict | None:
    """
    Постоянный радиус пятна по CALIBRATE.json.

    :return: dict {radius_px, w_mm, per_point} либо None, если файла нет или нет
             годных боковых точек (|D| вне рабочего диапазона).
    """
    path = Path(calib_path)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    pts = data.get("points", {})
    fov = float(cfg.FOV)           # м

    d0 = float(pts.get("i0", {}).get("x_norm", 0.0))  # смещение нуля (центр)

    mm_list: list[float] = []
    per_point: dict = {}
    for key, p in pts.items():
        if key == "i0":                              # центр — нулевая точка
            continue
        D = float(p["x_norm"]) - d0                  # коррекция на центр
        theta = math.radians(normalize_deg(float(p["angle"])))
        aD = abs(D)
        if not (_D_MIN < aD < _D_MAX) or theta == 0.0:
            continue                                 # шум у нуля / насыщение
        ei = float(erfinv(aD))
        x_mm = fov * math.tan(abs(theta))           # смещение луча, мм
        w_mm = math.sqrt(2.0) * x_mm / ei            # радиус пятна (1/e²), мм
        mm_list.append(w_mm)
        per_point[key] = {"D": round(D, 4),
                          "angle_deg": round(math.degrees(theta), 3),
                          "w_mm": round(w_mm, 3)}

    if not mm_list:
        return None

    w_mm = sum(mm_list) / len(mm_list)
    radius_px = w_mm * cfg.CALIB_PX_PER_MM

    return {"radius_px": radius_px, "w_mm": w_mm, "per_point": per_point}
