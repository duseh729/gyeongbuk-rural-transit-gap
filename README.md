# 경북 농촌 교통 사각지대 분석

"정류장은 있어도 버스는 없다" — 경북 고령 농촌의 숨은 교통 사각지대 찾기와 수요응답형 교통(DRT) 우선 지역 제안.
AI와 함께하는 교통문제 해결을 위한 데이터 분석 공모전(숲과나눔·한겨레, 2026) 출품 코드.

## 실행

```sh
python -m venv .venv && .venv/bin/pip install geopandas pandas shapely matplotlib pyogrio
.venv/bin/python analysis/01_build.py        # 읍면동 인구·정류장·마을 결합, 마을별 최근접 정류장 거리
echo "DATA_GO_KR_KEY=<공공데이터포털 Decoding 키>" > .env
.venv/bin/python analysis/03_fetch_tago.py   # TAGO 버스노선정보 수집 (응답은 data/raw/tago 에 캐시)
.venv/bin/python analysis/04_service.py      # 정류장·마을별 하루 버스 정차 횟수
.venv/bin/python analysis/02_maps.py         # 사각지대 지수, 그림
```

`02_maps.py` 는 `04_service.py` 결과가 없으면 정류장 거리만으로 지수를 계산한다.
그림은 macOS 의 AppleGothic 글꼴을 쓴다. 다른 OS 에서는 `plt.rcParams["font.family"]` 를 바꾼다.

## 원자료 (`data/raw/`, 저장소에는 넣지 않음)

| 파일 | 데이터 | 받는 곳 |
| --- | --- | --- |
| `stops.csv` → `stops_utf8.csv` (CP949→UTF-8) | 국토교통부_전국 버스정류장 위치정보 (2025-10-31) | https://www.data.go.kr/data/15067528/fileData.do |
| `pop.csv` | 행정안전부_지역별(행정동) 성별 연령별 주민등록 인구수 (2026-09-30) | https://www.data.go.kr/data/15097972/fileData.do |
| `adm_20261001.geojson` | 행정동 경계 (통계청 SGIS 원자료, CC BY 4.0) | https://github.com/vuski/admdongkor |
| `places.geojsonseq` | OpenStreetMap place=village/hamlet (ODbL) | https://download.geofabrik.de/asia/south-korea.html 에서 `osmium tags-filter n/place` 후 `osmium export` |
| `tago/` | 국토교통부_(TAGO)_버스노선정보 | https://www.data.go.kr/data/15098529/openapi.do |

## 방법 요약

- 마을(OSM 지점)마다 1km 안 정류장 중 하루 정차 횟수가 가장 많은 값을 그 마을의 버스 서비스로 본다.
- 노선 하루 운행 횟수 = (막차 − 첫차) / 배차간격 + 1. 배차간격이 없거나 첫차 = 막차면 1회.
- 사각지대 지수 = 수요(65세 이상 인구 수·고령화율 백분위 평균) × 접근성 결핍("1km 안 버스 없음 또는 하루 5회 이하(왕복 3회 미만)" 마을 비율 백분위).
