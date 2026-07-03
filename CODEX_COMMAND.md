# CODEX 명령문

현재 작업 폴더는 `midas_floorload_auto_v4`이다. 기존 V4의 Tkinter GUI, MIDAS Gen NX REST API, MGT export/import, DXF HATCH/폐합 Polyline 기반 FLOOR LOAD 배정 흐름은 유지한다. 이번 작업의 목적은 V3에 있던 `구조계산서 PDF를 분석 및 인식하여 MIDAS MGT/MGTX 하중 입력 파일로 변환하는 기능`을 V4에 자연스럽게 복원하는 것이다.

## 작업 목표

1. V4 프로그램의 탭 구조에서 `2 모델/Story` 탭과 기존 `3 DXF 생성/검증` 탭 사이에 `PDF 하중 입력(선택)` 탭을 추가한다.
2. 단, PDF 탭은 필수 절차가 아니므로 프로그램 최초 실행 시에는 숨긴다.
3. 2번 탭에서 모델을 API로 열어 MGT를 export하거나, 사용자가 MGT/MGTX를 직접 읽으면 즉시 MGT 텍스트를 분석하여 `*FLOORLOAD` 배정 존재 여부를 확인한다.
4. `*FLOORLOAD` 배정이 있으면 기존 흐름을 유지하고 PDF 입력을 강제하지 않는다.
5. `*FLOORLOAD` 배정이 없거나 사용자가 원할 때만 `PDF로 하중 입력하기` 버튼을 통해 PDF 탭을 열 수 있게 한다.
6. PDF 탭에서는 V3 legacy 파이프라인을 재사용하여 구조계산서 PDF를 분석하고, 유효한 하중표 row를 MIDAS `*STLDCASE`, `*FLOADTYPE`가 포함된 MGTX로 생성한다.
7. 생성된 PDF 하중 결과를 V4의 DXF 레이어 입력 형식인 `하중명, DL:0.0 LL:0.0` 형태로 변환하여 DXF 생성 탭의 하중 레이어 목록에 적용할 수 있게 한다.
8. 선택적으로 V3 생성 MGTX의 `*STLDCASE`, `*FLOADTYPE`를 현재 full MGT에 병합하는 기능을 제공한다.
9. 원본 `.mgb`는 절대 직접 덮어쓰지 않는다.

## 수정 범위

- `app/main.py`
  - Notebook 구조 수정
  - 숨김 상태의 `3 PDF 하중 입력(선택)` 탭 추가
  - 2번 탭에 FLOOR LOAD 자동 분석 상태 표시 추가
  - `PDF로 하중 입력하기` 버튼 추가
  - PDF 파일 선택, 분석, 결과 표시, DXF 레이어 반영, MGTX 병합 버튼 추가
- `app/core/pdf_load_importer.py`
  - 신규 작성
  - V3 legacy 모듈을 Streamlit 없이 직접 호출
  - PDF → raw rows → parsed rows → classified rows → valid rows → MGTX 생성
  - MGT 내 `*FLOORLOAD`, `*FLOADTYPE`, `*STLDCASE` 존재 여부 분석
  - PDF valid rows를 DXF 레이어 입력 텍스트로 변환
  - PDF MGTX의 `*STLDCASE`, `*FLOADTYPE`를 full MGT에 안전 병합
- `README.md`
  - V4.1 PDF 기능 사용법 추가
- `tests/test_pdf_load_importer.py`
  - FLOOR LOAD 존재 여부 분석 테스트
  - PDF valid rows → DXF 레이어 텍스트 변환 테스트
  - PDF MGTX → full MGT 병합 테스트

## 금지 사항

- 원본 `.mgb` 파일을 직접 덮어쓰지 말 것.
- PDF 탭을 필수 단계처럼 강제하지 말 것.
- 기존 V4의 DXF HATCH/폐합 polyline 인식 흐름을 제거하거나 변경하지 말 것.
- 기존 V3 legacy 소스를 삭제하지 말 것.
- 단순 문자열 append만으로 전체 MGT를 무조건 덮어쓰지 말 것. 최소한 섹션 단위로 `*STLDCASE`, `*FLOADTYPE`, `*FLOORLOAD`를 구분하여 처리할 것.
- 기존 `*FLOORLOAD`가 존재하는 모델에서 PDF 입력을 자동 실행하지 말 것.

## 기대 동작

1. 사용자가 2번 탭에서 모델/MGT를 읽는다.
2. 프로그램이 자동으로 `*FLOORLOAD`를 분석한다.
3. 기존 FLOOR LOAD가 있으면 “기존 MGT에서 FLOOR LOAD 배정 n개를 확인했습니다” 메시지를 표시하고 기존 흐름을 유지한다.
4. FLOOR LOAD가 없으면 “PDF로 하중 입력하기” 버튼이 활성화된다.
5. 사용자가 버튼을 누르면 `3 PDF 하중 입력(선택)` 탭이 기존 2번과 DXF 탭 사이에 삽입된다.
6. 사용자가 PDF를 추가하고 분석하면 V3 로직으로 MGTX와 로그가 생성된다.
7. 사용자가 “생성된 PDF 하중을 DXF 레이어 목록에 적용”을 누르면 V4 DXF 생성 탭의 하중 레이어 목록이 PDF 기반 하중명/DL/LL 값으로 채워진다.
8. 사용자가 원하면 “PDF MGTX를 현재 MGT에 병합”으로 현재 full MGT에 PDF 기반 하중 타입을 추가한다.
9. 이후 기존 V4 DXF 기반 하중 영역 입력, MGT 생성, 새 모델 import/save as 흐름을 그대로 진행한다.

## 테스트

다음 명령으로 테스트한다.

```bat
cd /d "midas_floorload_auto_v4"
python -m pytest -q
```

기대 결과는 모든 테스트 통과이다. `ezdxf`가 없는 환경에서는 DXF 관련 테스트가 skip될 수 있으나, `pip install -r requirements.txt` 후에는 실행 가능해야 한다.
