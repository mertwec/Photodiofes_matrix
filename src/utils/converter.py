"""
Конвертер сырого лога UART в CSV формата putty.csv.

Вход — дамп с UART, где каждая строка это python-repr байтов, как их отдаёт
`serial.readline()`:

    b'06800606;0018;0036;0111;0153;-0.079;-0.024\\r\\n'

Поля разделены ';' (формат устройства) или ',' — принимаются оба. На выходе —
CSV с заголовком cfg.COLUMNS (T,s1,s2,s3,s4,v_x,v_y), как DATA/putty.csv:
T и s1..s4 — целые без ведущих нулей, v_x/v_y — в формате '%+09.4f'
(-0.079 -> -000.0790). Строки также принимаются «как есть» (без обёртки b'...'),
поэтому конвертер работает и с обычным текстовым дампом устройства.

Пропускаются: пустые строки и пустые serial-чтения (b''), битые/неполные строки
(< 5 полей) и строка-заголовок (нечисловые T/s1..s4).
"""

import ast
import csv
import re
from pathlib import Path
import json

from config import cfg

# Разделитель полей — ';' (устройство) или ',' (CSV). Как в stream_reader.
_FIELD_SEP = re.compile(r"[;,]")


def _decode_line(raw: str) -> str | None:
    """
    Приводит одну строку лога к чистому тексту.

    Если строка — python-repr байтов (b'...\\r\\n'), разбирает её через
    ast.literal_eval и декодирует ASCII. Иначе возвращает как есть. Возвращает
    None, если строка пустая или не разобралась (битый repr).
    """
    raw = raw.strip()
    if not raw:
        return None
    if raw.startswith(("b'", 'b"')):
        try:
            raw = ast.literal_eval(raw).decode("ascii", errors="replace")
        except (ValueError, SyntaxError):
            return None  # битый repr (например, обрезанный хвост b''v)
    line = raw.strip()
    return line or None  # пустой serial-read b'' -> None


def log_to_csv(input_log: Path, output_csv: Path) -> int:
    """
    Конвертирует лог UART в CSV формата putty.csv.

    :param input_log: путь к сырому логу (строки b'...;...;...\\r\\n' или текст).
    :param output_csv: путь к создаваемому CSV (перезаписывается).
    :return: число записанных строк данных (без заголовка).
    """
    input_log, output_csv = Path(input_log), Path(output_csv)
    written = 0
    with open(input_log, "r", errors="replace") as f_in, open(
        output_csv, "w", newline=""
    ) as f_out:
        writer = csv.writer(f_out)
        writer.writerow(cfg.COLUMNS)  # T,s1,s2,s3,s4,v_x,v_y

        for raw in f_in:
            line = _decode_line(raw)
            if line is None:
                continue

            parts = [p for p in _FIELD_SEP.split(line) if p != ""]
            if len(parts) < 5:
                continue  # нужно минимум T + 4 датчика

            try:
                # T и s1..s4 — целые (int отбрасывает ведущие нули: 0018 -> 18).
                t = int(parts[0])
                s1, s2, s3, s4 = (int(p) for p in parts[1:5])
            except ValueError:
                continue  # строка-заголовок или мусор

            # v_x/v_y — опциональны; формат putty.csv '%+09.4f'. При отсутствии
            # или непарсимости оставляем пустыми (строка всё равно валидна).
            v_x = v_y = ""
            if len(parts) >= 7:
                try:
                    v_x = f"{float(parts[5]):+09.4f}"
                    v_y = f"{float(parts[6]):+09.4f}"
                except ValueError:
                    v_x = v_y = ""

            writer.writerow((t, s1, s2, s3, s4, v_x, v_y))
            written += 1

    return written


def format_duration_hms(t) -> str | None:
    """
    Время кадра из T в формате H:M:S.

    T — детекторное время в миллисекундах (счётчик от старта устройства),
    приходит int (лог) или строкой (UART, напр. '06800606'). Переводим в
    длительность: T/1000 секунд → ЧЧ:ММ:СС. Возвращает None, если T нет/не число.
    """
    if t is None:
        return None
    try:
        total_s = int(float(t)) // 1000
    except (TypeError, ValueError):
        return None
    h, rem = divmod(total_s, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def dms_to_deg(deg:float, minute:float = 0, seconds:float = 0):
    return deg + minute/60 + seconds/3600


def dm_to_deg(value) -> float:
    """
    Запись «градусы.минуты» (DD.MM) → угол в градусах (float, до 6 знака).

    Дробная часть строки — это угловые минуты (две позиционные цифры 00..59),
    а НЕ доля градуса. Принимает str или число (str() применяется внутри):

        '0.2'  = '0.20' = 0°20' = 0.333333
        '0.30'          = 0°30' = 0.5
        '1.40'          = 1°40' = 1.666667
        '-1.40'         = -1°40' = -1.666667
        '2.00'          = 2°00' = 2.0

    Так хранятся углы в DATA/MEASURE/MEASURE.json: при вычислении полинома их
    нужно прогонять через эту функцию (см. compensation.points_to_arrays).
    """
    text = str(value).strip()
    if not text:
        return 0.0
    sign = -1.0 if text[0] == "-" else 1.0
    text = text.lstrip("+-")
    deg_part, _, min_part = text.partition(".")
    deg = int(deg_part) if deg_part else 0
    # цифры после точки — позиционные минуты: '2'->20, '20'->20, '05'->5.
    minutes = int((min_part + "00")[:2]) if min_part else 0
    return round(sign * (dms_to_deg(deg, minutes)), 6)


def deg_to_dm(value: float) -> str:
    """
    Угол в градусах → запись «градусы.минуты» (DD.MM), обратная к dm_to_deg.

    Минуты округляются до ближайшей целой и дополняются до двух цифр:
    0.333 → '0.20', 0.5 → '0.30', 1.667 → '1.40', -0.333 → '-0.20', 0.0 → '0.00'.
    """
    sign = "-" if value < -1e-9 else ""
    deg, minutes = divmod(round(abs(value) * 60), 60)
    return f"{sign}{deg}.{minutes:02d}"


def json_to_print_table(js_file:Path):
    with open(js_file, "r") as f:
        js_data = json.load(f)

    print(f"| i\t\t | s1\t\t | s2\t\t | s3\t\t | s4\t\t | Th_x\t\t | Th_y\t\t")
    print(f"| ---\t\t | ---\t\t | ---\t\t | ---\t\t | ---\t\t | ---\t\t | ---\t\t")
    for i, v in js_data["points"].items():
        print(f"| {i:>10} | {v['s'][0]:>10} | {v['s'][1]:>10} | {v['s'][2]:>10} | {v['s'][3]:>10} | {v['angle_x']:>10} | {v['angle_y']:>10} |")


