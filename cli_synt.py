from pathlib import Path

import click

from config import cfg
from src.syntetic.generator_data import (
    check_spec_example,
    generate_uart_log,
)


@click.group()
def cli():
    """Генерация синтетики"""


@cli.command("uart-log")
@click.option("--logname", default="uart_log.txt", help="название лога сохраняется в DATA/SYNTHETIC")
@click.option("--frames", default=500, show_default=True, help="Число посылок в логе.")
@click.option(
    "--period", "period_ms", default=50, show_default=True, help="Период выдачи посылок, мс."
)
@click.option(
    "--amp-x", default=1.0, show_default=True, help="Амплитуда угла по X, градусы."
)
@click.option(
    "--amp-y", default=0.6, show_default=True, help="Амплитуда угла по Y, градусы."
)
@click.option(
    "--dropout",
    default=0,
    show_default=True,
    help="Кадров без источника в середине лога (потеря захвата).",
)
@click.option(
    "--noise", default=2.0, show_default=True, help="СКО шума отсчётов АЦП, единиц."
)
@click.option("--seed", default=20260731, show_default=True, help="Зерно генератора шума.")
@click.option(
    "--one-line/--per-packet-line",
    default=False,
    show_default=True,
    help="Весь дамп одной строкой (как DATA/UART_LOG/log.txt) или по посылке на строку.",
)
def synthetic_uart_log_cmd(
    logname: str,
    frames: int,
    period_ms: int,
    amp_x: float,
    amp_y: float,
    dropout: int,
    noise: float,
    seed: int,
    one_line: bool,
):
    """Синтетический лог обмена по UART (AGS 16.00.10, спецификация ред. 1.1)."""
    path = Path(cfg.SYNTHETIC_DIR) / logname

    # Кодировщик сверяется с контрольным примером §8 спецификации: если байты
    # не сходятся, лог писать бессмысленно.
    if not check_spec_example():
        raise click.ClickException(
            "Кодировщик не воспроизводит контрольный пример §8 спецификации."
        )

    stats = generate_uart_log(
        path,
        frames=frames,
        one_line=one_line,
        period_ms=period_ms,
        amp_x_deg=amp_x,
        amp_y_deg=amp_y,
        dropout=dropout,
        noise_counts=noise,
        seed=seed,
    )

    click.echo("Контрольный пример §8 воспроизведён байт в байт: да")
    click.echo(
        f"Записано {stats['packets']} посылок ({stats['bytes']} байт) в {stats['path']}"
    )
    click.echo(
        f"Проверка дампа: CRC верна у {stats['crc_ok']} посылок, "
        f"мусора при синхронизации {stats['resync_bytes']} байт, "
        f"хвост {stats['tail_bytes']} байт"
    )
    if stats["saturated"]:
        click.echo(
            f"Внимание: в {stats['saturated']} посылках квадрант в насыщении — "
            f"разностные сигналы там уже не соответствуют углу. Уменьшите "
            f"--amp-x/--amp-y."
        )


if __name__ == "__main__":
    cli()
