import threading
from pathlib import Path

import click

from config import cfg
from src.calibration import run_calibration
from src.measure import run_measure
from src.pipeline.calib_radius import info_calib_radius
from src.pipeline.get_single_point import df_to_raw_rows, make_point, points_by_angles
from src.pipeline.poly_compensation import load_compensation
from src.reader.file_reader import read_csv_log
from src.reader.log_writer import make_log_path, tee_frames_to_csv
from src.reader.stream import detect_serial_format, read_serial_rows, read_serial_uart
from src.utils.parsing_uart import is_uart_log, read_uart_log
from src.visualization.display import display_points_stream


@click.group()
def cli():
    """Визуализатор направления засветки с фотодиодной матрицы."""


def _compensation_model(comps: bool):
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


def _rows_from_log(file_path: Path):
    """
    Строки датчиков из лога с автоопределением формата (Задача №15).

    Дамп посылок UART (двоичный или hex-текст, см. DATA/SYNTHETIC/uart_log.txt)
    разбирается parsing_uart, старый CSV — как раньше. Обе ветки отдают одну и
    ту же форму строк {s1..s4 [, T, v_x, v_y]} + опорный adc_max, поэтому
    дальше пайплайн общий. Возвращает (rows, adc_max, число кадров, формат).
    """
    if is_uart_log(file_path):
        rows, adc_max, stats = read_uart_log(file_path)
        print(
            f"[Лог] формат UART (спецификация ред. 1.2): посылок {stats['packets']}, "
            f"{stats['bytes']} байт, мусора при синхронизации {stats['dropped_bytes']} "
            f"байт, хвост {stats['tail_bytes']} байт, без захвата {stats['no_lock']}, "
            f"перегрузка тракта в {stats['overload']}, "
            f"ступени усиления {stats['gain_steps']}."
        )
        if stats["short_blocks"]:
            print(
                f"[Лог] пропущено {stats['short_blocks']} посылок с блоком короче "
                "31 байта — это дамп старой редакции протокола (1.0/1.1), "
                "разбирается только текущая 1.2."
            )
        return rows, adc_max, len(rows), "UART"

    df = read_csv_log(file_path)
    rows, adc_max = df_to_raw_rows(df)
    print(f"[Лог] формат CSV: строк {len(df)}, adc_max={adc_max:.0f}.")
    return rows, adc_max, len(df), "CSV"


def _apply_by_angles(frames, size: int, fmt: str, by_angles: bool):
    """
    Точка по ПЕРЕДАННЫМ углам v_x/v_y вместо разностей квадрантов (Задачи №15/№16).

    Общий для log и stream шаг между make_point и дисплеем: физическое положение
    центра пятна d = FOC·tg θ в масштабе зоны датчика. Кадры без переданных
    углов проходят нетронутыми (см. points_by_angles).

    Углы достоверны только в формате UART (изделие считает их само, §7). В
    старом ASCII/CSV-формате v_x/v_y посчитаны неверно (поправка №1) — флаг
    выполняется как просили, но с предупреждением.
    """
    if not by_angles:
        return frames

    print(
        "[Точка] по переданным углам v_x/v_y (d = FOC·tg θ, "
        f"масштаб {cfg.DET_SIZE_MM:.0f} мм ↔ {size} px); отключить: --no-by-angles."
    )
    if fmt != "UART":
        print(
            f"        внимание: в формате {fmt} углы v_x/v_y изделие считает "
            "неверно (поправка №1) — точка уедет к краю, нужен --no-by-angles."
        )
    return points_by_angles(frames, size)


@cli.command("log")
@click.option(
    "--file",
    "file_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=Path("./DATA/LOG_20260619_110246.csv"),
    show_default=True,
    help="Лог с показаниями датчиков: CSV или дамп посылок UART.",
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
@click.option(
    "--by-angles/--no-by-angles",
    default=True,
    show_default=True,
    help="Точку рисовать по переданным углам v_x/v_y, а не по разностям квадрантов.",
)
def log_cmd(file_path: Path, size: int, comps: bool, by_angles: bool):
    """Проиграть точки из лога: CSV или дамп посылок UART (формат определяется сам)."""
    rows, adc_max, frames_count, fmt = _rows_from_log(file_path)

    frames = make_point(
        rows,
        size,
        adc_max,
        val_max=cfg.S_VAL_MAX,
        val_min=cfg.S_VAL_MIN,
        fixed_radius=info_calib_radius(),
        comp_model=_compensation_model(comps),
    )

    # Задача №15: точка по переданным углам (физическое положение центра пятна
    # d = FOC·tg θ в масштабе зоны датчика), а не по разностным сигналам. Кадры
    # без углов остаются с точкой, посчитанной по квадрантам.
    frames = _apply_by_angles(frames, size, fmt, by_angles)

    # Прошедшее время с первого кадра рисуется живой подписью покадрово (часы
    # хоста, см. display_points_stream) — время устройства T для этого не годится.
    legend: dict = {
        "формат": fmt,
        "frames": frames_count,
        "точка": "углы" if by_angles else "квадранты",
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
@click.option(
    "--by-angles/--no-by-angles",
    default=True,
    show_default=True,
    help="Точку рисовать по переданным углам v_x/v_y, а не по разностям квадрантов.",
)
def stream_cmd(port: str, baudrate: int, log: bool, comps: bool, by_angles: bool):
    """Читать данные с UART (формат определяется сам) и отображать в реальном времени."""
    adc_max = cfg.ADC_MAX
    size = cfg.SIZE_DISPLAY

    # Задача №16: выбираем ридер по тому, что реально шлёт изделие — двоичные
    # посылки (спецификация ред. 1.2) или старые ASCII-строки. Ждём первую
    # полноценную посылку/строку (порт держится открытым), поэтому пустой порт
    # не приводит к пустому окну. Обе ветки отдают одинаковые словари строк.
    print(f"[Порт] {port}: определяем формат данных…")
    if detect_serial_format(port=port, baudrate=baudrate) == "uart":
        fmt = "UART"
        print("[Порт] формат UART: двоичные посылки (спецификация ред. 1.2).")
        rows = read_serial_uart(port=port, baudrate=baudrate)
    else:
        fmt = "ASCII"
        print("[Порт] формат ASCII-строк: T;s1..s4[;v_x;v_y].")
        rows = read_serial_rows(port=port, baudrate=baudrate)

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
        comp_model=_compensation_model(comps),
    )

    frames = _apply_by_angles(frames, size, fmt, by_angles)

    # Лог пишется ПОСЛЕ make_point: в него идут РАССЧИТАННЫЕ углы angle_x/angle_y
    # (а не опорные v_x/v_y устройства), время — системное (столбец ts).
    if log:
        log_path = make_log_path(cfg.LOG_DIR)
        frames = tee_frames_to_csv(frames, log_path)

    try:
        legend: dict = {
            "port": port,
            "формат": fmt,
            "точка": "углы" if by_angles else "квадранты",
            # "quit": "q",
        }
        # interval=0: темп задаёт сам UART (ser.readline блокируется до строки/таймаута).
        display_points_stream(frames, size=size, interval=0, legend=legend)
    finally:
        frames.close()
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
