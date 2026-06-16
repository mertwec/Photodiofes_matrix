"""
Постоянный радиус засветки из калибровочных данных нож-сканирования (Задача №5).

По CALIBRATE.json (Задача №4) считаем ОДИН радиус пятна и используем его в
визуализации — это ЕДИНСТВЕННЫЙ источник радиуса (покадровый расчёт по засветке
квадрантов убран): радиус — физическое свойство оптики, он постоянен. Без
калибровки круг пятна не рисуется вовсе.

Модель гаусс-ножа (profile "gauss_1e2"): нормированная разность право/лево
`D = erf(√2 · s / w)`, где s — положение центра пятна относительно границы
квадрантов, w — радиус пятна по уровню 1/e².

Расчёт — РАЗНОСТЯМИ в пространстве аргумента erfinv (AI_ANALYSE.md §9.5):

    erfinv(D_i) − erfinv(D_j) = √2 · (x_i − x_j) / w
    ⇒   w = √2 · (x_i − x_j) / (erfinv(D_i) − erfinv(D_j))

где x_i = FOC · tan(CALIB_ANGLE_SCALE · Δθ_i), а Δθ_i = θ_i − θ_{i0} — угол
относительно ЦЕНТРАЛЬНОЙ точки. В разности смещение нуля (луч в i0 не точно на
границе) сокращается точно — в отличие от вычитания в D-пространстве, которое
искажается нелинейностью erf.

Основная оценка — по паре крайних точек (i1, i2): столик ходит только по оси x,
поэтому точек две. Центр i0 — опора нуля угла и контроль: по нему считаются
диагностические w каждой боковой точки (расхождение пары — признак асимметрии
или фона).

Радиус в пиксели: весь датчик (cfg.DET_SIZE_MM) ↔ весь дисплей (SIZE_DISPLAY),
поэтому radius_px = w_mm · cfg.CALIB_PX_PER_MM — без клампа, реальное значение.
"""

import itertools
import json
import math
from pathlib import Path

from scipy.special import erfinv

from config import cfg
from src.utils.normalization import normalize_deg


def _w_pair(a: tuple[str, float, float], b: tuple[str, float, float]) -> float | None:
    """w по паре точек (key, D, x_мм); None — пара вырождена или знак не сходится."""
    (_, da, xa), (_, db, xb) = a, b
    de = float(erfinv(da)) - float(erfinv(db))
    if abs(de) < cfg.EI_D_MIN:
        return None
    w = math.sqrt(2.0) * (xa - xb) / de
    return w if w > 0 else None


def spot_radius_from_points(pts: dict) -> dict | None:
    """
    Радиус пятна по словарю точек калибровки {key: {x_norm, angle, …}}.

    Используется и офлайн (spot_radius_from_calib), и онлайн из run_calibration
    для мгновенного контроля после каждой снятой точки (AI_ANALYSE.md §9.4).

    :return: dict {radius_px, w_mm, per_point, warnings} либо None, если годных
             точек для хотя бы одной пары нет.
    """
    foc = float(cfg.FOC)  # мм
    warnings: list[str] = []

    p0 = pts.get("i0") or {}
    theta0 = normalize_deg(float(p0["angle"])) if "angle" in p0 else 0.0
    d0 = float(p0.get("x_norm", 0.0))

    # Валидные точки: (key, D, x_мм). Центр — опора нуля угла, его x = 0.
    points: list[tuple[str, float, float]] = []
    for key, p in pts.items():
        if "angle" not in p or "x_norm" not in p:
            continue
        D = float(p["x_norm"])
        if abs(D) >= cfg.D_MAX:
            warnings.append(
                f"{key}: |D|={abs(D):.3f} в насыщении (≥{cfg.D_MAX}) — точка пропущена"
            )
            continue
        if key == "i0":
            points.append((key, D, 0.0))
            continue
        dtheta = normalize_deg(float(p["angle"])) - theta0
        # Валидация знаков вместо abs() (§9.5): право — положительные D и Δθ.
        if (D - d0) * dtheta < 0:
            warnings.append(
                f"{key}: знак D={D:+.3f} не согласован со знаком "
                f"Δθ={dtheta:+.2f}° — проверьте раскладку ph↔s / знак столика"
            )
        if abs(D) < cfg.CALIB_SIDE_EPS + 0.02:
            warnings.append(
                f"{key}: D={D:+.3f} близко к порогу фиксации "
                f"({cfg.CALIB_SIDE_EPS}) — точка могла быть снята не в крайнем положении"
            )
        points.append((key, D, foc * math.tan(math.radians(dtheta))))

    sides = [p for p in points if p[0] != "i0"]
    center = next((p for p in points if p[0] == "i0"), None)

    # Основная оценка — пары крайних точек (обычно одна: i1−i2).
    est: list[float] = []
    for a, b in itertools.combinations(sides, 2):
        w = _w_pair(a, b)
        if w is not None:
            est.append(w)
        else:
            warnings.append(f"пара {a[0]}−{b[0]} отброшена (вырождена или w ≤ 0)")
    # Снята пока одна боковая точка — оценка по паре с центром (онлайн-контроль).
    if not est and center is not None:
        est = [w for sp in sides if (w := _w_pair(sp, center)) is not None]

    if not est:
        return None
    w_mm = sum(est) / len(est)

    # Диагностика: w каждой боковой точки относительно центра + разброс оценок.
    per_point: dict = {}
    diag = list(est)
    for sp in sides:
        w = _w_pair(sp, center) if center is not None else None
        per_point[sp[0]] = {
            "D": round(sp[1], 4),
            "x_mm": round(sp[2], 3),
            "w_mm": round(w, 3) if w is not None else None,
        }
        if w is not None:
            diag.append(w)
    if abs(d0) > 0.1:
        warnings.append(
            f"центр смещён: D(i0)={d0:+.3f} — луч в i0 заметно не на границе"
        )
    if len(diag) > 1 and max(diag) > 1.2 * min(diag):
        warnings.append(
            f"разброс оценок w: {min(diag):.2f}…{max(diag):.2f} мм (>20%) — "
            "несимметричные точки или фоновая засветка"
        )

    return {
        "radius_px": w_mm * cfg.CALIB_PX_PER_MM,
        "w_mm": w_mm,
        "per_point": per_point,
        "warnings": warnings,
    }


def spot_radius_from_calib(calib_path: Path | str) -> dict | None:
    """
    Постоянный радиус пятна по файлу CALIBRATE.json.

    :return: см. spot_radius_from_points; None — если файла нет.
    """
    path = Path(calib_path)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return spot_radius_from_points(data.get("points", {}))

def info_calib_radius(calib_file=cfg.CALIB_FILE) -> float | None:
    """
    Постоянный радиус пятна из калибровки (Задача №5) или None, если калибровки нет.

    Радиус берётся ТОЛЬКО из калибровки (нож-сканирование): без CALIBRATE.json
    круг пятна не отображается — рисуется только точка.
    """
    info = spot_radius_from_calib(calib_file)
    if info is None:
        print(
            "[Радиус] Калибровка не найдена — круг пятна не отображается "
            "(только точка)."
        )
        return None
    print(
        f"[Радиус] Постоянный радиус из калибровки: {info['radius_px']:.1f} px "
        f"(w≈{info['w_mm']:.2f} мм). Файл: {calib_file}"
    )
    for msg in info.get("warnings", []):
        print(f"[Радиус] ⚠ {msg}")
    return info["radius_px"]