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
    INTERVAL = 0.1     # сек между кадрами (для потока имеет смысл 0)
    BASE_DIR = Path(os.path.dirname(__file__))

    @property
    def LOG_DIR(self):
        return self.BASE_DIR / "DATA" / "LOG"

    # --- Калибровка нож-сканированием (Задача №4, AI_ANSWER.md §4) ---
    CALIB_CENTER_EPS = 0.08   # |x_norm|,|y_norm| для фиксации положения «центр»
    CALIB_SIDE_EPS = 0.45     # |x_norm| для фиксации «крайнее право/лево»
    CALIB_MIN_FRAC = 0.10     # мин. засветка (max доля квадранта) для валидной позиции
    CALIB_HOLD = 8            # кадров стабильного удержания позиции → фиксация

    @property
    def CALIB_DIR(self):
        return self.BASE_DIR / "DATA" / "CALIB"

class SensorConfig:
    # Опорный максимум АЦП: raw 0 — max засвет, ADC_MAX — min засвет (яркость 0).
    # Устройство при отсутствии сигнала шлёт 4096 (на 1 выше 12-битного диапазона
    # 0..4095), поэтому ADC_MAX = 4096 — такой кадр даёт нулевую яркость по всем
    # датчикам и распознаётся как «нет сигнала» (точка в центре без окружности).
    ADC_MAX = 4096
    S_VAL_MAX = 0
    S_VAL_MIN = 3500
    COLUMNS = ("T", "s1", "s2", "s3", "s4", "v_x", "v_y")
    SENSOR_COLS = ("s1", "s2", "s3", "s4")
    FOV = 50e-3 # m

    # --- Геометрический решатель радиуса пятна (Поправка №2, AI_ANSWER.md,
    #     DOCUMENTATION/r2_estimation_algorithm.pdf). Совместный фит (x, y, R2)
    #     по 4 площадям пересечения пятна с квадрантами детектора (R1=1). ---
    N_INT = 500             # полос интегрирования прямой задачи forward_areas
    NM_MAXITER = 2000       # макс. итераций Нелдера–Мида (на один старт)
    NM_FATOL = 1e-12        # порог сходимости симплекса по остатку F
    R2_CLIP = (0.02, 1.95)  # физически допустимый диапазон R2 (в единицах R1=1)
    F_RELIABLE = 1e-3       # остаток F выше — оценка ненадёжна (круг рисуется серым)
    FRAC_EPS = 0.01         # порог «квадрант засвечен» для подсчёта nz


class Config(SerialConfig, DisplayConfig, SensorConfig):
    pass


cfg = Config()
