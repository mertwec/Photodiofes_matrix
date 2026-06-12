import csv
from pathlib import Path

import pandas as pd


def read_csv_log(file_path: Path | str):
    return pd.read_csv(file_path)
