# MIDAS FLOOR LOAD TOOL Windows 사내 배포 가이드

이 문서는 Python을 설치하지 않은 직원 PC에서 `MIDAS FLOOR LOAD TOOL`을 실행할 수 있도록 Windows EXE와 선택적 설치파일을 만드는 절차를 정리한 문서입니다.

## 권장 빌드 방식

- 일반 배포: PyInstaller `onedir + windowed`
- 디버그 배포: PyInstaller `onedir + console`
- 초기 사내 배포에서는 `onefile`을 권장하지 않습니다. 실행 시 임시 압축 해제가 필요하고 백신/Windows Defender 오탐 가능성이 커질 수 있습니다.
- UPX 압축은 사용하지 않습니다.

## 빌드 PC 준비

권장 환경:

- Windows 10/11
- Python 3.11 또는 3.12 중 하나로 고정
- 프로젝트 루트에서 가상환경 사용

예시:

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller pyinstaller-hooks-contrib
```

`build` 배치 파일은 `pip install -r requirements.txt`를 자동 실행하지 않습니다. 빌드 PC 환경을 예측 가능하게 유지하기 위해 필요한 패키지는 위 명령으로 먼저 설치하세요.

## 일반 EXE 빌드

프로젝트 루트에서 실행합니다.

```bat
build\build_exe.bat
```

빌드 결과:

```text
dist\midas_floorload_auto_v4\midas_floorload_auto_v4.exe
```

이 폴더 전체를 공유하면 직원은 Python 없는 PC에서도 `midas_floorload_auto_v4.exe`를 실행할 수 있습니다.

## Python 없는 직원 PC에 배포하는 방법

PyInstaller onedir 배포에서는 exe 하나만 보내면 안 됩니다.  
반드시 아래 폴더 전체를 배포해야 합니다.

```text
dist\midas_floorload_auto_v4\
```

직원에게 직접 전달할 ZIP은 아래 bat로 생성합니다.

```bat
build\package_release_zip.bat
```

생성 결과:

```text
dist_release\MIDAS_FLOOR_LOAD_TOOL_v1.0.0_YYYYMMDD_HHMM.zip
```

이 ZIP만 직원에게 전달하세요. `build\midas_floorload_auto_v4` 폴더나 `midas_floorload_auto_v4.exe` 단독 파일은 배포하지 마세요.

## 직원 PC에서 실행하는 방법

1. 배포 담당자가 전달한 `MIDAS_FLOOR_LOAD_TOOL_v1.0.0_YYYYMMDD_HHMM.zip` 파일을 한 번만 압축 해제합니다.
2. 압축 해제 후 생성된 `midas_floorload_auto_v4` 폴더를 엽니다.
3. `midas_floorload_auto_v4.exe`를 더블클릭합니다.
4. Python은 설치하지 않아도 됩니다.

### base_library.zip 주의사항

`midas_floorload_auto_v4\_internal\base_library.zip` 파일은 PyInstaller 실행파일이 내부적으로 사용하는 Python 런타임 파일입니다.

이 파일은 추가로 압축 해제하지 마세요.  
압축파일 상태 그대로 `_internal` 폴더 안에 있어야 프로그램이 정상 실행됩니다.

직원은 배포 ZIP만 한 번 압축 해제하면 됩니다.

잘못된 사용:

- `_internal\base_library.zip`을 추가로 압축 해제함
- `midas_floorload_auto_v4.exe`만 따로 복사해서 실행함
- `build\midas_floorload_auto_v4` 폴더를 배포함
- `Analysis-00.toc`, `EXE-00.toc`, `PYZ-00.pyz`, `.pkg` 파일이 들어 있는 ZIP을 배포함

올바른 사용:

- `dist_release`에 생성된 배포 ZIP을 한 번만 압축 해제
- 폴더 구조를 유지한 상태로 `midas_floorload_auto_v4.exe` 실행

## 디버그 EXE 빌드

오류 분석용 콘솔 실행파일은 아래 명령으로 만듭니다.

```bat
build\build_debug_exe.bat
```

빌드 결과:

```text
dist\midas_floorload_auto_v4_debug\midas_floorload_auto_v4_debug.exe
```

직원 PC에서 문제가 발생하면 이 디버그 EXE로 실행해 콘솔 오류 메시지와 `logs` 폴더의 로그를 함께 확보하세요.

## 설치파일 생성

먼저 일반 EXE 빌드를 완료해야 합니다. 아래 파일이 없으면 Inno Setup 컴파일 전에 `build\build_exe.bat`를 먼저 실행하세요.

```text
dist\midas_floorload_auto_v4\midas_floorload_auto_v4.exe
```

Inno Setup 6이 설치된 PC에서 실행합니다.

```bat
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\midas_floorload_auto_v4.iss
```

설치파일 결과:

```text
dist_installer\MIDAS_FLOOR_LOAD_TOOL_Setup_1.0.0.exe
```

설치 기본 위치는 다음과 같습니다.

```text
%LOCALAPPDATA%\MIDAS_FLOOR_LOAD_TOOL
```

관리자 권한이 필요 없는 사용자별 설치 방식입니다.

## 압축 해제도 어렵다면 설치파일 방식 사용

직원이 압축 해제 과정도 어려워한다면 Inno Setup으로 생성한 설치파일을 배포합니다.

설치파일 예:

```text
dist_installer\MIDAS_FLOOR_LOAD_TOOL_Setup_1.0.0.exe
```

이 방식은 직원이 설치파일을 실행하면 자동으로 필요한 파일이 설치되므로 `_internal`, `base_library.zip` 같은 내부 파일을 볼 필요가 없습니다.

## 직원 PC 테스트 체크리스트

배포 전 Python 없는 PC 또는 깨끗한 테스트 계정에서 아래 항목을 확인하세요.

- Python 없는 PC에서 일반 EXE 실행
- 한글 경로와 한글 파일명으로 MGT/MGTX/DXF 파일 열기
- MGT/MGTX 읽기
- DXF 생성/검증
- 진단 DXF 생성
- PDF 기능 사용 시 OCR/Tesseract 필요 여부 확인
- MIDAS API 연결 테스트
- `logs`, `DATA`, `user_config` 쓰기 권한 확인
- 설치파일로 설치 후 시작 메뉴 바로가기 실행
- 바탕화면 바로가기 옵션 선택 시 바로가기 실행

## 백신/Windows Defender 오탐 감소 지침

- `onefile`보다 `onedir` 배포를 우선 사용하세요.
- UPX 압축을 사용하지 마세요.
- 가능한 경우 EXE와 installer에 회사 코드 서명을 적용하세요.
- 사내 백신 또는 Windows Defender allowlist에 배포 폴더와 설치파일을 등록하세요.
- 설치파일을 사내 공유폴더에서 배포하고, 파일 해시와 버전을 함께 공지하세요.

## 버전 관리

설치 스크립트의 버전은 `installer\midas_floorload_auto_v4.iss` 상단에서 관리합니다.

```ini
#define MyAppVersion "1.0.0"
```

버전 예시:

- `1.0.0`: 최초 배포
- `1.0.1`: 버그 수정
- `1.1.0`: 기능 추가

공유폴더 배포 예시:

```text
\\사내공유\프로그램\MIDAS_FLOOR_LOAD_TOOL\1.0.0\
```

권장 구성:

```text
\\사내공유\프로그램\MIDAS_FLOOR_LOAD_TOOL\1.0.0\dist\midas_floorload_auto_v4\
\\사내공유\프로그램\MIDAS_FLOOR_LOAD_TOOL\1.0.0\MIDAS_FLOOR_LOAD_TOOL_Setup_1.0.0.exe
\\사내공유\프로그램\MIDAS_FLOOR_LOAD_TOOL\1.0.0\README_DEPLOY.md
```

## 문제 발생 시 오류 로그 확보

1. 일반 EXE에서 문제가 발생한 직원 PC에 디버그 빌드 폴더를 전달합니다.
2. 아래 파일을 실행합니다.

```text
dist\midas_floorload_auto_v4_debug\midas_floorload_auto_v4_debug.exe
```

3. 콘솔 창에 표시되는 오류 메시지를 캡처합니다.
4. 실행 폴더 아래의 `logs` 폴더와 작업 중 생성된 `DATA` 폴더를 함께 압축합니다.
5. 사용한 입력 파일 경로, MIDAS API 연결 방식, 실행한 탭/버튼 순서를 기록합니다.

## package_release_zip.bat 검증 실패: legacy_v3/user_config 누락

오류 예:

```text
[ERROR] Missing required distribution files/folders:
  dist\midas_floorload_auto_v4\legacy_v3
  dist\midas_floorload_auto_v4\user_config
```

원인:

PyInstaller 6.x onedir 빌드에서는 data 파일이 `_internal` 아래로 들어갈 수 있습니다.  
하지만 이 프로그램은 exe가 있는 폴더를 기준으로 `legacy_v3`, `user_config`를 찾습니다.

해결:

`build\build_exe.bat`의 post-build copy 단계가 `legacy_v3`, `user_config`, `resources`를 `dist\midas_floorload_auto_v4` 루트로 복사해야 합니다.  
`build\package_release_zip.bat`는 일반 빌드 후 다시 `build\validate_distribution.py`를 실행하므로, 이 복사 단계가 실패하면 ZIP 생성을 중단합니다.

주의:

`user_config\*.local.json`에는 개인 MAPI Key가 들어갈 수 있으므로 직원 배포 ZIP에는 기본 포함하지 않습니다.  
배포용 기본 설정은 `user_config\*.example.json`처럼 민감 정보가 없는 파일로 관리하세요.

## 전체 배포 순서 요약

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller pyinstaller-hooks-contrib

build\build_exe.bat
build\build_debug_exe.bat
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\midas_floorload_auto_v4.iss
```
