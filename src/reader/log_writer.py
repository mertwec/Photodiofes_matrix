import csv
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

from config import cfg


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


def tee_to_csv(
    rows: Iterable[dict],
    path: Path | str,
    columns: tuple[str, ...] = cfg.COLUMNS,
) -> Iterator[dict]:
    """
    Прозрачно («тройник») пишет каждую валидную строку датчиков в CSV и отдаёт
    её дальше по пайплайну без изменений — поэтому встраивается между
    read_serial_rows и make_point, не нарушая контракт генератора.

    В лог пишутся два времени: ts — системное время записи (первый столбец,
    YYYYmmdd_HHMMSS.ffffff), и T — время с детектора (приходит в строке, второй
    столбец); далее s1,s2,s3,s4,v_x,v_y. Строки сюда приходят уже отфильтрованными
    (read_serial_rows отбрасывает заголовок/мусор/неполные строки), поэтому пишется
    только валидное. Отсутствующие T/v_x/v_y оставляются пустыми. ts проставляется
    в момент записи строки.

    Файл открывается лениво — на первой строке, чтобы при мгновенном выходе
    не оставался пустой LOG. Каждая строка flush'ится: при обрыве UART/Ctrl-C
    теряется максимум последний кадр. Файл закрывается при завершении генератора.

    :yield: ту же строку dict, что и пришла на вход.
    """
    path = Path(path)
    fieldnames = ["ts", *columns]
    f = None
    writer: csv.DictWriter | None = None
    try:
        for row in rows:
            if f is None:
                f = path.open("w", newline="")
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                print(f"Запись лога: {path}")
            ts = datetime.now().strftime("%Y%m%d_%H%M%S.%f")
            writer.writerow({"ts": ts, **{c: row.get(c, "") for c in columns}})
            f.flush()
            yield row
    finally:
        if f is not None:
            f.close()
