from pathlib import Path

import click

from config import cfg
from src.pipeline.calibration import calibrate_phi_c
from src.pipeline.get_single_point import df_to_raw_rows, make_point, make_point_online
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

    calib = calibrate_phi_c(df)
    spot_r_px = calib.spot_r_px(size) if calib else None
    if calib:
        print(f"Калибровка пятна: {calib}")
    else:
        print("Калибровка пятна: нет v_x/v_y или данных свипа — пятно не показывается")

    frames = make_point(rows, size, adc_max, spot_r_px=spot_r_px)
    legend: dict = {
        "source": file_path.name,
        "frames": len(df),
        "adc_max": int(adc_max),
        **({"φc": f"{calib.phi_c:.2f}"} if calib else {}),
        "quit": "q",
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
@click.option("--calib-file", "calib_file", default=None, show_default=True,
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="CSV-лог со свипом для статической калибровки φc (игнорируется при --online-fit).")
@click.option("--online-fit / --no-online-fit", "online_fit", default=False,
              show_default=True,
              help="Динамически калибровать φc из входящих v_x/v_y в реальном времени.")
def stream_cmd(port: str, baudrate: int, size: int, adc_max: float,
               log: bool, calib_file: Path | None, online_fit: bool):
    """Читать данные с UART и отображать в реальном времени."""
    print(f"PORT: {port}, fit: {online_fit}, log: {log}")

    rows = read_serial_rows(port=port, baudrate=baudrate)
    log_path = None
    if log:
        log_path = make_log_path(cfg.LOG_DIR)
        rows = tee_to_csv(rows, log_path)

    if online_fit:
        if calib_file:
            click.echo("Примечание: --online-fit активен, --calib-file игнорируется.", err=True)
        print("[online-fit] Ожидание данных свипа для калибровки φc...")
        frames = make_point_online(rows, size, adc_max)
        calib_label = "online"
    else:
        calib = None
        if calib_file:
            calib = calibrate_phi_c(read_csv_log(calib_file))
            if calib:
                print(f"Калибровка пятна из {calib_file.name}: {calib}")
            else:
                print(f"Предупреждение: {calib_file.name} не содержит данных свипа — пятно не показывается")
        spot_r_px = calib.spot_r_px(size) if calib else None
        frames = make_point(rows, size, adc_max, spot_r_px=spot_r_px)
        calib_label = f"{calib.phi_c:.2f}" if calib else "off"

    legend: dict = {
        # "source": "UART",
        "port": port,
        # "baud": baudrate,
        # "adc_max": int(adc_max),
        "φc": calib_label,
        # "log": log_path.name if log_path else "off",
        # "quit": "q",
    }
    # interval=0: темп задаёт сам UART (ser.readline блокируется до строки/таймаута).
    display_points_stream(frames, size=size, interval=0, legend=legend)


if __name__ == "__main__":
    cli()
