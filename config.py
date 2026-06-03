import sys
import os
from pathlib import Path


class SerialConfig:
    # PORT = '/dev/ttyUSB0'  # Измените на ваш порт
    BAUDRATE = 115200      # Измените на скорость вашего устройства (часто 9600, 115200)
    TIMEOUT = 0.01          # сек на чтение строки

    @property
    def PORT(self):
        if sys.platform.startswith('win'):
            return 'COM6'
        return '/dev/ttyUSB0'


class DisplayConfig:
    SIZE_DISPLAY = 200  # px
    INTERVAL = 0.05     # сек между кадрами (для потока имеет смысл 0)
    BASE_DIR = Path(os.path.dirname(__file__))

    @property
    def LOG_DIR(self):
        return self.BASE_DIR / "DATA" / "LOG"

class SensorConfig:
    # Опорный максимум АЦП: raw 0 — max засвет, ADC_MAX — min засвет.
    # В putty.csv max наблюдалось ~3423, поэтому 4095 (12-bit) безопасный потолок.
    ADC_MAX = 4095
    S_VAL_MAX = 20
    S_VAL_MIN = 3500
    COLUMNS = ("s1", "s2", "s3", "s4", "v_x", "v_y")


class Config(SerialConfig, DisplayConfig, SensorConfig):
    pass


cfg = Config()
