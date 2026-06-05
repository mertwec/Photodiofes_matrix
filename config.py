import sys
import os
from pathlib import Path


class SerialConfig:
    # PORT = '/dev/ttyUSB0'  # Измените на ваш порт

    BAUDRATE = 115200      # Измените на скорость вашего устройства (часто 9600, 115200)
    TIMEOUT = 0.1          # сек на чтение строки

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
    # Опорный максимум АЦП: raw 0 — max засвет, ADC_MAX — min засвет (яркость 0).
    # Устройство при отсутствии сигнала шлёт 4096 (на 1 выше 12-битного диапазона
    # 0..4095), поэтому ADC_MAX = 4096 — такой кадр даёт нулевую яркость по всем
    # датчикам и распознаётся как «нет сигнала» (точка в центре без окружности).
    ADC_MAX = 4096
    S_VAL_MAX = 0
    S_VAL_MIN = 3500
    COLUMNS = ("T", "s1", "s2", "s3", "s4", "v_x", "v_y")


class Config(SerialConfig, DisplayConfig, SensorConfig):
    pass


cfg = Config()
