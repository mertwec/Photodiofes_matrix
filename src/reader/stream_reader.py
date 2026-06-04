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
    в новом формате: T,s1,s2,s3,s4,v_x,v_y, где T — время с детектора
    (первое поле, пробрасывается как есть для записи в лог).

    Битые/неполные строки и строку заголовка (нечисловые поля) пропускает.
    Закрывает порт при выходе из генератора (GeneratorExit / исключение / EOF).

    :yield: dict со значениями {'T','s1','s2','s3','s4', и опционально 'v_x','v_y'}.
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

            parts = line.split(",")
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
