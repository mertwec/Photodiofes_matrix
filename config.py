
class SerialConfig:
    PORT = '/dev/ttyUSB0'  # Измените на ваш порт
    BAUDRATE = 115200      # Измените на скорость вашего устройства (часто 9600, 115200)
    TIMEOUT = 1.0          # сек на чтение строки


class DisplayConfig:
    SIZE_DISPLAY = 200  # px
    INTERVAL = 0.05     # сек между кадрами (для потока имеет смысл 0)


class SensorConfig:
    # Опорный максимум АЦП: raw 0 — max засвет, ADC_MAX — min засвет.
    # В putty.csv max наблюдалось ~3423, поэтому 4095 (12-bit) безопасный потолок.
    ADC_MAX = 4095
    COLUMNS = ("s1", "s2", "s3", "s4", "v_x", "v_y")


class Config(SerialConfig, DisplayConfig, SensorConfig):
    pass


cfg = Config()
