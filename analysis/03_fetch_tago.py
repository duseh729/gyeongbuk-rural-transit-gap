"""TAGO 버스노선정보 API로 경북 시군의 노선·노선별 경유 정류장·운행 정보를 받는다.

API: 국토교통부_(TAGO)_버스노선정보 (공공데이터포털 https://www.data.go.kr/data/15098529/openapi.do)
  getRouteNoList            시군 노선 목록
  getRouteInfoIem           노선 기본정보 (첫차·막차·배차간격)
  getRouteAcctoThrghSttnList 노선별 경유 정류장
인증키: .env 의 DATA_GO_KR_KEY (Decoding 키)
출력: data/raw/tago/{도시코드}/*.json (응답 캐시. 이미 받은 것은 다시 받지 않는다)
"""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import urllib.error
import urllib.parse
import urllib.request

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "raw" / "tago"
BASE = "https://apis.data.go.kr/1613000/BusRouteInfoInqireService"


def load_key():
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("DATA_GO_KR_KEY="):
            return line.split("=", 1)[1].strip()
    sys.exit(".env 에 DATA_GO_KR_KEY 가 없다")


KEY = load_key()


def call(op, **params):
    params = {"serviceKey": KEY, "_type": "json", "numOfRows": 1000, "pageNo": 1, **params}
    url = f"{BASE}/{op}?{urllib.parse.urlencode(params)}"
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                text = r.read().decode("utf-8")
            body = json.loads(text)["response"]
            if body["header"]["resultCode"] != "00":
                raise RuntimeError(body["header"])
            items = body["body"].get("items") or {}
            items = items.get("item", []) if isinstance(items, dict) else []
            return items if isinstance(items, list) else [items]
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as e:
            if attempt == 3:
                raise RuntimeError(f"{op} {params.get('routeId', params.get('cityCode'))}: {e}")
            time.sleep(2 ** attempt)


def cached(path, fn):
    if path.exists():
        return json.loads(path.read_text())
    data = fn()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False))
    return data


def fetch_city(city):
    d = CACHE / str(city)
    routes = cached(d / "routes.json", lambda: call("getRouteNoList", cityCode=city))

    def one(rt):
        rid = rt["routeid"]
        info = cached(d / "info" / f"{rid}.json", lambda: call("getRouteInfoIem", cityCode=city, routeId=rid))
        stops = cached(d / "stops" / f"{rid}.json", lambda: call("getRouteAcctoThrghSttnList", cityCode=city, routeId=rid))
        return len(info), len(stops)

    with ThreadPoolExecutor(12) as ex:
        res = list(ex.map(one, routes))
    print(f"{city}: 노선 {len(routes)}, 경유 정류장 합 {sum(s for _, s in res)}", flush=True)


def main():
    s = pd.read_csv(ROOT / "data" / "raw" / "stops_utf8.csv", dtype=str)
    cities = sorted(s[s.도시명.str.startswith("경상북도")].도시코드.unique())
    if len(sys.argv) > 1:
        cities = sys.argv[1:]
    for c in cities:
        fetch_city(c)


if __name__ == "__main__":
    main()
