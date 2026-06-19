"""
CLI получения и проверки компенсационного полинома (Задача №13).

    python cli_model.py fit      # построить полином из MEASURE.json, проверить, сохранить
    python cli_model.py verify   # проверить уже сохранённый COMPENSATION.json на данных

Полином корректирует систематику нож-модели измерения угла (анализ —
DOCUMENTATION/AI_COMPENSATION.md). Математика — src/compensation.py, получение/IO —
src/pipeline/poly_compensation.py.
"""

from pathlib import Path

import click

from config import cfg
from src.compensation import (
    evaluate,
    holdout_rmse,
    knife_baseline_rmse,
    poly_terms,
)
from src.pipeline.calib_radius import spot_radius_from_calib
from src.pipeline.poly_compensation import (
    build_compensation,
    load_compensation,
    load_measure_points,
    save_compensation,
)
from src.visualization.data_plot import (
    plot_angle_linearity,
    plot_compensation_surface,
    plot_measure_data,
)


def _term_label(p: int, q: int) -> str:
    """(p, q) → 'ux²·uy', '1', 'uy', … для печати коэффициентов."""
    sup = {0: "", 1: "", 2: "²", 3: "³"}
    parts = []
    if p:
        parts.append(f"ux{sup.get(p, '^' + str(p))}")
    if q:
        parts.append(f"uy{sup.get(q, '^' + str(q))}")
    return "·".join(parts) if parts else "1"


def _print_report(model, info: dict) -> None:
    click.echo("=== ПОСТРОЕНИЕ ПОЛИНОМА ===")
    click.echo(
        f"степень {info['degree']} ({info['n_coef']} коэф./ось), базис {model.basis}, "
        f"d_max={info['d_max']}, ADC_MAX={info['adc_max']:.0f}"
    )
    click.echo(
        f"точек: всего {info['n_total']} → валидных {info['n_valid']} → "
        f"в фите {info['n_used']}"
    )
    dxmin, dxmax, dymin, dymax = info["d_range"]
    click.echo(
        f"диапазон D: Dx∈[{dxmin:+.3f},{dxmax:+.3f}]  Dy∈[{dymin:+.3f},{dymax:+.3f}]  "
        f"std(angle_y)={info['std_y']:.3f}"
    )

    if info["dropped"]:
        click.echo(f"\nотфильтровано ({len(info['dropped'])}):")
        for key, reason in info["dropped"]:
            click.echo(f"  {key}: {reason}")
    if info["outliers"]:
        click.echo(f"\nвыбросы K·MAD ({len(info['outliers'])}):")
        for key, axis, r in info["outliers"]:
            click.echo(f"  {key}: ось {axis}, остаток {r:+.3f}°")

    click.echo("\nкоэффициенты (моном: coef_x  coef_y):")
    for (p, q), cxk, cyk in zip(poly_terms(model.degree), model.coef_x, model.coef_y):
        click.echo(f"  {_term_label(p, q):<7} {cxk:+10.4f}  {cyk:+10.4f}")

    click.echo(
        f"\nобучающий RMSE: x={model.rmse_deg['x']:.4f}°  y={model.rmse_deg['y']:.4f}°"
    )
    click.echo(
        f"LOO RMSE (паспорт): x={model.loo_rmse_deg['x']:.4f}°  "
        f"y={model.loo_rmse_deg['y']:.4f}°"
    )
    for w in model.warnings:
        click.echo(f"⚠ {w}")


def _print_verify(model, points: dict) -> None:
    click.echo("\n=== ПРОВЕРКА КОМПЕНСАЦИИ ===")

    ev = evaluate(model, points)
    click.echo(
        f"in-sample на {ev['n']} точках: RMSE x={ev['rmse_x']:.4f}° y={ev['rmse_y']:.4f}°  "
        f"| max |ошибки| x={ev['max_x']:.3f}° y={ev['max_y']:.3f}°"
    )
    click.echo("худшие точки (ключ: ошибка_x, ошибка_y):")
    for key, ex, ey in ev["worst"]:
        click.echo(f"  {key}: {ex:+.3f}°, {ey:+.3f}°")

    ho = holdout_rmse(points, degree=model.degree, d_max=model.d_max)
    click.echo(
        f"\nhold-out {ho['n'] - ho['n_test']}/{ho['n_test']} ×{ho['iters']}: "
        f"RMSE x={ho['x_mean']:.4f}±{ho['x_std']:.4f}°  "
        f"y={ho['y_mean']:.4f}±{ho['y_std']:.4f}°"
    )

    # Сравнение с базовой нож-моделью (w из калибровки) — «было/стало».
    calib = spot_radius_from_calib(cfg.CALIB_FILE)
    if calib is None:
        click.echo(
            "\nнож-модель: нет CALIBRATE.json — сравнение «было/стало» пропущено"
        )
        return
    base = knife_baseline_rmse(points, calib["w_mm"], d_max=model.d_max)
    click.echo(
        f"\nбазовая нож-модель (w={base['w_mm']:.2f} мм, FOC={base['foc']:.0f}): "
        f"RMSE x={base['rmse_x']:.4f}° y={base['rmse_y']:.4f}°"
    )
    gx = base["rmse_x"] / ho["x_mean"] if ho["x_mean"] else float("nan")
    gy = base["rmse_y"] / ho["y_mean"] if ho["y_mean"] else float("nan")
    click.echo(
        f"выигрыш (нож/полином, hold-out): ×{gx:.1f} по x, ×{gy:.1f} по y"
    )


@click.group()
def cli():
    """Компенсационный полином измерения угла (Задача №13)."""


@cli.command("fit")
@click.option("--out", "out_path", type=click.Path(path_type=Path),
              default=None, help="куда сохранить (по умолч. cfg.COMP_FILE).")
@click.option("--degree", type=int, default=cfg.COMP_DEGREE,
              help=f"степень полинома (по умолч. cfg.COMP_DEGREE={cfg.COMP_DEGREE}).")
@click.option("--keep-outliers", is_flag=True, default=False,
              help="не отбраковывать выбросы K·MAD.")
@click.option("--no-save", is_flag=True, default=False,
              help="только показать отчёт, не сохранять файл.")
def fit_cmd(out_path, degree, keep_outliers, no_save):
    """Построить полином из MEASURE.json, проверить и сохранить COMPENSATION.json."""
    measure_path = cfg.MEASURE_FILE

    model, info = build_compensation(
        measure_path, degree=degree, reject_outliers=keep_outliers
    )
    _print_report(model, info)
    _print_verify(model, load_measure_points(measure_path))

    if no_save:
        click.echo("\n[--no-save] файл не записан.")
    else:
        path = save_compensation(model, out_path)
        click.echo(f"\n[Сохранено] {path}")


@cli.command("verify")
@click.option("--measure", "measure_path", type=click.Path(path_type=Path),
              default=None, help="MEASURE.json (по умолч. cfg.MEASURE_FILE).")
@click.option("--model", "model_path", type=click.Path(path_type=Path),
              default=None, help="COMPENSATION.json (по умолч. cfg.COMP_FILE).")
def verify_cmd(measure_path, model_path):
    """Проверить уже сохранённый полином на данных MEASURE.json."""

    measure_path = cfg.MEASURE_FILE
    model = load_compensation(model_path)
    if model is None:
        raise click.ClickException(
            f"нет файла полинома ({model_path or cfg.COMP_FILE}) — сначала "
            "`python cli_model.py fit`"
        )
    click.echo(
        f"модель: степень {model.degree}, d_max={model.d_max}, "
        f"точек в фите {model.n_points}, создана {model.created}"
    )
    _print_verify(model, load_measure_points(measure_path))


@cli.command("show")
@click.option("--data", "data_path", type=click.Path(path_type=Path),
              default=None, help="MEASURE.json (по умолч. cfg.MEASURE_FILE).")
@click.option("--model", "model_path", type=click.Path(path_type=Path),
              default=None,
              help="COMPENSATION.json для --kind surface (по умолч. cfg.COMP_FILE).")
@click.option("--kind", "-k", type=click.Choice(["linearity", "raw", "surface"]),
              default="linearity", show_default=True,
              help="linearity: θ от D и erfinv(D); raw: АЦП от θx/θy; "
                   "surface: 3D-поверхность полинома θx/θy(Dx,Dy) + точки.")
def show_data_cmd(data_path, model_path, kind):
    """Показать графики снятых данных (см. --kind)."""
    measure_path = Path(data_path) if data_path else cfg.MEASURE_FILE
    points = load_measure_points(measure_path)

    if not points:
        raise click.ClickException(f"нет точек в {measure_path}")

    click.echo(f"точек: {len(points)} из {measure_path}  (--kind {kind})")
    title = f"{measure_path}  (точек: {len(points)})"
    if kind == "surface":
        model = load_compensation(model_path)
        if model is None:
            raise click.ClickException(
                f"нет файла полинома ({model_path or cfg.COMP_FILE}) — сначала "
                "`python cli_model.py fit`"
            )
        plot_compensation_surface(points, model, title=title)
    else:
        plot = plot_angle_linearity if kind == "linearity" else plot_measure_data
        plot(points, title=title)


if __name__ == "__main__":
    cli()
