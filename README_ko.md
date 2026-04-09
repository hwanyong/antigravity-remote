# Antigravity Remote Bridge 🌉

[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg?logo=fastapi)](https://fastapi.tiangolo.com)
[![Textual](https://img.shields.io/badge/Textual-TUI-purple.svg)](https://textual.textualize.io/)
[![macOS Support](https://img.shields.io/badge/macOS-supported-lightgrey.svg?logo=apple)]()

*[Read this in English](README.md)*

**Antigravity Remote Bridge**는 Antigravity IDE (VS Code 기반) 인스턴스를 외부에서 제어하고 모니터링하기 위한 백그라운드 브릿지 및 TUI 시스템입니다. 
터미널을 떠나지 않은 채로 백그라운드 IDE의 AI 에이전트와 대화하고, 파일 탐색기 및 Git 상태를 관리하세요!

---

## ✨ Features

*   **📱 TUI First**: 모바일 퍼스트 아키텍처로 설계된 세련된 `Textual` 기반의 터미널 인터페이스 제공.
*   **🔌 멀티 워크스페이스**: 시스템에 켜져 있는 여러 개의 Antigravity 창을 자동 감지하고 각각 독립적으로 연결.
*   **🤖 AI 에이전트 원격 제어**: 에이전트에 프롬프트 주입(`CMD_INJECT_PROMPT`), 상태 확인, AI가 수정한 코드 수락/거절을 터미널에서 즉시 처리.
*   **🕵️ macOS 네이티브 스크래핑**: PyObjC를 사용한 `Accessibility (AX)` 및 `Quartz` 화면 캡처 기술로 플러그인 없이 IDE 요소 직접 접근.
*   **⚡ 실시간 스트리밍**: FastAPI 및 WebSockets를 활용하여 푸시(Push) 기반의 델타 이벤트(파일 생성, Git 상태 변경 등) 고속 처리.

## 🏗️ Architecture

이 프로젝트는 두 가지 주요 컴포넌트로 나뉘어져 있습니다:

1.  **`server` (`agbridge-server`)**: 백그라운드에서 실행되며 권한 접근을 통해 IDE 데이터를 수집하는 WebSocket 푸시 서버(데몬)입니다.
2.  **`client` (`agbridge-tui`)**: 서버에 연결하여 데이터를 실시간으로 보여주고 사용자의 명령 세션을 전달하는 터미널 대시보드(TUI)입니다.

## 🚀 Getting Started

### 1. Server 실행
데몬(서버)은 현재 **macOS** 에서만 동작하며 초기 실행 시 필수 OS 권한 승인이 요구됩니다.

```bash
# 1. 서버 폴더로 이동 및 가상환경 설정
cd server/
python3 -m venv .venv
source .venv/bin/activate

# 2. 필수 패키지 설치
pip install -e .

# 3. 브릿지 서버 구동
agbridge-server --log-level ERROR
```
> **Note**: 최초 실행 시 시스템 환경설정에서 파이썬 실행 파일에 대해 **손쉬운 사용 (Accessibility)** 및 **화면 기록 (Screen Recording)** 권한을 허용해야 합니다.

### 2. Client 실행 (새 터미널 열기)

```bash
# 1. 클라이언트 폴더로 이동 및 가상환경 설정
cd client/
python3 -m venv .venv
source .venv/bin/activate

# 2. 필수 패키지 설치
pip install -e .

# 3. TUI 실행
agbridge-tui
```

## ⌨️ Keybindings (TUI)

TUI 내에서는 다음과 같은 단축키를 통해 마우스 조작 없이 모든 메뉴를 오갈 수 있습니다:
- `Ctrl + W`: 워크스페이스 목록 패널
- `Ctrl + A`: AI 에이전트 패널
- `Ctrl + E`: 📁 파일 탐색기
- `Ctrl + G`: 🌲 Git 제어 패널
- `F1 ~ F4`: 각 기능 드롭다운 메뉴 활성화
- `F10`: ⚙️ 설정 & 이벤트 로깅, 네트워크 상태 확인

## 🤝 Contributing

버그 제보나 기능 추가, 코드 개선 등은 모두 환영합니다! 개선을 위한 Pull Request를 자유롭게 열어주세요. 

1. 이 저장소 Fork 하기
2. Feature 브랜치 생성 (`git checkout -b feature/AmazingFeature`)
3. Commit 작성 (`git commit -m 'Add some AmazingFeature'`)
4. Branch 푸쉬 (`git push origin feature/AmazingFeature`)
5. Pull Request 생성

## 📄 License
이 프로젝트는 MIT 라이선스에 따라 배포됩니다. 자세한 내용은 `LICENSE` 파일을 확인하세요.
