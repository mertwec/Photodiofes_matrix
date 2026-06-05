from pathlib import Path

import click

from config import cfg
from src.calibration import run_calibration
from src.pipeline.get_single_point import df_to_raw_rows, make_point
from src.reader.file_reader import read_csv_log
from src.reader.log_writer import make_log_path, tee_to_csv
from src.reader.stream_reader import read_serial_rows
from src.visualization.display import display_points_stream

DEFAULT_FILE = Path("./DATA/putty.csv")


@click.group()
def cli():
    """Визуализатор направления засветки с фотодиодной матрицы."""


@cli.command("log")
@click.option(
    "--file", "file_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=DEFAULT_FILE, show_default=True,
    help="CSV-лог с показаниями датчиков.",
)
@click.option("--size", default=cfg.SIZE_DISPLAY, show_default=True,
              help="Размер дисплея в пикселях.")
@click.option("--interval", default=cfg.INTERVAL, show_default=True,
              help="Пауза между кадрами, сек.")
def log_cmd(file_path: Path, size: int, interval: float):
    """Проиграть точки из CSV-лога."""
    df = read_csv_log(file_path)
    rows, adc_max = df_to_raw_rows(df)

    frames = make_point(rows, size, adc_max,
                        val_max=cfg.S_VAL_MAX, val_min=cfg.S_VAL_MIN)
    # ts (время из T) рисуется живой подписью покадрово, см. Frame.ts / display.
    legend: dict = {
        "frames": len(df),
        # "adc_max": int(adc_max),
        # "s_max/min": f"{cfg.S_VAL_MAX}/{cfg.S_VAL_MIN}",
        # "quit": "q",
    }
    display_points_stream(frames, size=size, interval=interval, legend=legend)


@cli.command("stream")
@click.option("--port", default=cfg.PORT, show_default=True, help="UART-порт.")
@click.option("--baudrate", default=cfg.BAUDRATE, show_default=True, help="Скорость UART.")
@click.option("--size", default=cfg.SIZE_DISPLAY, show_default=True,
              help="Размер дисплея в пикселях.")
@click.option("--adc-max", "adc_max", default=cfg.ADC_MAX, show_default=True,
              help="Опорный максимум АЦП (raw 0 — max засвет, ADC_MAX — min засвет).")
@click.option("--log/--no-log", default=True, show_default=True,
              help="Сохранять принятые валидные строки в LOG_{timestamp}.csv.")
def stream_cmd(port: str, baudrate: int, size: int, adc_max: float, log: bool):
    """Читать данные с UART и отображать в реальном времени."""
    rows = read_serial_rows(port=port, baudrate=baudrate)
    if log:
        log_path = make_log_path(cfg.LOG_DIR)
        rows = tee_to_csv(rows, log_path)

    try:
        # Поправка №1: размер пятна считается покадрово из абсолютных долей засветки
        # s1..s4 по известным предельным значениям квадранта (cfg.S_VAL_MAX/S_VAL_MIN),
        # без привязки к v_x/v_y.
        frames = make_point(rows, size, adc_max,
                            val_max=cfg.S_VAL_MAX, val_min=cfg.S_VAL_MIN)

        legend: dict = {
            # "source": "UART",
            "port": port,
            # "baud": baudrate,
            "adc_max": int(adc_max),
            # "quit": "q",
        }
        # interval=0: темп задаёт сам UART (ser.readline блокируется до строки/таймаута).
        display_points_stream(frames, size=size, interval=0, legend=legend)

    finally:
        rows.close()


@cli.command("calibr")
@click.option("--port", default=cfg.PORT, show_default=True, help="UART-порт.")
@click.option("--baudrate", default=cfg.BAUDRATE, show_default=True, help="Скорость UART.")
@click.option("--size", default=cfg.SIZE_DISPLAY, show_default=True,
              help="Размер дисплея в пикселях.")
@click.option("--adc-max", "adc_max", default=cfg.ADC_MAX, show_default=True,
              help="Опорный максимум АЦП (raw 0 — max засвет, ADC_MAX — min засвет).")
def calibr_cmd(port: str, baudrate: int, size: int, adc_max: float):
    """Калибровка нож-сканированием (Задача №4): 3 фиксации → CALIB_*.json."""
    # 3 фиксации (центр + крайнее право/лево): записываем углы столика и сигналы
    # в CALIB_*.json. q/закрытие окна — отмена.
    rows = read_serial_rows(port=port, baudrate=baudrate)
    try:
        run_calibration(rows, adc_max, size, cfg.CALIB_DIR)
    finally:
        rows.close()  # освобождаем COM-порт


if __name__ == "__main__":
    cli()
