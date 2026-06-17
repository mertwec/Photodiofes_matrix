"""
Модуль получения компенсационного полинома (Задача №13).

Оркестровка вокруг src/compensation.py: читает DATA/MEASURE/MEASURE.json,
строит CompensationModel и сохраняет её в DATA/MEASURE/COMPENSATION.json
(по аналогии с CALIBRATE.json для радиуса пятна). Файловый ввод-вывод и метка
времени — здесь; сама математика — в src/compensation.py.
"""

import json
from datetime import datetime
from pathlib import Path

from config import cfg
from src.compensation import fit_from_points
from src.data_types import CompensationModel


def load_measure_points(measure_path: Path | str | None = None) -> dict:
    """Прочитать словарь точек из MEASURE.json (по умолч. cfg.MEASURE_FILE)."""
    path = Path(measure_path) if measure_path else cfg.MEASURE_FILE
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data.get("points", {})


def build_compensation(
    measure_path: Path | str | None = None,
    *,
    degree: int | None = None,
    reject_outliers: bool = True,
) -> tuple[CompensationModel, dict]:
    """
    Построить компенсационную модель из MEASURE.json.

    :return: (model, info) — model с проставленной меткой created; info — диагностика.
    """
    path = Path(measure_path) if measure_path else cfg.MEASURE_FILE
    points = load_measure_points(path)
    model, info = fit_from_points(
        points, degree=degree, reject_outliers=reject_outliers, source=str(path)
    )
    model.created = datetime.now().strftime("%Y%m%d_%H%M%S")
    return model, info


def save_compensation(
    model: CompensationModel, out_path: Path | str | None = None
) -> Path:
    """Сохранить модель в COMPENSATION.json (по умолч. cfg.COMP_FILE). Возвращает путь."""
    path = Path(out_path) if out_path else cfg.COMP_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(model.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


def load_compensation(path: Path | str | None = None) -> CompensationModel | None:
    """Загрузить модель из COMPENSATION.json или None, если файла нет.

    Это будущая точка интеграции в рантайм (log/stream): нет файла — нет
    компенсации, поведение не меняется (как info_calib_radius без CALIBRATE.json).
    """
    p = Path(path) if path else cfg.COMP_FILE
    if not p.exists():
        return None
    return CompensationModel.from_dict(json.loads(p.read_text(encoding="utf-8")))
