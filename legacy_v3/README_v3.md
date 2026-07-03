# MIDAS Floor Load Auto

구조계산서 PDF의 하중표를 분석해 MIDAS GEN NX용 MGTX 파일을 생성하는 로컬 Python 자동화 도구입니다.

## 운영 원칙

샘플 PDF는 OCR/하중표 인식률 검증용입니다. 운영 로직은 특정 파일명, 특정 좌표, 특정 숫자, 특정 샘플 reference 값을 하드코딩하지 않습니다. 텍스트 레이어 품질, 이미지/스캔 여부, OCR confidence, 하중표 키워드, 단위, 행/열 정렬성, `load_value_role`, `confidence_score`를 조합해 자동 입력/검토 필요/제외를 판정합니다.

`manual_overrides.yml`은 예외 보정용이며 특정 프로젝트 값을 코드에 고정하는 용도가 아닙니다.

## 실행

```powershell
pip install -r requirements.txt
python src/main.py
streamlit run app.py
```

OCR/스캔 PDF 처리 방식, Tesseract 설치 안내, 디버그 이미지, manual override 사용법은 [docs/OCR_IMPROVEMENT.md](docs/OCR_IMPROVEMENT.md)를 참고하세요.

`구조계산서_역삼동2.pdf`처럼 텍스트 레이어가 있는 PDF는 기존 텍스트 파싱을 사용합니다. `구조계산서_역삼동3.pdf`처럼 PDF 재출력으로 페이지가 이미지화된 문서는 자동으로 `ocr_fallback`을 실행해 렌더링 이미지, 전처리 이미지, OCR bounding box overlay, 페이지 진단 JSON을 `debug/yeoksam3/`에 저장합니다.

실패 또는 검토가 필요한 경우 다음을 확인하세요.

- `output/error_log.txt`
- `output/auto_input_log.xlsx`
- `debug/yeoksam3/page_diagnostics.json`
- `debug/yeoksam_compare/`

비교 진단:

```powershell
python src/pdf_compare_diagnostics.py --reference input_pdfs/구조계산서_역삼동2.pdf --target input_pdfs/구조계산서_역삼동3.pdf --out debug/yeoksam_compare
python -m src.scan_pdf_compare_diagnostics --reference input_pdfs/구조계산서_역삼동2.pdf --targets input_pdfs/구조계산서_역삼동4.pdf input_pdfs/구조계산서_역삼동5.pdf input_pdfs/구조계산서_역삼동6.pdf --out debug/yeoksam_scan_compare
pytest
```

이 프로젝트는 외부 GPT/API, 클라우드 OCR API를 사용하지 않고 로컬/내부망 처리만 전제로 합니다.
