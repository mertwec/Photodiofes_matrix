import threading
from pathlib import Path

import click

from config import cfg
from src.calibration import run_calibration
from src.measure import run_measure
from src.pipeline.calib_radius import info_calib_radius
from src.pipeline.get_single_point import df_to_raw_rows, make_point
from src.pipeline.poly_compensation import load_compensation
from src.reader.file_reader import read_csv_log
from src.reader.log_writer import make_log_path, tee_to_csv
from src.reader.stream_reader import read_serial_rows
from src.visualization.display import display_points_stream


@click.group()
def cli():
    """Визуализатор направления засветки с фотодиодной матрицы."""


def _comp_model(comps: bool):
    """Компенсационный полином углов (Задача №13) для make_point, если включён --comps.

    Возвращает CompensationModel или None (нет файла / выключено) — тогда углы
    считаются нож-моделью, как раньше. Печатает статус при старте.
    """
    if not comps:
        print("[Компенсация] выключена (--no-comps): углы по нож-модели.")
        return None
    model = load_compensation()
    if model is None:
        print(
            "[Компенсация] COMPENSATION.json не найден — углы по нож-модели "
            "(построить: python cli_model.py fit)."
        )
        return None
    loo = model.loo_rmse_deg or {}
    tail = f", LOO≈{loo.get('x')}°/{loo.get('y')}°" if loo else ""
    print(
        f"[Компенсация] полином степени {model.degree} применён к углам "
        f"(|D|≤{model.d_max}{tail})."
    )
    return model


@cli.command("log")
@click.option(
    "--file",
    "file_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=Path("./DATA/putty.csv"),
    show_default=True,
    help="CSV-лог с показаниями датчиков.",
)
@click.option(
    "--size",
    default=cfg.SIZE_DISPLAY,
    show_default=True,
    help="Размер дисплея в пикселях.",
)
@click.option(
    "--comps/--no-comps",
    default=True,
    show_default=True,
    help="Применять компенсационный полином (Задача №13) к расчёту углов.",
)
def log_cmd(file_path: Path, size: int, comps: bool):
    """Проиграть точки из CSV-лога."""
    df = read_csv_log(file_path)
    rows, adc_max = df_to_raw_rows(df)

    frames = make_point(
        rows,
        size,
        adc_max,
        val_max=cfg.S_VAL_MAX,
        val_min=cfg.S_VAL_MIN,
        fixed_radius=info_calib_radius(),
        comp_model=_comp_model(comps),
    )
    # ts (время из T) рисуется живой подписью покадрово, см. Frame.ts / display.
    legend: dict = {
        "frames": len(df),
        # "adc_max": int(adc_max),
        # "s_max/min": f"{cfg.S_VAL_MAX}/{cfg.S_VAL_MIN}",
        # "quit": "q",
    }
    display_points_stream(frames, size=size, interval=cfg.INTERVAL, legend=legend)


@cli.command("stream")
@click.option("--port", default=cfg.PORT, show_default=True, help="UART-порт.")
@click.option(
    "--baudrate", default=cfg.BAUDRATE, show_default=True, help="Скорость UART."
)
@click.option(
    "--log/--no-log",
    default=True,
    show_default=True,
    help="Сохранять принятые валидные строки в LOG_{timestamp}.csv.",
)
@click.option(
    "--comps/--no-comps",
    default=True,
    show_default=True,
    help="Применять компенсационный полином (Задача №13) к расчёту углов.",
)
def stream_cmd(port: str, baudrate: int, log: bool, comps: bool):
    """Читать данные с UART и отображать в реальном времени."""
    adc_max = cfg.ADC_MAX
    size = cfg.SIZE_DISPLAY

    rows = read_serial_rows(port=port, baudrate=baudrate)
    if log:
        log_path = make_log_path(cfg.LOG_DIR)
        rows = tee_to_csv(rows, log_path)

    try:
        # Задача №5: если есть калибровка — радиус пятна постоянный (из
        # нож-сканирования); иначе круг не рисуется. Углы: компенсационный полином
        # (Задача №13) при --comps, иначе нож-модель (нужна калибровка).
        frames = make_point(
            rows,
            size,
            adc_max,
            val_max=cfg.S_VAL_MAX,
            val_min=cfg.S_VAL_MIN,
            fixed_radius=info_calib_radius(),
            comp_model=_comp_model(comps),
        )

        legend: dict = {
            "port": port,
            # "quit": "q",
        }
        # interval=0: темп задаёт сам UART (ser.readline блокируется до строки/таймаута).
        display_points_stream(frames, size=size, interval=0, legend=legend)

    finally:
        rows.close()


@cli.command("calibr")
@click.option("--port", default=cfg.PORT, show_default=True, help="UART-порт.")
@click.option(
    "--baudrate", default=cfg.BAUDRATE, show_default=True, help="Скорость UART."
)
def calibr_cmd(port: str, baudrate: int):
    """Калибровка нож-сканированием (Задача №4): 3 фиксации → CALIB_*.json."""
    # 3 фиксации (центр + крайнее право/лево): записываем углы столика и сигналы
    # в CALIBRATE.json. q/закрытие окна — отмена.
    rows = read_serial_rows(port=port, baudrate=baudrate)
    try:
        run_calibration(rows, cfg.ADC_MAX, size=cfg.SIZE_DISPLAY, out_dir=cfg.CALIB_DIR)
    finally:
        rows.close()  # освобождаем COM-порт


@cli.command("measure")
@click.option("--port", default=cfg.PORT, show_default=True, help="UART-порт.")
@click.option(
    "--baudrate", default=cfg.BAUDRATE, show_default=True, help="Скорость UART."
)
@click.option("--test/--no-test", default=False, show_default=False, help="Test by log")
@click.option(
    "--continue",
    "do_continue",
    is_flag=True,
    default=False,
    help="Продолжить запись: подгрузить точки из MEASURE.json и дописывать.",
)
def measure_cmd(port: str, baudrate: int, test: bool, do_continue: bool):
    """Режим фиксации данных (Задача №7): g — точка + углы x/y, JSON пишется сам."""
    # Поток как в stream, но без пятна: «g» фиксирует s1..s4 (усреднение
    # cfg.MEASURE_HOLD кадров) + углы x/y (ввод в терминале идёт в отдельном
    # потоке); после ввода обоих углов весь словарь сразу сохраняется в
    # DATA/MEASURE/MEASURE.json, а входной буфер порта сбрасывается (flush_event),
    # чтобы дальше читать текущие данные, а не накопленный хвост. С --continue
    # стартуем не с нуля, а с уже снятых точек из MEASURE.json.
    file_path = Path(cfg.DATA_DIR) / "putty.csv"
    flush_event = None
    if test:
        df = read_csv_log(file_path)
        rows, adc_max = df_to_raw_rows(df)
    else:
        flush_event = threading.Event()
        rows = read_serial_rows(port=port, baudrate=baudrate, flush_event=flush_event)
    try:
        run_measure(
            rows,
            size=cfg.SIZE_DISPLAY,
            out_dir=cfg.MEASURE_DIR,
            flush_event=flush_event,
            cont=do_continue,
        )
    finally:
        rows.close()  # освобождаем COM-порт


if __name__ == "__main__":
    cli()
