# MIDAS Floor Load Auto v4

`midas_floorload_auto_v4`는 기존 `midas_floorload_auto_v3`의 PDF 설계하중표 → MGTX 하중 타입 생성 기능을 보존하면서, MIDAS Gen NX 모델에서 Story 기반 center line DXF를 생성하고 사용자가 CAD에서 입력한 HATCH/폐합 Polyline 하중 영역을 full MGT에 삽입하는 데스크톱 자동화 프로그램입니다.

## 1. 주요 기능

1. MIDAS Gen NX REST API 연결 테스트
2. `.mgb/.mgbx/.mcb` 모델 `doc/OPEN`
3. `doc/EXPORTMXT`로 full MGT export
4. `*STORY`, `*NODE`, `*ELEMENT` 파싱
5. 선택 Story 기준 center line DXF 템플릿 생성
6. 하중명/DL/LL 레이어 자동 생성 및 JSON/CSV 매핑 저장
7. 사용자 작성 DXF에서 `HATCH` 우선, closed `LWPOLYLINE/POLYLINE` fallback으로 하중 영역 인식
8. 선택 Story 노드에 polygon vertex snap
9. `*FLOADTYPE`, `*FLOORLOAD` 블록을 full MGT에 삽입
10. `doc/NEW` → `doc/IMPORTMXT` → `doc/SAVEAS` 방식으로 새 `.mgb` 저장
11. 결과 보고서 `.xlsx/.csv`, 검증 DXF, 날짜별 로그 생성

원본 `.mgb`는 직접 덮어쓰지 않습니다.

## 2. 폴더 구조

```text
midas_floorload_auto_v4/
  app/
    main.py
    core/
      midas_api_client.py
      mgt_parser.py
      dxf_template_writer.py
      dxf_load_reader.py
      load_parser.py
      story_extractor.py
      floorload_mgt_builder.py
      validators.py
    utils/
      logger.py
      config.py
      path_utils.py
  legacy_v3/
    streamlit_app.py
    src/
    config/
  DATA/
    OUTPUT/
      {project_name}/
        dxf_templates/
        imported_dxf/
        mgt/
        models/
        reports/
        pdf_jobs/
  logs/
  build/
    build_exe.bat
    build_debug_exe.bat
  user_config/
    midas_floorload_auto_config.example.json
  tests/
  requirements.txt
  Run_midas_floorload_auto.bat
```

## 3. 설치 및 개발 실행

Windows PowerShell 또는 CMD에서:

```bat
cd midas_floorload_auto_v4
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m app.main
```

`ezdxf`, `shapely`, `pandas`, `openpyxl`, `requests`가 핵심 의존성입니다.

## 4. EXE 빌드

GUI 전용 빌드:

```bat
build\build_exe.bat
```

디버그 콘솔 포함 빌드:

```bat
build\build_debug_exe.bat
```

빌드 후 기본 실행:

```bat
Run_midas_floorload_auto.bat
```

## 5. MIDAS API 설정

GUI의 `1 API 설정` 탭에서 다음을 입력합니다.

- Base URL: 예) `https://moa-engineers.midasit.com:443/gen`
- Port: 별도 포트를 쓸 때만 입력
- MAPI Key: MIDAS Gen NX 세션의 MAPI Key
- Timeout: export/import가 오래 걸리는 모델은 180~600초 권장

연결 테스트는 `db/STOR`, `db/NODE`, `doc/INFO` 후보를 순서대로 확인합니다. API는 실행 중인 MIDAS Gen NX client/session과 연결되어 있어야 합니다.

## 6. 사용 순서

### 6.1 모델/Story 읽기

1. `2 모델/Story` 탭에서 `.mgb/.mgbx/.mcb` 선택
2. `API로 열기 + MGT Export + Story 읽기` 클릭
3. Story 목록에서 입력 대상 Story 선택

오프라인 검토 또는 디버그 시에는 `MGT 직접 읽기`로 기존 `.mgt/.mgtx`를 파싱할 수 있습니다.

### 6.2 DXF 템플릿 생성

1. `3 DXF 생성/검증` 탭에서 모델링 입력 하중목록 또는 PDF 하중목록을 체크
2. 오른쪽 `최종 적용 하중목록`에 반영되는지 확인

```text
사무실, DL:1.2 LL:3.0
복도, DL:1.0 LL:4.0
화장실, DL:1.5 LL:2.0
기계실, DL:2.0 LL:5.0
```

3. `선택 Story center line DXF 생성` 클릭
4. `DATA/OUTPUT/{project_name}/dxf_templates/`에 DXF와 `.layer_mapping.json/.csv` 자동 생성

### 6.3 CAD 작업 규칙

- 기본 입력 방식: `HATCH`
- 보조 입력 방식: closed `LWPOLYLINE` 또는 closed `POLYLINE`
- 하중 영역은 `LOAD_*` 레이어에 작성
- 열린 polyline은 자동 폐합하지 않습니다.
- 원점/좌표축은 MIDAS 모델 XY와 동일해야 합니다.

## 7. DXF 레이어명 규칙

지원 입력:

```text
사무실, DL:1.2 LL:3.0
사무실 DL:1.2 LL:3.0
사무실,DL:1.2,LL:3.0
사무실_DL_1.2_LL_3.0
LOAD_001_사무실_DL_1.2_LL_3.0
```

템플릿 생성 시 CAD 안전 레이어명으로 변환됩니다.

예:

```text
LOAD_001_사무실_DL_1.2_LL_3
```

원본 실명/DL/LL은 JSON/CSV 매핑 파일에 저장됩니다.

## 8. MGT 입력 방식

1. 기존 모델 full MGT를 보존합니다.
2. `*FLOADTYPE`에 기존에 없는 하중 타입만 추가합니다.
3. `*FLOORLOAD`에 하중 영역별 node polygon을 추가합니다.
4. 기본 floor load 형식은 기존 MIDAS 샘플에 맞춰 `iDIST=2`, `DIR=GZ`, `bPROJ=NO`, `bAL=YES`, `GROUP=DXF_FLOORLOAD`입니다.
5. DL/LL 값은 MIDAS 중력방향 입력 관행을 고려해 음수로 기록합니다.
6. 기존 재료/단면/절점/요소/경계조건/해석조건은 수정하지 않습니다.

## 9. 결과 파일

- `DATA/OUTPUT/{project_name}/mgt/*_floorload_full.mgt`
- `DATA/OUTPUT/{project_name}/models/*_floorload_added.mgb`
- `DATA/OUTPUT/{project_name}/reports/*_floorload_report.xlsx`
- `DATA/OUTPUT/{project_name}/reports/*_floorload_report.csv`
- `DATA/OUTPUT/{project_name}/reports/*_floorload_preview.dxf`
- `logs/floorload_YYYYMMDD.log`

## 10. 오류 해결

| 메시지 | 조치 |
|---|---|
| MIDAS Gen NX API 연결에 실패했습니다 | MIDAS 실행 여부, Base URL, Port, MAPI Key 확인 |
| Story 정보가 없습니다 | MGT `*STORY` 또는 API `db/STOR` 응답 확인 |
| 선택 Story Level의 노드가 없습니다 | Story tolerance 증가 또는 Story 선택 확인 |
| 선택한 DXF에서 하중 해치를 찾지 못했습니다 | HATCH 또는 폐합 LWPOLYLINE 작성 여부 확인 |
| 레이어명에서 DL/LL 값을 읽을 수 없습니다 | DXF 생성 시 자동 저장된 `.layer_mapping.json/.csv` 또는 LOAD 레이어명 확인 |
| 최대 snap 오차 초과 | CAD 원점/축 방향, 모델 단위, Story 선택 확인 |
| MGT import 실패 | full MGT encoding, MIDAS 버전, 기존 모델 데이터 오류 확인 |

## 11. 테스트

```bat
python -m pytest -q
```

`ezdxf`가 없는 환경에서는 DXF fallback 테스트만 skip될 수 있습니다. 실제 사용 환경에서는 `requirements.txt` 설치 후 전체 테스트가 수행됩니다.

## 12. 기존 v3 기능

기존 PDF 설계하중표 → MGTX 변환 소스는 `legacy_v3/`에 보존했습니다. GUI의 `기존 v3 Streamlit 실행` 버튼으로 실행할 수 있습니다.

```bat
python -m streamlit run legacy_v3\streamlit_app.py
```

## V4.1 업데이트: V3 PDF 하중표 인식 기능 복원

V4.1에서는 V3에 있던 `구조계산서 PDF → 설계하중표 인식 → MIDAS MGTX/FLOADTYPE 생성` 기능을 Tkinter V4 GUI 안으로 다시 통합했습니다.

### 탭 흐름

기본 탭 구조는 기존 V4 흐름을 유지합니다.

```text
1 API 설정
2 모델/Story
3 DXF 생성/검증
4 MGT 입력/저장
로그
```

2번 탭에서 모델을 API로 열어 MGT를 export하거나, 오프라인 MGT를 직접 읽으면 프로그램이 자동으로 다음 항목을 분석합니다.

- `*FLOORLOAD` 배정 존재 여부
- `*FLOADTYPE` 존재 여부
- `*STLDCASE` 존재 여부

`*FLOORLOAD` 배정이 이미 존재하면 PDF 입력은 필수로 진행하지 않아도 됩니다. 기존 흐름대로 DXF 검증 또는 MGT 입력/저장 단계로 진행할 수 있습니다.

`*FLOORLOAD` 배정이 없으면 2번 탭의 `PDF로 하중 입력하기` 버튼을 눌러 선택 기능 탭을 열 수 있습니다. 이때 탭 구조는 다음처럼 바뀝니다.

```text
1 API 설정
2 모델/Story
3 PDF 하중 입력(선택)
4 DXF 생성/검증
5 MGT 입력/저장
로그
```

### PDF 하중 입력 탭 기능

`3 PDF 하중 입력(선택)` 탭에서는 다음을 수행할 수 있습니다.

1. 구조계산서 PDF 추가
2. `PDF 분석 및 MGTX 생성`
3. V3 파이프라인으로 하중표 인식
4. `*STLDCASE`, `*FLOADTYPE`가 포함된 MIDAS MGTX 생성
5. 분석 로그 Excel/JSON/error log 생성
6. PDF에서 추출한 하중명을 V4 DXF 레이어 입력 형식으로 변환
7. `PDF 하중목록 전체 선택` 버튼 또는 DXF 생성 탭 체크박스로 최종 적용 하중목록에 반영
8. 선택적으로 `PDF MGTX를 현재 MGT에 병합`하여 full MGT에 PDF 기반 하중 타입을 추가

### 기존 하중과 충돌 방지

- 기존 모델에 `*FLOORLOAD`가 있으면 기존 하중을 유지하는 것을 기본 흐름으로 둡니다.
- PDF 기능을 열어도 원본 `.mgb`는 직접 덮어쓰지 않습니다.
- `PDF MGTX를 현재 MGT에 병합`할 때 기존 `STLDCASE` 또는 `FLOADTYPE` 이름이 있으면 기본적으로 skip합니다.
- 병합 결과는 `DATA/OUTPUT/{project_name}/mgt/` 아래 새 MGT 파일로 생성됩니다.
- 병합된 MGT를 사용하면 이후 DXF 기반 `*FLOORLOAD` 배정 생성 단계에서 PDF에서 추출된 하중 타입명과 연계할 수 있습니다.

### PDF 기능 관련 산출물

PDF 분석 실행 시 다음 폴더가 생성됩니다.

```text
DATA/OUTPUT/{project_name}/pdf_jobs/{model_name}_pdf_load/
  source_pdfs/            # 사용자가 선택한 PDF 복사본
  midas_auto_define_floor_load_type.mgtx
  auto_input_log.xlsx
  auto_input_log.json
  error_log.txt
  pdf_load_layers.csv     # DXF 레이어 입력용 하중명, DL, LL 목록
```

### 주의사항

- OCR이 필요한 스캔 PDF는 Tesseract 설치 상태에 따라 인식률이 달라질 수 있습니다.
- PDF 단계는 선택 기능입니다. 모델에 이미 FLOOR LOAD가 입력되어 있으면 생략해도 됩니다.
- PDF 기능은 하중 타입과 하중값을 만드는 단계이고, 실제 하중 영역 배정은 기존 V4의 DXF HATCH/폐합 polyline 기반 워크플로우로 수행합니다.
