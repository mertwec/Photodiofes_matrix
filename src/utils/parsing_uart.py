"""
Приём и разбор посылок UART (Задача №15).

Формат — DOCUMENTATION/uart_interface_specification.pdf (изделие AGS 16.00.10,
редакция 1.1). Посылка: два синхробайта, длина блока, блок данных, CRC.

    AA 55 | LEN | блок данных LEN байт | CRC_hi CRC_lo

Числовые поля блока — младшим байтом вперёд, CRC-16/CCITT-FALSE — старшим
байтом вперёд и считается по байту LEN и всему блоку (§4). Границы посылки
берутся из поля LEN, а не из константы 35 (§3), но разбирается только блок
редакции 1.1 (LEN = 30, с отсчётами квадрантов) — посылки другой длины
пропускаются. Единственный признак верной синхронизации — сошедшаяся CRC,
поэтому при несовпадении поиск 0xAA 0x55 продолжается со следующего байта.

Модуль читает и текстовый hex-дамп (как DATA/SYNTHETIC/uart_log.txt и
DATA/UART_LOG/log.txt), и двоичный дамп, и определяет формат файла
автоматически (`is_uart_log`) — чтобы `cli.py log` мог проигрывать и старые
CSV-логи, и новый формат.

Шкала отсчётов. В посылке зависимость обратная и своя (§5.1): тёмновой
уровень ≈2048, максимальная засветка ≈186. Пайплайн проекта ждёт «сырые»
значения в шкале cfg.ADC_MAX (0 — max засветка, ADC_MAX — темнота), поэтому
`adc_to_raw` переводит одно в другое: относительная засветка S_i = N0 − adc_i
сохраняется точно, и make_point (а с ним и компенсационный полином) работает с
такими строками без изменений.

Самопроверка на синтетике: `python -m src.utils.parsing_uart`.
"""

import struct
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from config import cfg
from src.utils.converter import dms_to_deg

# --- Кадр обмена (§3) ---
SOF = b"\xaa\x55"
LEN_DATA = 30  # длина блока данных, редакция 1.1
# Раскладка блока (§5): uptime, углы X/Y как град/мин/сек, служебные поля,
# счётчик измерений и четыре отсчёта квадрантов.
FMT30 = "<IbBBbBBBBHHBBIHHHH"

# --- Поле признаков (§6) ---
F_EXT_RANGE = 0x01
F_X_NEG = 0x08
F_Y_NEG = 0x10
F_VALID = 0x20

# --- Отсчёты квадрантов (§5.1) ---
ADC_FULL = 4095
DARK_LEVEL = 2048  # типовой отсчёт при отсутствии засветки; изделием не передаётся


def crc16_ccitt(data: Iterable[int], crc: int = 0xFFFF) -> int:
    """
    CRC-16/CCITT-FALSE (§4, приложение А): полином 0x1021, начальное значение
    0xFFFF, без отражения входа/выхода и без финального сложения по модулю 2.
    """
    for x in data:
        crc ^= x << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def parse_data_block(d: bytes) -> dict | None:
    """
    Блок данных (30 байт, редакция 1.1) → словарь полей (§5, §6, §7).

    Возвращает None для блока другой длины (в том числе для редакции 1.0 —
    22 байта без отсчётов квадрантов).

    Знак угла берётся ИСКЛЮЧИТЕЛЬНО из битов X_NEG/Y_NEG поля признаков (§7):
    при |угол| < 1° поле градусов равно нулю и знак в нём не представим.
    """
    if len(d) < LEN_DATA:
        return None

    (uptime, xd, xm, xs, yd, ym, ys, locked, quality,
     cvalid, cmiss, vpct, flags, count, *adc) = struct.unpack(FMT30, d[:LEN_DATA])

    x_deg = dms_to_deg(xd, xm, xs, negative=bool(flags & F_X_NEG))
    y_deg = dms_to_deg(yd, ym, ys, negative=bool(flags & F_Y_NEG))

    return dict(
        uptime_ms=uptime,
        x_deg=x_deg,
        y_deg=y_deg,
        locked=bool(locked),
        quality=quality / 255.0,
        consec_valid=cvalid,
        consec_miss=cmiss,
        valid_percent=vpct,
        frame_count=count,
        ext_range=bool(flags & F_EXT_RANGE),
        mode=(flags >> 1) & 0x03,
        valid=bool(flags & F_VALID),
        adc=adc,  # [S1, S2, S3, S4]
    )


def quadrant_levels(adc: Sequence[int], dark_level: int = DARK_LEVEL) -> tuple:
    """
    Относительные засветки квадрантов и разностные сигналы (§5.1).

        S_i = max(0, N0 − adc_i),  rx = (S4+S3−S1−S2)/Σ,  ry = (S1+S4−S2−S3)/Σ

    dark_level — типовой ориентир; точное значение изделием не передаётся.
    Возвращает (S, Σ/(4·4095), rx, ry).
    """
    s = [max(0, dark_level - int(v)) for v in adc]
    total = sum(s)
    if total == 0:
        return s, 0.0, 0.0, 0.0
    return (
        s,
        total / (4 * ADC_FULL),
        (s[3] + s[2] - s[0] - s[1]) / total,  # rx
        (s[0] + s[3] - s[1] - s[2]) / total,  # ry
    )


def extract_frames(buf: bytes) -> tuple[list[bytes], bytes]:
    """
    Выделяет из буфера все целые посылки (§9). Возвращает (список блоков данных,
    остаток буфера). Остаток начинается с недочитанной посылки — его надо
    склеить со следующей порцией байт (нужно для потокового чтения).
    """
    out: list[bytes] = []
    i = 0
    while True:
        i = buf.find(SOF, i)
        if i < 0:
            return out, b""
        if i + 3 > len(buf):
            return out, buf[i:]
        ln = buf[i + 2]
        end = i + 3 + ln + 2
        if end > len(buf):
            return out, buf[i:]  # посылка ещё не дочитана
        crc_rx = (buf[end - 2] << 8) | buf[end - 1]  # старший байт вперёд
        if crc16_ccitt(buf[i + 2 : end - 2]) == crc_rx:
            out.append(buf[i + 3 : end - 2])
            i = end
        else:
            i += 1  # ложная синхронизация: 0xAA 0x55 внутри блока данных


def iter_packets(data: bytes) -> Iterator[dict]:
    """Байтовый буфер → поток разобранных посылок (битые/обрезанные пропускаются)."""
    blocks, _ = extract_frames(data)
    for block in blocks:
        packet = parse_data_block(block)
        if packet is not None:
            yield packet


def adc_to_raw(
    adc: Sequence[int],
    dark_level: int = DARK_LEVEL,
    adc_max: float | None = None,
) -> tuple[float, float, float, float]:
    """
    Отсчёты квадрантов из посылки (§5.1) → сырые значения в шкале проекта.

    В посылке засветка считается от тёмнового уровня: S_i = max(0, N0 − adc_i).
    Пайплайн ждёт обратного: raw = adc_max при темноте и raw = adc_max − S_i при
    засветке (make_point берёт яркость как max(0, adc_max − raw)). Такой перенос
    сохраняет S_i байт в байт, поэтому разностные сигналы D и все зависящие от
    них расчёты (в том числе компенсационный полином, который считает D по
    cfg.ADC_MAX) не искажаются.
    """
    adc_max = cfg.ADC_MAX if adc_max is None else adc_max
    return tuple(  # type: ignore[return-value]
        float(min(adc_max, max(0.0, adc_max - max(0, dark_level - int(v))))) for v in adc
    )


def rows_from_packets(
    packets: Iterable[dict],
    dark_level: int = DARK_LEVEL,
    adc_max: float | None = None,
) -> Iterator[dict]:
    """
    Разобранные посылки → строки пайплайна {T, s1..s4, v_x, v_y}.

    T — время работы изделия, мс (uptime_ms). v_x/v_y — переданные изделием
    углы отклонения по осям, градусы; они заполняются только когда изделие
    считает измерение годным (признак захвата + бит VALID, §7), иначе None —
    в остальных случаях поля углов не определены.
    """
    adc_max = cfg.ADC_MAX if adc_max is None else adc_max
    for packet in packets:
        s1, s2, s3, s4 = adc_to_raw(packet["adc"], dark_level, adc_max)
        usable = packet["locked"] and packet["valid"]
        yield {
            "T": packet["uptime_ms"],
            "s1": s1,
            "s2": s2,
            "s3": s3,
            "s4": s4,
            "v_x": packet["x_deg"] if usable else None,
            "v_y": packet["y_deg"] if usable else None,
        }


def read_uart_bytes(path: Path | str) -> bytes:
    """
    Читает дамп посылок: текстовый hex («AA 55 1E …», пробелы и переводы строк
    игнорируются) или двоичный — определяется по первым байтам файла.
    """
    data = Path(path).read_bytes()
    if data.startswith(SOF):
        return data
    cleaned = "".join(data.decode("ascii", errors="ignore").split())
    if len(cleaned) % 2:
        cleaned = cleaned[:-1]  # обрезанный последний полубайт
    return bytes.fromhex(cleaned)


def is_uart_log(path: Path | str, probe: int = 4096) -> bool:
    """
    Файл — дамп посылок UART (двоичный или hex-текст), а не CSV-лог?

    Признак: файл начинается с синхропоследовательности 0xAA 0x55 — либо
    байтами, либо её hex-записью. Этого достаточно, чтобы отличить формат от
    CSV (тот начинается с заголовка или числа) и выбрать нужный ридер.
    """
    head = Path(path).read_bytes()[:probe]
    if head.startswith(SOF):
        return True
    cleaned = "".join(head.decode("ascii", errors="ignore").split())[:4]
    if len(cleaned) < 4:
        return False
    try:
        return bytes.fromhex(cleaned) == SOF
    except ValueError:
        return False


def read_uart_log(
    path: Path | str,
    dark_level: int = DARK_LEVEL,
    adc_max: float | None = None,
) -> tuple[list[dict], float, dict]:
    """
    Дамп посылок UART → (строки пайплайна, опорный adc_max, статистика).

    Аналог `get_single_point.df_to_raw_rows` для нового формата: строки той же
    формы {T, s1..s4, v_x, v_y} идут прямо в `make_point`. adc_max здесь
    фиксированный (cfg.ADC_MAX) — в него уже пересчитаны отсчёты (см.
    `adc_to_raw`), поэтому шкала D совпадает с той, на которой обучался
    компенсационный полином.

    Статистика: сколько байт прочитано, сколько посылок разобрано, сколько байт
    отброшено при поиске синхронизации (ложные 0xAA 0x55 и мусор), сколько
    осталось в недочитанном хвосте и в скольких посылках нет годного измерения.
    """
    adc_max = cfg.ADC_MAX if adc_max is None else adc_max
    data = read_uart_bytes(path)
    blocks, tail = extract_frames(data)

    packets = [p for p in (parse_data_block(b) for b in blocks) if p is not None]
    rows = list(rows_from_packets(packets, dark_level, adc_max))

    used = sum(len(b) + 5 for b in blocks)  # SOF + LEN + блок + CRC
    stats = {
        "bytes": len(data),
        "packets": len(packets),
        "dropped_bytes": len(data) - used - len(tail),
        "tail_bytes": len(tail),
        "no_lock": sum(1 for p in packets if not (p["locked"] and p["valid"])),
    }
    return rows, float(adc_max), stats


if __name__ == "__main__":
    # Самопроверка на синтетике DATA/SYNTHETIC/uart_log.txt (генератор —
    # src/syntetic/generator_data.py): разбор, сверка углов с отсчётами
    # квадрантов и обратная сборка блоков данных байт в байт.
    import math

    from scipy.special import erfinv

    from src.syntetic.generator_data import W_MM, build_packet, check_spec_example

    log_path = cfg.SYNTHETIC_DIR / "uart_log.txt"
    print("Контрольный пример §8 (кодировщик):", check_spec_example())

    data = read_uart_bytes(log_path)
    blocks, tail = extract_frames(data)
    packets = [parse_data_block(b) for b in blocks]
    print(f"{log_path}: {len(data)} байт, посылок {len(packets)}, хвост {len(tail)} байт")

    err = 0.0
    same_bytes = same_fields = 0
    for block, p in zip(blocks, packets):
        # Угол из отсчётов квадрантов по нож-модели против угла в посылке.
        if p["valid"]:
            _, _, rx, ry = quadrant_levels(p["adc"])
            for diff, angle in ((rx, p["x_deg"]), (ry, p["y_deg"])):
                d_mm = W_MM * float(erfinv(diff)) / math.sqrt(2)
                err = max(err, abs(math.degrees(math.atan(d_mm / cfg.FOC)) - angle))
        # Обратная сборка: разобранные поля → тот же блок данных.
        again = build_packet(
            p["uptime_ms"],
            p["x_deg"],
            p["y_deg"],
            p["adc"],
            locked=p["locked"],
            valid=p["valid"],
            quality=round(p["quality"] * 255),
            consec_valid=p["consec_valid"],
            consec_miss=p["consec_miss"],
            valid_percent=p["valid_percent"],
            frame_count=p["frame_count"],
            ext_range=p["ext_range"],
            mode=p["mode"],
        )
        same_bytes += again[3 : 3 + LEN_DATA] == block
        same_fields += parse_data_block(again[3 : 3 + LEN_DATA]) == p

    print(
        f"обратная сборка: поля {same_fields}/{len(blocks)}, "
        f"байты {same_bytes}/{len(blocks)} — байтовое расхождение бывает только "
        "на «минус нуле»: бит знака при угле 0°00'00\""
    )
    print(f"макс. расхождение угла с отсчётами квадрантов: {err:.4f}°")

    rows, adc_max, stats = read_uart_log(log_path)
    print("строки пайплайна:", stats)
    print("первая строка:", rows[0])
