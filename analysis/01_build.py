"""경북 읍면동별 고령 인구와 버스정류장 접근성 기초 지표를 만든다.

입력 (data/raw):
  stops_utf8.csv            국토교통부_전국 버스정류장 위치정보 (2025-10-31 기준)
  pop.csv                   행정안전부_지역별(행정동) 성별 연령별 주민등록 인구수 (2026-09-30 기준)
  adm_20261001.geojson      행정동 경계 (통계청 SGIS 원자료, vuski/admdongkor 가공, CC BY 4.0)
  places.geojsonseq         OpenStreetMap 마을 지점 (ODbL)
출력: out/emd.gpkg (읍면동 지표), out/villages.gpkg (마을별 최근접 정류장 거리)
"""
import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "out"
CRS_M = 5179  # 미터 단위 좌표계(UTM-K)


def load_adm():
    adm = gpd.read_file(RAW / "adm_20261001.geojson")
    adm = adm[adm.sidonm == "경상북도"].to_crs(CRS_M)
    adm["area_km2"] = adm.area / 1e6
    return adm[["adm_cd2", "adm_nm", "sggnm", "area_km2", "geometry"]]


def load_pop():
    p = pd.read_csv(RAW / "pop.csv", dtype={"행정기관코드": str})
    p = p[p.시도명 == "경상북도"]
    age = lambda lo, hi: [f"{a}세{s}" for a in range(lo, hi + 1) for s in ("남자", "여자")]
    cols = set(p.columns)
    sum_cols = lambda names: p[[c for c in names if c in cols]].sum(axis=1)
    out = pd.DataFrame({
        "adm_cd2": p.행정기관코드,
        "pop": p["계"],
        "pop65": sum_cols(age(65, 99) + ["100세 이상남자", "100세 이상여자"]),
        "pop75": sum_cols(age(75, 99) + ["100세 이상남자", "100세 이상여자"]),
    })
    out = out[~out.adm_cd2.str.endswith("00000")]  # 시도·시군구 합계 행 제외
    out["aged_ratio"] = out.pop65 / out["pop"]
    return out


def load_stops():
    s = pd.read_csv(RAW / "stops_utf8.csv", dtype=str)
    s = s[s.도시명.str.startswith("경상북도")]
    g = gpd.GeoDataFrame(s, geometry=gpd.points_from_xy(s.경도.astype(float), s.위도.astype(float)), crs=4326)
    return g.to_crs(CRS_M)


def load_villages(adm):
    rows = []
    for line in open(RAW / "places.geojsonseq", encoding="utf-8"):
        line = line.lstrip("\x1e").strip()
        if line:
            f = json.loads(line)
            if f["properties"].get("place") in ("village", "hamlet", "isolated_dwelling"):
                rows.append({"name": f["properties"].get("name"), "place": f["properties"]["place"],
                             "geometry": shape(f["geometry"])})
    v = gpd.GeoDataFrame(rows, crs=4326).to_crs(CRS_M)
    return gpd.sjoin(v, adm[["adm_cd2", "geometry"]], predicate="within").drop(columns="index_right")


def main():
    OUT.mkdir(exist_ok=True)
    adm, pop, stops = load_adm(), load_pop(), load_stops()
    stops = gpd.sjoin(stops, adm[["adm_cd2", "geometry"]], predicate="within").drop(columns="index_right")

    vil = load_villages(adm)
    vil = gpd.sjoin_nearest(vil, stops[["정류장번호", "geometry"]], distance_col="d_stop_m")
    vil = vil[~vil.index.duplicated()]

    emd = adm.merge(pop, on="adm_cd2", how="left")
    emd = emd.merge(stops.groupby("adm_cd2").size().rename("n_stops"), on="adm_cd2", how="left")
    v = vil.groupby("adm_cd2").agg(n_vil=("name", "size"),
                                  vil_far_1km=("d_stop_m", lambda d: (d > 1000).sum()),
                                  vil_med_d=("d_stop_m", "median"))
    emd = emd.merge(v, on="adm_cd2", how="left")
    emd["n_stops"] = emd.n_stops.fillna(0).astype(int)
    emd["stops_per_1k65"] = emd.n_stops / (emd.pop65 / 1000)
    emd["is_rural"] = emd.adm_nm.str.endswith(("읍", "면"))

    emd.to_file(OUT / "emd.gpkg", driver="GPKG")
    vil.to_file(OUT / "villages.gpkg", driver="GPKG")
    print(f"읍면동 {len(emd)} · 인구 매칭 {emd['pop'].notna().sum()} · 정류장 {len(stops)} · 마을 {len(vil)}")
    print(f"경북 65세 이상 {int(emd.pop65.sum()):,}명, 고령화율 {emd.pop65.sum()/emd['pop'].sum():.1%}")
    print(f"마을 {len(vil)}곳 중 1km 안에 정류장 없음 {int((vil.d_stop_m>1000).sum())}곳")


if __name__ == "__main__":
    main()
