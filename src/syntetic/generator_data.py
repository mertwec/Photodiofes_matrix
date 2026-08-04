"""
Генераторы синтетических данных фотодиодной матрицы.

Две независимые части:

1. `generate_random_data` — случайная матрица засветки (используется
   src/pipeline/syntetic_data.py).
2. Генератор синтетического лога обмена по UART по спецификации
   DOCUMENTATION/uart_interface_specification.pdf (изделие AGS 16.00.10,
   редакция 1.2). Формируются полноценные посылки по 36 байт:

       AA 55 | LEN=1F | блок данных 31 байт | CRC_hi CRC_lo

   Блок данных (§5): uptime_ms u32, углы X и Y как град/мин/сек, признак
   захвата, качество сигнала, счётчики достоверных/пропущенных измерений,
   доля достоверных, поле признаков (§6), счётчик измерений, отсчёты
   четырёх квадрантов adc_s1..adc_s4 (введены в редакции 1.1) и ступень
   усиления приёмного тракта gain (введена в редакции 1.2, §5.2).

   Числовые поля блока — младшим байтом вперёд, контрольная сумма
   CRC-16/CCITT-FALSE — старшим байтом вперёд, считается по байту LEN и
   всему блоку данных (§4).

Кодировщик сверен с контрольным примером §8: `check_spec_example()`
собирает посылку из значений примера и сравнивает её байт в байт с
приведённой в спецификации (включая CRC 0x57 0xA5).

Физика синтетики. Спецификация (§5.1) честно предупреждает, что по
отсчётам квадрантов угол изделия точно не восстановить: тёмновой уровень и
коэффициенты выравнивания квадрантов в посылку не передаются. Поэтому здесь
задача решается в обратную сторону и в модели ЭТОГО проекта: траектория даёт
истинные углы θx/θy → нож-модель даёт разностные сигналы
D = erf(√2·FOC·tg θ / w) → §5.1 наоборот даёт отсчёты квадрантов. Углы в
посылке — истинные (как их «вычислило» изделие), отсчёты согласованы с ними
по rx/ry с точностью до шума и квантования.

Усиление (§5.2) моделируется поверх этого: источник задаётся суммарной
засветкой при усилении ×1, ступень выбирается автоматически (самая высокая, на
которой Σ ещё не выходит за рабочий уровень), а отсчёты квадрантов пишутся уже
усиленными — как их выдаёт изделие. На rx/ry ступень не влияет (общий
множитель сокращается), поэтому углы остаются согласованными с отсчётами.

Запускать из корня репозитория: `python -m src.syntetic.generator_data`
(модуль импортирует config).
"""

import math
import random
import struct
from pathlib import Path
from pprint import pprint
from typing import Callable, Iterator, Sequence

from config import cfg
from src.utils.converter import deg_to_dms, dms_to_deg


def generate_random_data(dimension: int = 2) -> list[list[float]]:
    """
    generates a random matrix of photodiodes with values 0 or 1.

    param:
    dimension (int): Dimension of the photodiodes matrix (2x2 or 4x4).

    Returns:
    list: List of lists, representing the photodiodes matrix with random values 0 or 1.
    """

    return [[random.random() for _ in range(dimension)] for _ in range(dimension)]


# Константы протокола (кадр §3, поле признаков §6, отсчёты квадрантов §5.1)
# лежат в config.py::SensorConfig как cfg.UART_* — общие с парсером
# src/utils/parsing_uart.py. Ниже — только параметры самой синтетики.

# Рабочий уровень Σ относительной засветки четырёх квадрантов, к которому
# автомат усиления подводит сигнал. 4000 — как в примере §8 (даёт качество
# сигнала 62). При сильном смещении пятна в угол квадрант упирается в
# cfg.UART_BRIGHT_LEVEL.
TOTAL_COUNTS = 4000

# Σ засветки от источника на ступени 0 (усиление ×1), то есть «яркость» самого
# источника до усиления. 400 × 10 (ступень 2) = 4000 — режим примера §8.
SOURCE_COUNTS = 400

# Физический потолок Σ: все четыре квадранта на уровне максимальной засветки
# (§5.1). Выше тракт уходит в перегрузку — бит 5 поля ступени усиления (§5.2).
SAT_TOTAL = 4 * (cfg.UART_DARK_LEVEL - cfg.UART_BRIGHT_LEVEL)

# Радиус пятна w [мм] по уровню 1/e² — из зафиксированной калибровки
# DATA/CALIB/CALIBRATE.json (нож-сканирование, Задача №5).
W_MM = 4.06

# |D| выше этого порога считаем выходом за основную линейную зону:
# в примере §8 при rx = 0.5 бит EXT_RANGE уже установлен.
EXT_RANGE_D = 0.45

# Измерений изделия на одну посылку: внутренний темп измерений выше темпа
# выдачи (§5, «Момент измерения») — счётчик frame_count растёт быстрее.
MEAS_PER_PACKET = 5

# Внеочередная посылка при смене признака захвата (§1): интервал между
# соседними посылками может быть меньше периода выдачи.
LOCK_EVENT_MS = 7


def crc16_ccitt(data: bytes, crc: int = 0xFFFF) -> int:
    """
    CRC-16/CCITT-FALSE (§4, приложение А): полином 0x1021, начальное значение
    0xFFFF, без отражения входа/выхода и без финального сложения по модулю 2.
    """
    for x in data:
        crc ^= x << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc



def diffs_from_adc(
    adc: Sequence[int],
    dark_level: int = cfg.UART_DARK_LEVEL,
) -> tuple[float, float, int]:
    """
    Отсчёты квадрантов → разностные сигналы (§5.1).

        S_i = max(0, N0 − adc_i),  Σ = S1+S2+S3+S4
        rx = (S4+S3−S1−S2)/Σ,  ry = (S1+S4−S2−S3)/Σ

    Нумерация — со стороны приёма излучения: S1 левый верхний, S2 левый
    нижний, S3 правый нижний, S4 правый верхний. Возвращает (rx, ry, Σ);
    при Σ = 0 (нет засветки) разности нулевые.
    """
    s1, s2, s3, s4 = (max(0, dark_level - int(v)) for v in adc)
    total = s1 + s2 + s3 + s4
    if total == 0:
        return 0.0, 0.0, 0
    return (s4 + s3 - s1 - s2) / total, (s1 + s4 - s2 - s3) / total, total


def adc_from_diffs(
    rx: float,
    ry: float,
    total_counts: int = TOTAL_COUNTS,
    dark_level: int = cfg.UART_DARK_LEVEL,
    bright_level: int = cfg.UART_BRIGHT_LEVEL,
    noise: Callable[[], float] | None = None,
) -> tuple[int, int, int, int]:
    """
    Обратная задача к §5.1: разностные сигналы → отсчёты квадрантов s1..s4.

    Пятно делится перекрестием на доли (1±rx)/2 по горизонтали и (1±ry)/2 по
    вертикали, засветка квадранта — произведение долей (разделяемое гауссово
    пятно). Такое распределение даёт ровно заданные rx/ry, поэтому лог
    самосогласован: обратный расчёт по §5.1 возвращает исходные разности.

    Зависимость обратная: чем больше засветка, тем меньше отсчёт,
    adc_i = N0 − S_i, с ограничением снизу уровнем максимальной засветки
    bright_level. `noise` — генератор шума отсчётов (единиц АЦП).
    """
    fx_r, fx_l = (1.0 + rx) / 2.0, (1.0 - rx) / 2.0
    fy_t, fy_b = (1.0 + ry) / 2.0, (1.0 - ry) / 2.0
    # S1 — ЛВ, S2 — ЛН, S3 — ПН, S4 — ПВ (§5.1)
    weights = (fx_l * fy_t, fx_l * fy_b, fx_r * fy_b, fx_r * fy_t)

    out = []
    for weight in weights:
        value = dark_level - total_counts * max(0.0, weight)
        if noise is not None:
            value += noise()
        out.append(int(min(cfg.UART_ADC_FULL, max(bright_level, round(value)))))
    return tuple(out)  # type: ignore[return-value]


def signal_quality(adc: Sequence[int], dark_level: int = cfg.UART_DARK_LEVEL) -> int:
    """
    Качество сигнала 0…255 (§5): суммарная относительная засветка,
    нормированная на 4·4095. Проверка по примеру §8: Σ = 4000 → 62.
    """
    _, _, total = diffs_from_adc(adc, dark_level)
    return min(255, max(0, round(255.0 * total / (4.0 * cfg.UART_ADC_FULL))))


def select_gain_step(source_counts: float, target_counts: int = TOTAL_COUNTS) -> int:
    """
    Автоматический выбор ступени усиления (§5.2): самая высокая ступень, на
    которой суммарная засветка источника ещё не превышает рабочего уровня.

    source_counts — Σ засветки при усилении ×1. Для 400 и рабочего уровня 4000
    выбирается ступень 2 (относительное усиление 10) — режим примера §8. Если
    даже на ступени 0 сигнал выше рабочего уровня, остаётся ступень 0: понижать
    усиление дальше некуда, тракт уйдёт в перегрузку.
    """
    step = 0
    for i, rel in enumerate(cfg.UART_GAIN_RELATIVE):
        if source_counts * rel <= target_counts:
            step = i
    return step


def pack_gain(
    step: int,
    *,
    auto: bool = True,
    overload: bool = False,
    searching: bool = False,
    sum_fault: bool = False,
) -> int:
    """
    Поле ступени усиления (§5.2) → байт: номер ступени в битах 0…3 и признаки
    состояния тракта в битах 4…7. Значение 0x12 из примера §8 — ступень 2,
    выбранная автоматически.
    """
    gain = step & cfg.UART_G_STEP
    if auto:
        gain |= cfg.UART_G_AUTO
    if overload:
        gain |= cfg.UART_G_OVERLOAD
    if searching:
        gain |= cfg.UART_G_SEARCH
    if sum_fault:
        gain |= cfg.UART_G_SUM_FAULT
    return gain


def angle_to_diff(angle_deg: float, w_mm: float = W_MM, foc_mm: float = cfg.FOC) -> float:
    """
    Угол отклонения → разностный сигнал D по нож-модели (та же, что в
    src/pipeline/get_single_point.py::deflection_angles, но в прямую сторону):

        d = FOC · tg θ,   D = erf(√2 · d / w).
    """
    if w_mm <= 0:
        return 0.0
    d_mm = foc_mm * math.tan(math.radians(angle_deg))
    return math.erf(math.sqrt(2.0) * d_mm / w_mm)


def build_packet(
    uptime_ms: int,
    angle_x_deg: float,
    angle_y_deg: float,
    adc: Sequence[int],
    *,
    locked: bool = True,
    valid: bool = True,
    quality: int | None = None,
    consec_valid: int = 0,
    consec_miss: int = 0,
    valid_percent: int = 100,
    frame_count: int = 0,
    ext_range: bool = False,
    mode: int = 0,
    gain_step: int = 0,
    gain_auto: bool = True,
    overload: bool = False,
    searching: bool = False,
    sum_fault: bool = False,
) -> bytes:
    """
    Собирает одну посылку (36 байт при LEN = 31) по §3/§5.

    `quality=None` — качество считается из отсчётов по §5.1. Углы задаются в
    градусах со знаком: в поля градусов кладётся значение со знаком
    (дополнительный код), а собственно знак дублируется битами X_NEG/Y_NEG
    поля признаков (§7) — приёмник обязан брать знак именно оттуда.

    `gain_step` и признаки тракта (`gain_auto`, `overload`, `searching`,
    `sum_fault`) идут в поле ступени усиления (§5.2): без него отсчёты
    квадрантов не интерпретируются, так как сняты с разным усилением.
    """
    xd, xm, xs, x_neg = deg_to_dms(angle_x_deg)
    yd, ym, ys, y_neg = deg_to_dms(angle_y_deg)

    flags = (mode & 0x03) << 1
    if ext_range:
        flags |= cfg.UART_F_EXT_RANGE
    if x_neg:
        flags |= cfg.UART_F_X_NEG
    if y_neg:
        flags |= cfg.UART_F_Y_NEG
    if valid:
        flags |= cfg.UART_F_VALID

    block = struct.pack(
        cfg.UART_FMT31,
        uptime_ms & 0xFFFFFFFF,  # переполнение u32 ≈ через 49.7 суток (§5)
        -xd if x_neg else xd,
        xm,
        xs,
        -yd if y_neg else yd,
        ym,
        ys,
        1 if locked else 0,
        signal_quality(adc) if quality is None else quality,
        min(0xFFFF, consec_valid),
        min(0xFFFF, consec_miss),
        min(100, max(0, valid_percent)),
        flags,
        frame_count & 0xFFFFFFFF,
        *(int(v) & 0xFFFF for v in adc),
        pack_gain(
            gain_step,
            auto=gain_auto,
            overload=overload,
            searching=searching,
            sum_fault=sum_fault,
        ),
    )

    head = bytes((cfg.UART_LEN_DATA,)) + block  # CRC считается по LEN и блоку данных
    crc = crc16_ccitt(head)
    # CRC передаётся старшим байтом вперёд
    return cfg.UART_SOF + head + bytes((crc >> 8, crc & 0xFF))


# Контрольный пример из §8: 123456 мс, X +6°5'21", Y −0°28'39", захват есть,
# качество 62, 250 достоверных подряд, 0 пропусков, 98 % достоверных,
# 51234 измерения, флаги 0x33, отсчёты 1588, 1508, 508, 588, ступень усиления
# 0x12 (вторая ступень, выбрана автоматически).
SPEC_EXAMPLE_BYTES = bytes.fromhex(
    "AA551F"
    "40E20100"
    "060515"
    "001C27"
    "01"
    "3E"
    "FA00"
    "0000"
    "62"
    "33"
    "22C80000"
    "3406E405FC014C02"
    "12"
    "57A5"
)


def spec_example_packet() -> bytes:
    """Собирает посылку из значений контрольного примера §8."""
    return build_packet(
        123456,
        dms_to_deg(6, 5, 21),
        dms_to_deg(0, 28, 39, negative=True),
        (1588, 1508, 508, 588),
        locked=True,
        valid=True,
        consec_valid=250,
        consec_miss=0,
        valid_percent=98,
        frame_count=51234,
        ext_range=True,
        mode=1,  # расчёт с табличной коррекцией
        gain_step=2,  # относительное усиление 10
        gain_auto=True,
    )


def check_spec_example() -> bool:
    """True, если кодировщик воспроизводит пример §8 байт в байт (с CRC)."""
    return spec_example_packet() == SPEC_EXAMPLE_BYTES


def generate_uart_packets(
    frames: int = 400,
    *,
    period_ms: int = 50,
    uptime_start_ms: int = 123_456,
    amp_x_deg: float = 1.0,
    amp_y_deg: float = 0.6,
    period_x_s: float = 6.0,
    period_y_s: float = 9.0,
    w_mm: float = W_MM,
    foc_mm: float = cfg.FOC,
    source_counts: int = SOURCE_COUNTS,
    gain_step: int | None = None,
    noise_counts: float = 2.0,
    dropout: int = 0,
    seed: int | None = 20260731,
    angles_fn: Callable[[float], tuple[float, float]] | None = None,
) -> Iterator[bytes]:
    """
    Поток синтетических посылок (по 36 байт) — как их выдавало бы изделие.

    Источник ходит по фигуре Лиссажу: θx = amp_x·sin(2π t/period_x),
    θy = amp_y·sin(2π t/period_y + π/3); `angles_fn(t_sec) -> (θx, θy)`
    подменяет траекторию целиком. Углы переводятся в разностные сигналы
    нож-моделью (`angle_to_diff`), разности — в отсчёты квадрантов
    (`adc_from_diffs`) с шумом noise_counts (СКО, единиц АЦП).

    `source_counts` — Σ засветки от источника при усилении ×1. Ступень усиления
    выбирается автоматически (`select_gain_step`, §5.2) и пишется в посылку;
    отсчёты квадрантов усилены выбранной ступенью, поэтому читать их без неё
    нельзя. `gain_step` фиксирует ступень принудительно (признак
    автоматического выбора при этом снимается); если сигнал на ней выходит за
    физический потолок SAT_TOTAL, квадранты насыщаются и ставится бит
    перегрузки — угол такой посылки недостоверен (§5.2).

    `dropout` — сколько кадров в середине лога идут без источника: отсчёты
    садятся на тёмновой уровень, качество ~0, захвата нет, бит VALID снят,
    поля углов не определены (пишутся нулями, §9), растёт consec_miss, а тракт
    переходит в поиск сигнала — ступень наращивается по одной на посылку до
    максимальной, с установленным битом поиска (§5.2). На смене признака
    захвата посылка формируется внеочередно — интервал между соседними
    посылками там меньше period_ms (§1).

    Служебные поля ведутся сквозным счётом: uptime_ms, frame_count (темп
    измерений выше темпа выдачи, MEAS_PER_PACKET на посылку), consec_valid /
    consec_miss и доля достоверных измерений за всё время.
    """
    rnd = random.Random(seed)
    noise = (lambda: rnd.gauss(0.0, noise_counts)) if noise_counts > 0 else None

    lost_from = max(0, (frames - dropout) // 2) if dropout > 0 else frames
    lost_to = lost_from + max(0, dropout)

    gain_auto = gain_step is None
    work_step = select_gain_step(source_counts) if gain_auto else gain_step
    work_step = min(max(0, work_step), len(cfg.UART_GAIN_RELATIVE) - 1)
    step = work_step

    uptime_ms = uptime_start_ms
    frame_count = MEAS_PER_PACKET
    consec_valid = consec_miss = valid_total = 0
    prev_locked: bool | None = None

    for i in range(frames):
        locked = not (lost_from <= i < lost_to)

        if prev_locked is not None:
            # Смена признака захвата → внеочередная выдача (§1).
            dt = period_ms if locked == prev_locked else LOCK_EVENT_MS
            uptime_ms += dt
            frame_count += max(1, round(MEAS_PER_PACKET * dt / period_ms))
        prev_locked = locked

        t_sec = (uptime_ms - uptime_start_ms) / 1000.0
        if locked:
            if angles_fn is not None:
                angle_x, angle_y = angles_fn(t_sec)
            else:
                angle_x = amp_x_deg * math.sin(2 * math.pi * t_sec / period_x_s)
                angle_y = amp_y_deg * math.sin(
                    2 * math.pi * t_sec / period_y_s + math.pi / 3
                )
            rx = angle_to_diff(angle_x, w_mm, foc_mm)
            ry = angle_to_diff(angle_y, w_mm, foc_mm)
            # Сигнал есть — тракт на рабочей ступени; отсчёты уже усилены.
            step = work_step
            total_counts = source_counts * cfg.UART_GAIN_RELATIVE[step]
            adc = adc_from_diffs(rx, ry, total_counts, noise=noise)
            overload = total_counts > SAT_TOTAL
            searching = False
            ext_range = max(abs(rx), abs(ry)) > EXT_RANGE_D
            consec_valid = min(0xFFFF, consec_valid + 1)
            consec_miss = 0
            valid_total += 1
        else:
            # Источника нет: все квадранты на тёмновом уровне, углы не определены,
            # тракт ищет сигнал и последовательно наращивает усиление (§5.2).
            angle_x = angle_y = 0.0
            adc = adc_from_diffs(0.0, 0.0, 0, noise=noise)
            step = min(step + 1, len(cfg.UART_GAIN_RELATIVE) - 1) if gain_auto else step
            overload = False
            searching = True
            ext_range = False
            consec_miss = min(0xFFFF, consec_miss + 1)
            consec_valid = 0

        yield build_packet(
            uptime_ms,
            angle_x,
            angle_y,
            adc,
            locked=locked,
            valid=locked,
            consec_valid=consec_valid,
            consec_miss=consec_miss,
            valid_percent=round(100.0 * valid_total / (i + 1)),
            frame_count=frame_count,
            ext_range=ext_range,
            # Расчёт с табличной коррекцией вне основной линейной зоны (§6).
            mode=1 if ext_range else 0,
            gain_step=step,
            gain_auto=gain_auto,
            overload=overload,
            searching=searching,
        )


def generate_uart_log(
    path: str | Path | None = None,
    frames: int = 400,
    *,
    one_line: bool = False,
    **kwargs,
) -> dict:
    """
    Пишет синтетический лог обмена по UART в текстовый hex-дамп.

    Формат файла — как у снятого с линии DATA/UART_LOG/log.txt: байты в
    верхнем регистре через пробел. По умолчанию одна посылка на строку (36
    байт, 108 символов), `one_line=True` — весь поток одной строкой, как в
    реальном дампе. Пробелы и переводы строк одинаково съедаются
    `bytes.fromhex`, так что байтовый поток от разбивки не зависит.

    `path=None` → cfg.SYNTHETIC_DIR/uart_log.txt. Остальные параметры
    прокидываются в `generate_uart_packets`. Возвращает сводку по логу.
    """
    out_path = Path(path) if path is not None else cfg.SYNTHETIC_DIR / "uart_log.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    packets = list(generate_uart_packets(frames, **kwargs))
    dump = " ".join(p.hex(" ").upper() for p in packets) if one_line else "\n".join(
        p.hex(" ").upper() for p in packets
    )
    out_path.write_text(dump + "\n", encoding="ascii")

    # Отсчёты квадрантов лежат в конце блока данных (смещение 22 в блоке, 25 в
    # посылке), сразу за ними — байт ступени усиления (30 и 33). Упёршийся в
    # bright_level квадрант — насыщение: rx/ry в таком кадре уже не совпадут с
    # углом, о чём есть смысл сообщить.
    bright = cfg.UART_BRIGHT_LEVEL
    saturated = sum(1 for p in packets if min(struct.unpack("<4H", p[25:33])) <= bright)

    return {
        "path": out_path,
        "packets": len(packets),
        "bytes": sum(len(p) for p in packets),
        "saturated": saturated,
        "gain_steps": sorted({p[33] & cfg.UART_G_STEP for p in packets}),
        "overload": sum(1 for p in packets if p[33] & cfg.UART_G_OVERLOAD),
        **verify_uart_log(out_path),
    }


def verify_uart_log(path: str | Path) -> dict:
    """
    Самопроверка hex-дампа: ищет синхропоследовательность, берёт границы
    посылки из поля LEN и сверяет контрольную сумму (§9). Возвращает число
    посылок с верной CRC, число байт, отброшенных при поиске синхронизации,
    и длину недочитанного хвоста.
    """
    data = bytes.fromhex(Path(path).read_text(encoding="ascii"))

    ok = skipped = 0
    i = 0
    while True:
        i = data.find(cfg.UART_SOF, i)
        if i < 0:
            return {"crc_ok": ok, "resync_bytes": skipped, "tail_bytes": 0}
        if i + 3 > len(data):
            return {"crc_ok": ok, "resync_bytes": skipped, "tail_bytes": len(data) - i}
        ln = data[i + 2]
        end = i + 3 + ln + 2
        if end > len(data):
            return {"crc_ok": ok, "resync_bytes": skipped, "tail_bytes": len(data) - i}
        crc_rx = (data[end - 2] << 8) | data[end - 1]
        if crc16_ccitt(data[i + 2 : end - 2]) == crc_rx:
            ok += 1
            i = end
        else:
            # Ложная синхронизация: 0xAA 0x55 могли встретиться внутри блока.
            skipped += 1
            i += 1


if __name__ == "__main__":
    data_phd_2x2 = generate_random_data(2)
    data_phd_4x4 = generate_random_data(4)

    print("Generated 2x2 photodiodes matrix:")
    pprint(data_phd_2x2)

    print("\nGenerated 4x4 photodiodes matrix:")
    pprint(data_phd_4x4)

    # Лог отсюда не пишется, чтобы не затирать DATA/SYNTHETIC/uart_log.txt:
    # для генерации есть `python cli_synt.py uart-log`.
    print("\nКонтрольный пример §8 воспроизведён:", check_spec_example())
