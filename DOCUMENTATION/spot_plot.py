#!/usr/bin/env python3
"""
spot_plot.py

Визуализация пеленгационной характеристики четырёхквадрантного детектора.
Считывает CSV из COM-порта (вывод spot_debug_csv()) или из файла,
строит графики, оценивает φc и качество настройки.

Использование:
    python spot_plot.py COM3          # чтение с USB CDC
    python spot_plot.py data.csv      # чтение из файла
    python spot_plot.py COM3 --save   # сохранить в data.csv
"""

import sys, math, re
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from scipy.optimize import curve_fit
from scipy.special import erf, erfinv
import serial, time


# ── Параметры ────────────────────────────────────────────────────────
PHI_MAX_MRAD = 20.0   # из dac_output.h (PHI_MAX_MRAD)
PHI_C_INIT   = 5.0    # начальное приближение φc для curve_fit

# ── Считывание данных ─────────────────────────────────────────────────
def read_serial(port, timeout=30):

    rows = []
    print(f"Подключение к {port}...")
    with serial.Serial(port, 115200, timeout=1) as s:
        s.write(b'dc\n')      # 'd' = debug mode, 'c' = csv
        t0 = time.time()
        in_csv = False
        while time.time() - t0 < timeout:
            line = s.readline().decode('utf-8', errors='replace').strip()
            if not line: continue
            if '# CSV' in line:
                in_csv = True
                print("Получение данных...")
                continue
            if '# END' in line:
                break
            if in_csv and not line.startswith('#'):
                rows.append(line)
    return rows

def read_file(path):
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                rows.append(line)
    return rows

def parse_rows(rows):
    pts = []
    for row in rows:
        try:
            v = [float(x) for x in row.split(',')]
            if len(v) >= 4:
                pts.append({'phi_x': v[0], 'rx': v[1],
                             'phi_y': v[2], 'ry': v[3],
                             'sum':   v[4] if len(v) > 4 else 1.0})
        except ValueError:
            pass
    return pts

# ── Подбор φc ─────────────────────────────────────────────────────────
def fit_phi_c(phi_arr, r_arr):
    """Подобрать φc из r = erf(phi/phi_c)."""
    def model(phi, phi_c):
        return erf(phi / phi_c)
    try:
        popt, pcov = curve_fit(model, phi_arr, r_arr,
                                p0=[PHI_C_INIT],
                                bounds=(0.1, 100.0),
                                maxfev=5000)
        phi_c  = popt[0]
        phi_c_err = np.sqrt(pcov[0, 0]) if pcov[0, 0] > 0 else 0.0
        r2 = 1 - np.sum((r_arr - model(phi_arr, phi_c))**2) / \
                 np.sum((r_arr - r_arr.mean())**2)
        return phi_c, phi_c_err, r2
    except Exception as e:
        print(f"Ошибка подбора: {e}")
        return None, None, None

# ── Рекомендация ──────────────────────────────────────────────────────
def recommendation(phi_c, phi_max=PHI_MAX_MRAD):
    lin  = 0.4 * phi_c
    phys = 4.0 * phi_c
    pct  = phys / phi_max * 100.0
    opt  = phi_max / 4.0

    print(f"\n{'='*50}")
    print(f"ОЦЕНКА РАЗМЕРА ПЯТНА")
    print(f"{'='*50}")
    print(f"  φc измеренный  = {phi_c:.2f} мрад")
    print(f"  φc оптимальный = {opt:.2f} мрад  (PHI_MAX/4)")
    print(f"  Линейный диап. = ±{lin:.2f} мрад")
    print(f"  Физ. предел    = ±{phys:.2f} мрад")
    print(f"  Использование ЦАП = {pct:.0f}%")

    if phi_c < 1.0:
        status = "❌ СЛИШКОМ МАЛО"
        advice = "Увеличить f или расфокусировать детектор"
    elif phi_c < opt * 0.5:
        status = "⚠  Мало"
        advice = f"Рекомендуется φc ≈ {opt:.1f} мрад, установить PHI_MAX_MRAD = {phys:.0f}"
    elif phi_c <= opt * 1.5:
        status = "✓  ОПТИМАЛЬНО"
        advice = "Настройка хорошая"
    elif phi_c <= 20.0:
        status = "⚠  Крупно"
        advice = f"Уменьшить PHI_MAX_MRAD до {phys:.0f} или уменьшить f"
    else:
        status = "❌ СЛИШКОМ ВЕЛИКО"
        advice = "Уменьшить f объектива или сфокусировать точнее"

    print(f"  Статус: {status}")
    print(f"  Совет:  {advice}")
    print(f"{'='*50}\n")

# ── Построение графиков ───────────────────────────────────────────────
def plot(pts):
    if not pts:
        print("Нет данных для построения")
        return

    phi_x = np.array([p['phi_x'] for p in pts])
    rx    = np.array([p['rx']    for p in pts])
    phi_y = np.array([p['phi_y'] for p in pts])
    ry    = np.array([p['ry']    for p in pts])
    sn    = np.array([p['sum']   for p in pts])

    # Фильтр: только достоверные измерения
    mask_x = (np.abs(rx) >= 0.02) & (np.abs(rx) <= 0.92) & (sn > 0.05)
    mask_y = (np.abs(ry) >= 0.02) & (np.abs(ry) <= 0.92) & (sn > 0.05)

    phi_c_x, err_x, r2_x = fit_phi_c(phi_x[mask_x], rx[mask_x]) \
        if mask_x.sum() >= 4 else (None, None, None)
    phi_c_y, err_y, r2_y = fit_phi_c(phi_y[mask_y], ry[mask_y]) \
        if mask_y.sum() >= 4 else (None, None, None)

    phi_c_mean = None
    if phi_c_x and phi_c_y:
        phi_c_mean = (phi_c_x + phi_c_y) / 2.0
        recommendation(phi_c_mean)
    elif phi_c_x:
        recommendation(phi_c_x)

    # ── Рисование ─────────────────────────────────────────────────
    fig = plt.figure(figsize=(14, 9))
    fig.suptitle('Пеленгационная характеристика — настройка размера пятна',
                 fontsize=13, fontweight='bold')
    gs = gridspec.GridSpec(2, 3, figure=fig, hspace=0.42, wspace=0.35)

    col = {'data': '#2563EB', 'fit': '#DC2626', 'lin': '#16A34A',
           'zone': '#FEF08A', 'ok': '#86EFAC', 'hi': '#FCA5A5'}

    phi_fine = np.linspace(-25, 25, 400)

    def draw_erf_axis(ax, phi_data, r_data, phi_c_fit, err, r2, axis_name):
        ax.scatter(phi_data, r_data, s=18, alpha=0.6,
                   color=col['data'], label='Измерения', zorder=3)

        if phi_c_fit:
            r_fit = erf(phi_fine / phi_c_fit)
            ax.plot(phi_fine, r_fit, color=col['fit'], lw=2,
                    label=f'erf(φ/{phi_c_fit:.2f})  R²={r2:.3f}')
            # Линейное приближение
            k = 2 / (math.sqrt(math.pi) * phi_c_fit)
            r_lin = np.clip(k * phi_fine, -1, 1)
            ax.plot(phi_fine, r_lin, '--', color=col['lin'], lw=1.2,
                    label=f'Линейн. k={k:.3f}/мрад')
            # Зона линейности ±0.4φc
            lin = 0.4 * phi_c_fit
            ax.axvspan(-lin, lin, alpha=0.15, color=col['ok'],
                       label=f'±{lin:.1f} мрад (±0.4φc)')
            ax.axvline(-lin, color=col['ok'], lw=0.8, ls=':')
            ax.axvline( lin, color=col['ok'], lw=0.8, ls=':')
            ax.set_title(
                f'Ось {axis_name}: φc = {phi_c_fit:.2f}±{err:.2f} мрад',
                fontsize=10)
        else:
            ax.set_title(f'Ось {axis_name}: нет данных', fontsize=10)

        ax.axhline(0, color='gray', lw=0.5)
        ax.axvline(0, color='gray', lw=0.5)
        ax.set_xlim(-25, 25)
        ax.set_ylim(-1.15, 1.15)
        ax.set_xlabel('φ, мрад')
        ax.set_ylabel(f'r{axis_name.lower()}')
        ax.legend(fontsize=7.5, loc='upper left')
        ax.grid(True, alpha=0.3)

    ax_x = fig.add_subplot(gs[0, :2])
    draw_erf_axis(ax_x, phi_x, rx, phi_c_x, err_x or 0, r2_x or 0, 'X')

    ax_y = fig.add_subplot(gs[1, :2])
    draw_erf_axis(ax_y, phi_y, ry, phi_c_y, err_y or 0, r2_y or 0, 'Y')

    # ── Круговая диаграмма rx/ry ─────────────────────────────────
    ax_c = fig.add_subplot(gs[:, 2])
    sc = ax_c.scatter(rx, ry, c=sn, cmap='RdYlGn', s=20,
                       vmin=0, vmax=0.5, alpha=0.7)
    plt.colorbar(sc, ax=ax_c, label='sum_norm')
    theta = np.linspace(0, 2*math.pi, 200)
    for r_lev in [0.4, 0.7, 1.0]:
        ax_c.plot(np.cos(theta)*r_lev, np.sin(theta)*r_lev,
                  'gray', lw=0.6, ls='--', alpha=0.5)
    ax_c.axhline(0, color='gray', lw=0.5)
    ax_c.axvline(0, color='gray', lw=0.5)
    ax_c.set_xlim(-1.2, 1.2)
    ax_c.set_ylim(-1.2, 1.2)
    ax_c.set_aspect('equal')
    ax_c.set_xlabel('rx (горизонталь)')
    ax_c.set_ylabel('ry (вертикаль)')
    ax_c.set_title('Траектория пучка\n(цвет = интенсивность)')
    ax_c.grid(True, alpha=0.3)

    # Аннотация φc
    if phi_c_mean:
        info = (f"φc = {phi_c_mean:.2f} мрад\n"
                f"w/f = {phi_c_mean/1000:.5f}\n"
                f"Lin ±{0.4*phi_c_mean:.2f} мрад\n"
                f"PHI_MAX = {PHI_MAX_MRAD:.0f} мрад\n"
                f"ЦАП = {4*phi_c_mean/PHI_MAX_MRAD*100:.0f}%")
        ax_c.text(0.04, 0.04, info, transform=ax_c.transAxes,
                  fontsize=8.5, verticalalignment='bottom',
                  bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

    plt.savefig('spot_result.png', dpi=150, bbox_inches='tight')
    print("График сохранён: spot_result.png")
    plt.show()

# ── Точка входа ───────────────────────────────────────────────────────
if __name__ == '__main__':
    save = '--save' in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    src  = args[0] if args else 'COM3'

    if src.upper().startswith('COM') or src.startswith('/dev/'):
        rows = read_serial(src)
        if save:
            with open('spot_data.csv', 'w') as f:
                f.write('\n'.join(rows))
            print("Данные сохранены: spot_data.csv")
    else:
        rows = read_file(src)

    pts = parse_rows(rows)
    print(f"Загружено точек: {len(pts)}")
    plot(pts)
