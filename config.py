import os
import sys
from pathlib import Path


class SerialConfig:
    # PORT = '/dev/ttyUSB0'  # Измените на ваш порт

    BAUDRATE = 115200  # Измените на скорость вашего устройства (часто 9600, 115200)
    TIMEOUT = 1  # сек на чтение строки

    @property
    def PORT(self):
        if sys.platform.startswith("win"):
            return "COM6"
        return "/dev/ttyUSB0"


class DisplayConfig:
    SIZE_DISPLAY = 140  # px
    INTERVAL = 0.1  # сек между кадрами (только для данных с лога)
    MEASURE_HOLD = 3  # кадров усреднения после «w» в режиме measure (Задача №7)
    BASE_DIR = Path(os.path.dirname(__file__))

    @property
    def LOG_DIR(self):
        return self.BASE_DIR / "DATA" / "LOG"

    @property
    def DATA_DIR(self):
        return self.BASE_DIR / "DATA"

    @property
    def CALIB_DIR(self):
        return self.BASE_DIR / "DATA" / "CALIB"

    @property
    def CALIB_FILE(self):
        return self.CALIB_DIR / "CALIBRATE.json"

    @property
    def MEASURE_DIR(self):
        return self.BASE_DIR / "DATA" / "MEASURE"


class CalibrateConfig:
    # --- Калибровка нож-сканированием (Задача №4, AI_ANSWER.md §4) ---
    CALIB_CENTER_EPS = 0.05     # |x_norm|,|y_norm| для фиксации положения «центр»
    CALIB_SIDE_EPS = 0.5       # |x_norm| для фиксации «крайнее право/лево»
    CALIB_MIN_FRAC = 0.10       # мин. засветка (max доля квадранта) для валидной позиции
    CALIB_HOLD = 6              # кадров усреднения после подтверждения клавишей «w»


    D_MAX = 0.999   # |D| ближе к 1 — насыщение: erfinv → ∞, точка непригодна.
    EI_D_MIN = 1e-2 # Мин. |erfinv(D_i) − erfinv(D_j)| для устойчивого деления (точки слиплись).

    # Постоянный радиус из калибровки (Задача №5): физический w [мм] → пиксели.
    # Весь активный размер датчика DET_SIZE_MM отображается на весь дисплей
    # SIZE_DISPLAY, поэтому масштаб px/мм = SIZE_DISPLAY / DET_SIZE_MM.
    @property
    def CALIB_PX_PER_MM(self):
        return self.SIZE_DISPLAY / self.DET_SIZE_MM

class CompensationConfig:
    # --- Компенсационный полином (Задача №12/№13, DOCUMENTATION/AI_COMPENSATION.md) ---
    # Корректирует систематику нож-модели: углы θx/θy считаются полиномом от
    # u = erfinv(clip(D, ±COMP_DMAX)) — в этом базисе нож-модель почти линейна.
    COMP_DEGREE = 2               # степень полинома (6 коэф/ось). Анализ §12: оптимум 2.
    COMP_DMAX = 0.95              # |D| клампится сюда перед erfinv; точки |D|>DMAX
    #                               (насыщение erf) в фит не берём и в рантайме не корректируем.
    COMP_MAD_K = 3.0              # отбраковка выбросов: |остаток| > K·MAD (опечатки ввода углов).
    COMP_MIN_POINTS_PER_COEF = 3  # мин. точек на коэффициент, иначе предупреждение.

    @property
    def MEASURE_FILE(self):
        return self.MEASURE_DIR / "MEASURE.json"

    @property
    def COMP_FILE(self):
        # Лежит рядом с источником (MEASURE.json), как CALIBRATE.json в DATA/CALIB.
        return self.MEASURE_DIR / "COMPENSATION.json"


class SensorConfig:
    # Опорный максимум АЦП: raw 0 — max засвет, ADC_MAX — min засвет (яркость 0).
    # Устройство при отсутствии сигнала шлёт 4096 (на 1 выше 12-битного диапазона
    # 0..4095), поэтому ADC_MAX = 4096 — такой кадр даёт нулевую яркость по всем
    # датчикам и распознаётся как «нет сигнала» (точка в центре без окружности).
    ADC_MAX = 3500
    S_VAL_MAX = 40
    S_VAL_MIN = 3350

    COLUMNS = ("T", "s1", "s2", "s3", "s4", "v_x", "v_y")
    SENSOR_COLS = ("s1", "s2", "s3", "s4")

    LAMBDA_UM = 1.064  # длина волны источника λ, мкм (1064 нм)
    APERTURE_MM = 50.0  # диаметр входной апертуры D, мм
    DEFOCUS_MM = 17  # дефокус Δz (фокус на 17 мм перед датчиком), мм
    DET_SIZE_MM = 14.0  # mm

    FOC = 50  # mm расстояние от линзы до датчика с погрешностью +-3 мм

    # Задача №8: мин. число засвеченных квадрантов для измерения углов.
    # Порог «квадрант засвечен» по доле засветки (quadrant_fracs) — для подсчёта
    # nz в детекции потери позиции (Задача №8).
    FRAC_EPS = 0.01 # доля засветки, квадрант засчитывается засвеченным, если в нём есть хотя бы 1 % от полной засветки

    # nz < NZ_ANGLE_MIN (сигнал пропал на ≥2 квадрантах) → потеря позиции:
    # угол не измерить, точка у края дисплея (жёлтая), вместо углов — прочерк.
    NZ_ANGLE_MIN = 3


class Config(SerialConfig, DisplayConfig, SensorConfig, CalibrateConfig, CompensationConfig):
    pass


cfg = Config()
