import re
import threading
import time
from typing import Generator
import serial

from config import cfg
from src.utils.parsing_uart import extract_frames, parse_data_block, rows_from_packets

# Устройство шлёт поля через ';' (06800606;0018;0036;0111;0153;-0.079;-0.024),
# но логи/CSV используют ','. Принимаем оба разделителя.
_FIELD_SEP = re.compile(r"[;,]")


def read_serial_rows(
    port: str | None = None,
    baudrate: int | None = None,
    timeout: float | None = None,
    flush_event: threading.Event | None = None,
) -> Generator[dict, None, None]:
    """
    Подключается к UART и построчно отдаёт распарсенные строки датчиков
    в формате T<sep>s1<sep>s2<sep>s3<sep>s4<sep>v_x<sep>v_y, где разделитель
    sep — ';' (как шлёт устройство) или ',' (CSV-совместимый). T — время с
    детектора (первое поле, пробрасывается как есть для записи в лог).

    Битые/неполные строки и строку заголовка (нечисловые поля) пропускает.
    Закрывает порт при выходе из генератора (GeneratorExit / исключение / EOF).

    flush_event — запрос сброса входного буфера порта: пока потребитель занят
    (например, оператор вводит углы в measure), устройство продолжает слать
    данные и буфер копится — после set() накопленное отбрасывается и следующая
    строка читается «с этого момента», а не из хвоста буфера. Событие
    сбрасывается здесь же; первая строка после сброса может быть обрезана —
    её отбраковывает обычный парсинг.

    :yield: dict со значениями {'T','s1','s2','s3','s4', и опционально 'v_x','v_y'}.
    """
    port = port or cfg.PORT
    baudrate = baudrate or cfg.BAUDRATE
    timeout = cfg.TIMEOUT if timeout is None else timeout

    with serial.Serial(port, baudrate, timeout=timeout) as ser:
        print(f"Подключено к {port} @ {baudrate} (timeout={timeout}s)")
        while True:
            if flush_event is not None and flush_event.is_set():
                ser.reset_input_buffer()
                flush_event.clear()
            raw = ser.readline()
            if not raw:
                continue  # таймаут чтения — ждём следующий кадр

            line = raw.decode("ascii", errors="ignore").strip()
            if not line:
                continue

            parts = _FIELD_SEP.split(line)
            if len(parts) < 5:
                continue  # нужно минимум T + 4 датчика

            try:
                s1, s2, s3, s4 = (float(p) for p in parts[1:5])
            except ValueError:
                continue  # заголовок или мусор в строке

            # T — время с детектора (первое поле), храним строкой как пришло,
            # чтобы не потерять исходный формат/точность при записи в лог.
            row: dict = {"T": parts[0], "s1": s1, "s2": s2, "s3": s3, "s4": s4}
            if len(parts) >= 7:
                try:
                    row["v_x"] = float(parts[5])
                    row["v_y"] = float(parts[6])
                except ValueError:
                    pass
            yield row


def read_serial_uart(
    port: str | None = None,
    baudrate: int | None = None,
    timeout: float | None = None,
    flush_event: threading.Event | None = None,
    dark_level: int = cfg.UART_DARK_LEVEL,
    adc_max: float | None = None,
) -> Generator[dict, None, None]:
    """
    Подключается к UART и отдаёт строки датчиков из ДВОИЧНЫХ посылок (Задача №16).

    Формат — DOCUMENTATION/uart_interface_specification.pdf (редакция 1.1),
    разбор целиком в src/utils/parsing_uart.py. Отличие от read_serial_rows
    только в источнике: здесь не строки ASCII, а поток байт, из которого
    посылки выделяются по синхробайтам + сошедшейся CRC (`extract_frames`).
    Наружу идут те же словари {'T','s1'..'s4','v_x','v_y'}, что и у текстового
    ридера, — дальше пайплайн общий.

    Читается всё, что уже пришло в порт (ser.in_waiting), но не меньше одного
    байта: чтение блокируется максимум на timeout, поэтому окно matplotlib
    успевает реагировать на 'q'. Недочитанный хвост буфера сохраняется между
    итерациями — посылка почти всегда приходит несколькими порциями.

    dark_level/adc_max — перенос шкалы отсчётов в шкалу пайплайна
    (см. parsing_uart.adc_to_raw); по умолчанию тёмновой уровень из
    спецификации и cfg.ADC_MAX.

    flush_event — как в read_serial_rows: сброс входного буфера порта по запросу
    потребителя (плюс сбрасывается недочитанный хвост, чтобы не склеить обрывок
    старой посылки с новыми данными).

    :yield: dict со значениями {'T','s1','s2','s3','s4','v_x','v_y'}.
    """
    port = port or cfg.PORT
    baudrate = baudrate or cfg.BAUDRATE
    timeout = cfg.TIMEOUT if timeout is None else timeout
    adc_max = cfg.ADC_MAX if adc_max is None else adc_max

    with serial.Serial(port, baudrate, timeout=timeout) as ser:
        print(f"Подключено к {port} @ {baudrate} (timeout={timeout}s), формат UART")
        buf = b""
        while True:
            if flush_event is not None and flush_event.is_set():
                ser.reset_input_buffer()
                buf = b""
                flush_event.clear()

            chunk = ser.read(max(1, ser.in_waiting))
            if not chunk:
                continue  # таймаут чтения — ждём следующую порцию байт
            buf += chunk

            blocks, tail = extract_frames(buf)
            # Синхробайты могли разорваться между порциями: одиночный 0xAA в
            # конце буфера как SOF не найдётся и был бы отброшен вместе с
            # мусором — сохраняем его до следующего чтения.
            if not tail and buf.endswith(cfg.UART_SOF[:1]):
                tail = cfg.UART_SOF[:1]
            buf = tail

            packets = [p for p in map(parse_data_block, blocks) if p is not None]
            yield from rows_from_packets(packets, dark_level, adc_max)


def _has_text_row(buf: bytes) -> bool:
    """
    Есть ли в буфере ЦЕЛАЯ строка ASCII-формата T<sep>s1..s4[<sep>v_x<sep>v_y]?

    Критерий тот же, что у read_serial_rows: не меньше 5 полей и поля 1..4
    разбираются как числа. Строка заголовка и мусор не считаются — значит ждём
    дальше, а не решаем формат по обрывку.
    """
    text = buf.decode("ascii", errors="ignore")
    for line in text.split("\n")[:-1]:  # хвост после последнего \n — недочитан
        parts = _FIELD_SEP.split(line.strip())
        if len(parts) < 5:
            continue
        try:
            [float(p) for p in parts[1:5]]
        except ValueError:
            continue  # заголовок или мусор
        return True
    return False


def detect_serial_format(
    port: str | None = None,
    baudrate: int | None = None,
    timeout: float | None = None,
    wait: float | None = None,
    notice_every: float = 5.0,
) -> str:
    """
    Определяет, что шлёт устройство в порт (Задача №16): 'uart' или 'text'.

    Слушает порт и ЖДЁТ, пока формат не станет однозначным:

    * набралась целая посылка с сошедшейся CRC → 'uart';
    * набралась целая строка ASCII вида T;s1..s4[;v_x;v_y] → 'text'.

    Обрывки, заголовок и мусор решением не считаются — порт держится открытым до
    полноценных данных, как в первоначальном stream (устройство может молчать
    сколько угодно: интервал между посылками непостоянен, §9). Прерывание —
    Ctrl+C. Каждые notice_every секунд печатается напоминание, что ждём данные.

    wait — предел ожидания в секундах; None (по умолчанию) — ждать бесконечно.
    По истечении предела возвращается 'text' с предупреждением.

    Порт открывается на время определения и закрывается — вызывающий код
    открывает его заново нужным ридером; прочитанные здесь байты теряются (на
    старте это несколько кадров).
    """
    port = port or cfg.PORT
    baudrate = baudrate or cfg.BAUDRATE
    timeout = cfg.TIMEOUT if timeout is None else timeout

    buf = b""
    start = time.monotonic()
    notice = start + notice_every
    with serial.Serial(port, baudrate, timeout=timeout) as ser:
        while True:
            buf += ser.read(max(1, ser.in_waiting))

            blocks, _ = extract_frames(buf)
            if blocks:
                return "uart"
            if _has_text_row(buf):
                return "text"

            now = time.monotonic()
            if wait is not None and now - start >= wait:
                print(
                    f"Внимание: за {wait:g} с из {port} не пришло распознаваемых "
                    "данных — читаем как ASCII-строки."
                )
                return "text"
            if now >= notice:
                got = "тишина" if not buf else f"{len(buf)} байт без целой посылки"
                print(f"Ждём данные из {port}: {got}. Прервать — Ctrl+C.")
                notice = now + notice_every

            # Целая посылка ≤ 260 байт, целая строка короче: держим только хвост,
            # чтобы буфер не рос на долгом ожидании (мусор всё равно не решение).
            if len(buf) > 8192:
                buf = buf[-1024:]
