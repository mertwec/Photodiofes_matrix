import csv
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

from src.data_types import Frame


def make_log_path(directory: Path | str = "DATA") -> Path:
    """
    Сформировать путь вида LOG_{timestamp}.csv внутри directory.

    timestamp — локальное время старта записи (YYYYmmdd_HHMMSS).
    Каталог создаётся при отсутствии.
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    return d / f"LOG_{ts}.csv"


def tee_frames_to_csv(
    frames: Iterable[Frame],
    path: Path | str,
) -> Iterator[Frame]:
    """
    Прозрачно («тройник») пишет каждый кадр в CSV и отдаёт его дальше по
    пайплайну без изменений — поэтому встраивается ПОСЛЕ make_point (нужны уже
    рассчитанные углы) и перед display_points_stream, не нарушая контракт
    генератора кадров.

    Колонки лога: ts — системное время записи (YYYYmmdd_HHMMSS.ffffff), затем
    сырые s1..s4 кадра и РАССЧИТАННЫЕ углы отклонения angle_x, angle_y (град).
    Опорные v_x/v_y устройства в лог НЕ пишутся (они считаются неверно) — вместо
    них идут рассчитанные углы. Кадры без углов (нет сигнала / потеря позиции,
    angle_*=None) получают пустые поля angle_x/angle_y.

    Файл открывается лениво — на первом кадре, чтобы при мгновенном выходе
    не оставался пустой LOG. Каждая строка flush'ится: при обрыве UART/Ctrl-C
    теряется максимум последний кадр. Файл закрывается при завершении генератора.

    :yield: тот же Frame, что пришёл на вход.
    """
    path = Path(path)
    fieldnames = ["ts", "s1", "s2", "s3", "s4", "angle_x", "angle_y"]
    f = None
    writer: csv.DictWriter | None = None

    def _ang(v) -> str:
        return "" if v is None else f"{v:.4f}"

    try:
        for frame in frames:
            if f is None:
                f = path.open("w", newline="")
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                print(f"Запись лога: {path}")
            s = frame.s or (None, None, None, None)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S.%f")
            writer.writerow({
                "ts": ts,
                "s1": s[0], "s2": s[1], "s3": s[2], "s4": s[3],
                "angle_x": _ang(frame.angle_x),
                "angle_y": _ang(frame.angle_y),
            })
            f.flush()
            yield frame
    finally:
        if f is not None:
            f.close()
