"""TAGO 노선 자료로 정류장별 하루 버스 정차 횟수를 추정하고, 마을·읍면 단위로 붙인다.

노선 하루 운행 횟수 = (막차 - 첫차) / 배차간격 + 1. 배차간격이 없거나 첫차 = 막차면 1회.
  (농촌 노선은 운행 한 번이 노선 하나로 등록된 경우가 많다)
정류장 정차 횟수 = 그 정류장을 지나는 노선들의 운행 횟수 합 (상·하행 합)
마을 서비스 = 마을 1km 안 정류장 중 정차 횟수가 가장 많은 정류장의 값
입력: data/raw/tago (03_fetch_tago.py), out/villages.gpkg, out/emd.gpkg (01_build.py)
출력: out/stops_service.gpkg, out/villages_service.gpkg, out/emd_service.csv
"""
import json
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TAGO = ROOT / "data" / "raw" / "tago"
OUT = ROOT / "out"
CRS_M = 5179
WALK_M = 1000
LOW_TRIPS = 5  # 하루 정차 5회 이하 = 왕복 3회 미만 (농어촌서비스기준 "하루 3회 이상" 미달)
MAX_UNKNOWN = 0.15  # 운행 횟수를 알 수 없는 노선 비율이 이보다 크면 그 시군은 판단 보류


def hhmm(v):
    if v is None or str(v).strip() == "":
        return None
    s = str(v).zfill(4)
    return int(s[:2]) * 60 + int(s[2:]) if s.isdigit() else None


def route_trips(info):
    """(하루 운행 횟수, 알 수 없음 여부). 첫차 != 막차인데 배차간격이 없으면 횟수를 알 수 없다(1회로 둔다)."""
    start, end = hhmm(info.get("startvehicletime", "")), hhmm(info.get("endvehicletime", ""))
    iv = pd.to_numeric(info.get("intervaltime"), errors="coerce")
    if start is None or end is None or end <= start:
        return 1, start is None or end is None or start != end
    if pd.isna(iv) or iv <= 0:
        return 1, True
    return int((end - start) // iv) + 1, False


def load_city(d):
    rows = []
    for rt in json.loads((d / "routes.json").read_text()):
        rid = rt["routeid"]
        info_p, stops_p = d / "info" / f"{rid}.json", d / "stops" / f"{rid}.json"
        if not stops_p.exists():
            continue
        info = (json.loads(info_p.read_text()) or [rt])[0] if info_p.exists() else rt
        trips, unknown = route_trips(info)
        for s in {x["nodeid"]: x for x in json.loads(stops_p.read_text())}.values():  # 한 노선은 정류장당 한 번
            rows.append({"city": d.name, "routeid": rid, "routetp": info.get("routetp"), "trips": trips, "unknown": unknown,
                         "nodeid": s["nodeid"], "nodenm": s["nodenm"],
                         "lat": float(s["gpslati"]), "lon": float(s["gpslong"])})
    return rows


def main():
    rows = [r for d in sorted(TAGO.iterdir()) if (d / "routes.json").exists() for r in load_city(d)]
    rs = pd.DataFrame(rows)
    st = rs.groupby("nodeid").agg(nodenm=("nodenm", "first"), city=("city", "first"), lat=("lat", "first"),
                                  lon=("lon", "first"), n_routes=("routeid", "nunique"), trips=("trips", "sum")).reset_index()
    st = gpd.GeoDataFrame(st, geometry=gpd.points_from_xy(st.lon, st.lat), crs=4326).to_crs(CRS_M)
    st.to_file(OUT / "stops_service.gpkg", driver="GPKG")
    unknown = rs.drop_duplicates("routeid").groupby("city").unknown.mean()
    covered = set(unknown[unknown <= MAX_UNKNOWN].index)

    emd = gpd.read_file(OUT / "emd.gpkg")
    vil = gpd.read_file(OUT / "villages.gpkg")
    # 마을 1km 안 정류장 중 정차 횟수 최대값 (없으면 0)
    near = gpd.sjoin(vil[["geometry"]].assign(vid=range(len(vil))), st[["trips", "geometry"]].set_geometry(st.buffer(WALK_M)),
                     predicate="within")
    best = near.groupby("vid").trips.max()
    vil["trips_1km"] = pd.Series(range(len(vil))).map(best).fillna(0).astype(int).values
    # TAGO 에 노선이 없는 시군은 판단 보류
    sgg_city = pd.read_csv(ROOT / "data" / "raw" / "stops_utf8.csv", dtype=str)
    sgg_city = sgg_city[sgg_city.도시명.str.startswith("경상북도")].drop_duplicates("도시코드")
    no_data_sgg = {n.split()[-1] for c, n in zip(sgg_city.도시코드, sgg_city.도시명) if c not in covered}
    (OUT / "tago_quality.csv").write_text(
        pd.DataFrame({"city": unknown.index, "sggnm": [sgg_city.set_index("도시코드").도시명[c].split()[-1] for c in unknown.index],
                      "routes": rs.drop_duplicates("routeid").groupby("city").size().values,
                      "unknown_share": unknown.values.round(3), "used": [c in covered for c in unknown.index]}).to_csv(index=False))
    vil["sggnm"] = vil.adm_cd2.map(emd.set_index("adm_cd2").sggnm)
    vil["tago_ok"] = ~vil.sggnm.str.replace(r"(시)(남구|북구)$", r"\1", regex=True).isin(no_data_sgg)
    vil["service"] = pd.cut(vil.trips_1km, [-1, 0, LOW_TRIPS, 1e9], labels=["버스 없음", "하루 5회 이하", "6회 이상"])
    vil.to_file(OUT / "villages_service.gpkg", driver="GPKG")

    v = vil[vil.tago_ok].groupby("adm_cd2").agg(
        vil_no_bus=("trips_1km", lambda t: (t == 0).sum()),
        vil_low_bus=("trips_1km", lambda t: ((t > 0) & (t <= LOW_TRIPS)).sum()),
        vil_med_trips=("trips_1km", "median"))
    v.reset_index().to_csv(OUT / "emd_service.csv", index=False, encoding="utf-8-sig")

    ok = vil[vil.tago_ok]
    print(f"운행 횟수 판단 가능 시군 {len(covered)} / 보류: {sorted(no_data_sgg) or '없음'}")
    print(f"노선 {rs.routeid.nunique():,} · 정류장 {len(st):,} · 정류장 정차 횟수 중앙값 {st.trips.median():.0f}")
    print(f"마을 {len(ok):,}곳: 1km 안 버스 없음 {(ok.trips_1km == 0).sum()} · 하루 5회 이하 {((ok.trips_1km > 0) & (ok.trips_1km <= LOW_TRIPS)).sum()}")


if __name__ == "__main__":
    main()
