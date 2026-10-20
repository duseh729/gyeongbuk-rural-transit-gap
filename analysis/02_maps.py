"""기초 지표로 사각지대 지수를 계산하고 보고서용 지도·그래프를 그린다.

지수:
  수요   = 65세 이상 인구 수의 백분위와 고령화율 백분위의 평균
  접근성 결핍 = "버스를 쓰기 어려운 마을" 비율(OSM 마을 3곳 이상인 읍면만)의 백분위
               버스를 쓰기 어려운 마을 = 1km 안에 정류장이 없거나, 있어도 하루 정차 5회 이하(왕복 3회 미만)
               (04_service.py 결과가 없으면 정류장 거리만 쓴다)
  사각지대 지수 = 수요 × 접근성 결핍 (0~1)
"""
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out"
plt.rcParams["font.family"] = "AppleGothic"
plt.rcParams["axes.unicode_minus"] = False


def index(emd):
    e = emd.copy()
    e["far_share"] = (e.vil_far_1km / e.n_vil).where(e.n_vil >= 3)
    svc = OUT / "emd_service.csv"
    if svc.exists():
        e = e.merge(pd.read_csv(svc, dtype={"adm_cd2": str}), on="adm_cd2", how="left")
        e["hard_share"] = ((e.vil_no_bus + e.vil_low_bus) / e.n_vil).where(e.n_vil >= 3)
    e["demand"] = (e.pop65.rank(pct=True) + e.aged_ratio.rank(pct=True)) / 2
    e["blind_idx_dist"] = e.demand * e.far_share.rank(pct=True)  # 22개 시군 공통(정류장 거리만)
    # 운행 횟수를 알 수 있는 시군만 운행 횟수까지 반영한 지수를 낸다. 나머지는 빈칸
    gap = e.hard_share if "hard_share" in e else e.far_share
    e["access_gap"] = gap.rank(pct=True)
    e["blind_idx"] = e.demand * e.access_gap
    return e


def main():
    emd = index(gpd.read_file(OUT / "emd.gpkg"))
    vil = gpd.read_file(OUT / "villages.gpkg")
    # 지도에서는 울릉군을 빼서 본토를 크게 보인다(지수·표에는 포함)
    land = emd[emd.sggnm != "울릉군"]
    vil_land = vil[vil.adm_cd2.isin(land.adm_cd2)]
    sgg = land.dissolve("sggnm")

    # 그림 1: 고령화율
    ax = land.plot("aged_ratio", cmap="OrRd", legend=True, figsize=(8, 8), edgecolor="white", linewidth=0.2,
                  legend_kwds={"label": "65세 이상 비율", "shrink": 0.6})
    sgg.boundary.plot(ax=ax, color="#555", linewidth=0.6)
    ax.set_title("경북 읍면동 고령화율 (2026.9 주민등록)"); ax.set_axis_off()
    plt.savefig(OUT / "fig1_aged_ratio.png", dpi=200, bbox_inches="tight"); plt.close()

    # 그림 2: 마을별 최근접 정류장 거리
    ax = land.plot(color="#f2f2f2", edgecolor="white", linewidth=0.2, figsize=(8, 8))
    sgg.boundary.plot(ax=ax, color="#999", linewidth=0.5)
    near, far = vil_land[vil_land.d_stop_m <= 1000], vil_land[vil_land.d_stop_m > 1000]
    near.plot(ax=ax, markersize=3, color="#7aa6c2", label=f"1km 안에 정류장 있음 ({len(near):,})")
    far.plot(ax=ax, markersize=7, color="#d7301f", label=f"1km 안에 정류장 없음 ({len(far):,})")
    ax.legend(loc="upper left", bbox_to_anchor=(0, -0.02), frameon=False); ax.set_title("경북 마을과 가장 가까운 버스정류장 거리"); ax.set_axis_off()
    plt.savefig(OUT / "fig2_village_distance.png", dpi=200, bbox_inches="tight"); plt.close()

    # 그림 3: 시군별 1km 밖 마을 비율
    vil["sggnm"] = vil.adm_cd2.map(emd.set_index("adm_cd2").sggnm)
    s = vil.groupby("sggnm").d_stop_m.agg(n="size", far=lambda d: (d > 1000).sum())
    s["share"] = s.far / s.n
    s = s.sort_values("share")
    fig, ax = plt.subplots(figsize=(7, 7))
    ax.barh(s.index, s.share * 100, color=["#d7301f" if v >= 0.25 else "#9ecae1" for v in s.share])
    for i, (v, n) in enumerate(zip(s.share, s.n)):
        ax.text(v * 100 + 0.5, i, f"{v:.0%} ({n}곳 중)", va="center", fontsize=8)
    ax.set_xlabel("정류장 1km 밖 마을 비율 (%)"); ax.set_title("시군별 정류장 1km 밖 마을 비율")
    plt.savefig(OUT / "fig3_sgg_far_share.png", dpi=200, bbox_inches="tight"); plt.close()

    # 그림 4: 사각지대 지수
    ax = land.plot("blind_idx", cmap="Reds", legend=True, figsize=(8, 8), edgecolor="white", linewidth=0.2,
                  missing_kwds={"color": "#e4e4e4", "hatch": "///", "edgecolor": "white", "label": "운행 자료 부족·마을 3곳 미만"},
                  legend_kwds={"label": "사각지대 지수", "shrink": 0.6})
    sgg.boundary.plot(ax=ax, color="#555", linewidth=0.6)
    top = land.nlargest(10, "blind_idx")
    for _, r in top.iterrows():
        p = r.geometry.representative_point()
        ax.annotate(r.adm_nm.split()[-1], (p.x, p.y), fontsize=7, ha="center")
    ax.set_title("교통 사각지대 지수 상위 읍면"); ax.set_axis_off()
    plt.savefig(OUT / "fig4_blind_index.png", dpi=200, bbox_inches="tight"); plt.close()

    # 그림 5: 마을별 버스 서비스 (운행 횟수 반영)
    vs_p = OUT / "villages_service.gpkg"
    if vs_p.exists():
        vs = gpd.read_file(vs_p)
        vs = vs[vs.adm_cd2.isin(land.adm_cd2)]
        ax = land.plot(color="#f2f2f2", edgecolor="white", linewidth=0.2, figsize=(8, 8))
        sgg.boundary.plot(ax=ax, color="#999", linewidth=0.5)
        nodata = vs[~vs.tago_ok]
        if len(nodata):
            nodata.plot(ax=ax, markersize=3, color="#cccccc", label=f"운행 자료 없음 ({len(nodata):,})")
        ok = vs[vs.tago_ok]
        for cat, color, size in [("6회 이상", "#7aa6c2", 3), ("하루 5회 이하", "#fd8d3c", 7), ("버스 없음", "#d7301f", 7)]:
            g = ok[ok.service == cat]
            g.plot(ax=ax, markersize=size, color=color, label=f"1km 안 {cat} ({len(g):,})")
        ax.legend(loc="upper left", bbox_to_anchor=(0, -0.02), frameon=False)
        ax.set_title("마을 1km 안 정류장의 하루 버스 정차 횟수"); ax.set_axis_off()
        plt.savefig(OUT / "fig5_village_service.png", dpi=200, bbox_inches="tight"); plt.close()

    cols = ["adm_nm", "pop65", "aged_ratio", "n_stops", "n_vil", "vil_far_1km", "far_share", "blind_idx_dist", "blind_idx"]
    if "vil_no_bus" in emd:
        cols[6:6] = ["vil_no_bus", "vil_low_bus", "vil_med_trips", "hard_share"]
    top20 = emd.nlargest(20, "blind_idx")[cols]
    top20.to_csv(OUT / "top20_blind.csv", index=False, encoding="utf-8-sig")
    emd.drop(columns="geometry").to_csv(OUT / "emd_index.csv", index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 200)
    print(top20.round(2).to_string(index=False))


if __name__ == "__main__":
    main()
