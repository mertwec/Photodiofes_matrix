#!/usr/bin/env python3
"""
analyze_measure.py — анализ зависимости S1..S4 от angle_x/angle_y.
"""
import json, os
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from scipy.optimize import curve_fit
from scipy.special import erf

from src.utils.converter import dm_to_deg

OUTDIR = './DATA/ANALYSE'

def load(path):
    with open(path) as f:
        d = json.load(f)
    pts = d['points']
    rows = []
    for k, p in pts.items():
        s = p['s']
        rows.append({'ax': dm_to_deg(p['angle_x']), 'ay': dm_to_deg(p['angle_y']),
                      's1': s[0], 's2': s[1], 's3': s[2], 's4': s[3]})
    return d, rows

def compute_rxry(rows):
    for r in rows:
        s1,s2,s3,s4 = r['s1'],r['s2'],r['s3'],r['s4']
        sigma = s1+s2+s3+s4
        r['sigma'] = sigma
        r['rx'] = (s4+s3-s1-s2)/sigma if sigma>0 else 0.0
        r['ry'] = (s1+s4-s2-s3)/sigma if sigma>0 else 0.0
    return rows

def fit_erf(angle, r):
    def model(a, phi_c, sign):
        return sign*erf(a/phi_c)
    best = None
    for sign in (1.0, -1.0):
        try:
            popt, pcov = curve_fit(lambda a, phi_c: sign*erf(a/phi_c),
                                    angle, r, p0=[5.0],
                                    bounds=(0.2, 200.0), maxfev=10000)
            phi_c = popt[0]
            pred = sign*erf(angle/phi_c)
            ss_res = np.sum((r-pred)**2)
            ss_tot = np.sum((r-r.mean())**2)
            r2 = 1 - ss_res/ss_tot if ss_tot>0 else -999
            if best is None or r2 > best[3]:
                err = np.sqrt(pcov[0,0]) if pcov[0,0]>0 else 0
                best = (phi_c, err, sign, r2)
        except Exception:
            pass
    return best  # (phi_c, err, sign, r2)

def linear_fit(angle, r):
    """k: r ≈ k*angle (для калибровки чувствительности, без erf)"""
    A = np.vstack([angle, np.ones_like(angle)]).T
    k, b = np.linalg.lstsq(A, r, rcond=None)[0]
    pred = k*angle+b
    ss_res = np.sum((r-pred)**2); ss_tot = np.sum((r-r.mean())**2)
    r2 = 1-ss_res/ss_tot if ss_tot>0 else -999
    return k, b, r2

def main(path):
    d, rows = load(path)
    rows = compute_rxry(rows)
    ax = np.array([r['ax'] for r in rows]); ay = np.array([r['ay'] for r in rows])
    s1 = np.array([r['s1'] for r in rows]); s2 = np.array([r['s2'] for r in rows])
    s3 = np.array([r['s3'] for r in rows]); s4 = np.array([r['s4'] for r in rows])
    rx = np.array([r['rx'] for r in rows]); ry = np.array([r['ry'] for r in rows])
    sigma = np.array([r['sigma'] for r in rows])

    mask_x = np.abs(ay) < 0.05   # точки на чистой оси X
    mask_y = np.abs(ax) < 0.05   # точки на чистой оси Y

    fit_x = fit_erf(ax[mask_x], rx[mask_x]) if mask_x.sum()>=5 else None
    fit_y = fit_erf(ay[mask_y], ry[mask_y]) if mask_y.sum()>=5 else None
    lin_x = linear_fit(ax[mask_x], rx[mask_x]) if mask_x.sum()>=3 else None
    lin_y = linear_fit(ay[mask_y], ry[mask_y]) if mask_y.sum()>=3 else None

    print(f"=== {os.path.basename(path)} ===")
    print(f"Точек всего: {len(rows)}  на оси X: {mask_x.sum()}  на оси Y: {mask_y.sum()}")
    print()
    print("--- Подбор erf (с учётом возможного инвертированного знака) ---")
    if fit_x:
        phi_c,err,sign,r2 = fit_x
        print(f"  rx = {'+' if sign>0 else '-'}erf(ax/{phi_c:.2f})  R²={r2:.4f}  "
              f"{'[ЗНАК ИНВЕРТИРОВАН]' if sign<0 else ''}")
    if fit_y:
        phi_c,err,sign,r2 = fit_y
        print(f"  ry = {'+' if sign>0 else '-'}erf(ay/{phi_c:.2f})  R²={r2:.4f}  "
              f"{'[ЗНАК ИНВЕРТИРОВАН]' if sign<0 else ''}")
    print()
    print("--- Линейная аппроксимация (диапазон ±2° далёк от насыщения) ---")
    if lin_x:
        k,b,r2 = lin_x
        print(f"  rx ≈ {k:+.4f}*ax {b:+.4f}   R²={r2:.4f}")
    if lin_y:
        k,b,r2 = lin_y
        print(f"  ry ≈ {k:+.4f}*ay {b:+.4f}   R²={r2:.4f}")

    print()
    print("--- Равномерность суммы Σ ---")
    print(f"  Σ: min={sigma.min():.0f} max={sigma.max():.0f} mean={sigma.mean():.0f} "
          f"std={sigma.std():.0f} ({sigma.std()/sigma.mean()*100:.1f}%)")

    print()
    print("--- Перекрёстная связь (cross-talk) ---")
    rx_y = rx[mask_y]; ry_x = ry[mask_x]
    print(f"  rx на чистой Y-оси (ax≈0): mean={rx_y.mean():+.4f} std={rx_y.std():.4f}")
    print(f"  ry на чистой X-оси (ay≈0): mean={ry_x.mean():+.4f} std={ry_x.std():.4f}")

    print()
    print("--- Баланс каналов в центре (|ax|,|ay|<0.1) ---")
    mc = (np.abs(ax)<0.1)&(np.abs(ay)<0.1)
    if mc.sum()>0:
        vals=[s1[mc].mean(),s2[mc].mean(),s3[mc].mean(),s4[mc].mean()]
        print(f"  S1={vals[0]:.0f} S2={vals[1]:.0f} S3={vals[2]:.0f} S4={vals[3]:.0f}  "
              f"(n={mc.sum()}, разброс {(max(vals)-min(vals))/np.mean(vals)*100:.1f}%)")

    # ===== Графики =====
    fig = plt.figure(figsize=(16, 11))
    fig.suptitle(f'Анализ 4QD: {os.path.basename(path)}  (fov={d.get("fov")})',
                 fontsize=13, fontweight='bold')
    gs = gridspec.GridSpec(3, 3, figure=fig, hspace=0.5, wspace=0.35)
    col = {'s1':'#DC2626','s2':'#2563EB','s3':'#16A34A','s4':'#CA8A04'}

    ax1 = fig.add_subplot(gs[0, :2])
    idx = np.argsort(ax[mask_x])
    for name,arr,c in [('S1',s1,col['s1']),('S2',s2,col['s2']),('S3',s3,col['s3']),('S4',s4,col['s4'])]:
        ax1.plot(ax[mask_x][idx], arr[mask_x][idx], 'o-', ms=4, color=c, label=name)
    ax1.set_xlabel('angle_x, °'); ax1.set_ylabel('Si'); ax1.legend(fontsize=8)
    ax1.set_title('S1..S4 при angle_y≈0'); ax1.grid(alpha=0.3)

    ax2 = fig.add_subplot(gs[1, :2])
    idy = np.argsort(ay[mask_y])
    for name,arr,c in [('S1',s1,col['s1']),('S2',s2,col['s2']),('S3',s3,col['s3']),('S4',s4,col['s4'])]:
        ax2.plot(ay[mask_y][idy], arr[mask_y][idy], 'o-', ms=4, color=c, label=name)
    ax2.set_xlabel('angle_y, °'); ax2.set_ylabel('Si'); ax2.legend(fontsize=8)
    ax2.set_title('S1..S4 при angle_x≈0'); ax2.grid(alpha=0.3)

    ax3 = fig.add_subplot(gs[2, :2])
    a_fine = np.linspace(ax.min()-0.2, ax.max()+0.2, 300)
    ax3.scatter(ax[mask_x], rx[mask_x], s=22, color='#DC2626', label='rx data', zorder=3)
    ax3.scatter(ay[mask_y], ry[mask_y], s=22, color='#2563EB', label='ry data', zorder=3, marker='s')
    if fit_x:
        phi_c,_,sign,r2 = fit_x
        ax3.plot(a_fine, sign*erf(a_fine/phi_c), color='#DC2626', lw=1.3,
                 label=f'erf fit φc={phi_c:.1f} R²={r2:.3f}')
    if fit_y:
        phi_c,_,sign,r2 = fit_y
        a_fine2 = np.linspace(ay.min()-0.2, ay.max()+0.2, 300)
        ax3.plot(a_fine2, sign*erf(a_fine2/phi_c), color='#2563EB', lw=1.3, ls='--',
                 label=f'erf fit φc={phi_c:.1f} R²={r2:.3f}')
    ax3.axhline(0,color='gray',lw=0.5); ax3.axvline(0,color='gray',lw=0.5)
    ax3.set_xlabel('angle, °'); ax3.set_ylabel('r'); ax3.legend(fontsize=7.5)
    ax3.set_title('rx(ax), ry(ay)'); ax3.grid(alpha=0.3)

    ax4 = fig.add_subplot(gs[0, 2])
    sc4 = ax4.scatter(ax, ay, c=rx, cmap='RdBu_r', s=40, vmin=-1, vmax=1)
    plt.colorbar(sc4, ax=ax4, label='rx')
    ax4.set_xlabel('angle_x, °'); ax4.set_ylabel('angle_y, °')
    ax4.set_title('Карта rx(ax,ay)'); ax4.set_aspect('equal'); ax4.grid(alpha=0.3)

    ax5 = fig.add_subplot(gs[1, 2])
    sc5 = ax5.scatter(ax, ay, c=ry, cmap='RdBu_r', s=40, vmin=-1, vmax=1)
    plt.colorbar(sc5, ax=ax5, label='ry')
    ax5.set_xlabel('angle_x, °'); ax5.set_ylabel('angle_y, °')
    ax5.set_title('Карта ry(ax,ay)'); ax5.set_aspect('equal'); ax5.grid(alpha=0.3)

    ax6 = fig.add_subplot(gs[2, 2])
    sc6 = ax6.scatter(ax, ay, c=sigma, cmap='viridis', s=40)
    plt.colorbar(sc6, ax=ax6, label='Σ')
    ax6.set_xlabel('angle_x, °'); ax6.set_ylabel('angle_y, °')
    ax6.set_title('Σ=S1+S2+S3+S4'); ax6.set_aspect('equal'); ax6.grid(alpha=0.3)

    out_png = os.path.join(OUTDIR, os.path.basename(path).replace('.json','_analysis.png'))
    plt.savefig(out_png, dpi=140, bbox_inches='tight')
    plt.close(fig)
    print(f"\nГрафик сохранён: {out_png}")
    print("="*72)
    return fit_x, fit_y

if __name__ == '__main__':
    for path in ['./DATA/MEASURE/MEASURE.json',
                 './DATA/MEASURE/MEASURE_v1.json']:
        main(path)
