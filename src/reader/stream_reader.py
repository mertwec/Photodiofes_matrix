from typing import Generator

import serial

from config import cfg


def read_serial_rows(
    port: str | None = None,
    baudrate: int | None = None,
    timeout: float | None = None,
) -> Generator[dict, None, None]:
    """
    Подключается к UART и построчно отдаёт распарсенные строки датчиков
    в формате как в DATA/putty.csv: s1,s2,s3,s4,v_x,v_y.

    Битые/неполные строки и строку заголовка (нечисловые поля) пропускает.
    Закрывает порт при выходе из генератора (GeneratorExit / исключение / EOF).

    :yield: dict со значениями {'s1','s2','s3','s4', и опционально 'v_x','v_y'}.
    """
    port = port or cfg.PORT
    baudrate = baudrate or cfg.BAUDRATE
    timeout = cfg.TIMEOUT if timeout is None else timeout

    with serial.Serial(port, baudrate, timeout=timeout) as ser:
        print(f"Подключено к {port} @ {baudrate} (timeout={timeout}s)")
        while True:
            raw = ser.readline()
            print(raw)
            if not raw:
                continue  # таймаут чтения — ждём следующий кадр

            line = raw.decode("ascii", errors="ignore").strip()
            if not line:
                continue

            parts = line.split(";")
            if len(parts) < 4:
                continue

            try:
                s1, s2, s3, s4 = (float(p) for p in parts[:4])
            except ValueError:
                continue  # заголовок или мусор в строке

            row: dict = {"s1": s1, "s2": s2, "s3": s3, "s4": s4}
            if len(parts) >= 6:
                try:
                    row["v_x"] = float(parts[4])
                    row["v_y"] = float(parts[5])
                except ValueError:
                    pass
            yield row
