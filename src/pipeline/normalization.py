import pandas as pd

SENSOR_COLS = ["s1", "s2", "s3", "s4"]


def normalize_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Приведение значений датчиков (0 — max засвет, ADC_MAX — min засвет)
    к виду [0, 1], где 0 — min засвет, 1 — max засвет.

    Делитель — единый максимум по всем 4 датчикам, иначе теряется
    относительная амплитуда между s1..s4, по которой и считается направление.
    """
    adc_max = df[SENSOR_COLS].to_numpy().max()
    df[SENSOR_COLS] = 1 - df[SENSOR_COLS] / adc_max
    return df
