# Antigravity Remote Bridge 🌉

### 터미널에서 AI IDE를 제어하세요 — 확장 프로그램 설치 불필요

[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg?logo=fastapi)](https://fastapi.tiangolo.com)
[![Textual](https://img.shields.io/badge/Textual-TUI-purple.svg)](https://textual.textualize.io/)
[![macOS Support](https://img.shields.io/badge/macOS-supported-lightgrey.svg?logo=apple)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![WebSocket](https://img.shields.io/badge/protocol-WebSocket-blueviolet.svg)]()

*[Read this in English](README.md)*

**Antigravity Remote Bridge** (`agbridge`)는 [Antigravity IDE](https://github.com/nicolo-ribaudo/tc39-proposal-bigint)(VS Code 기반의 에이전트 중심 AI 개발 플랫폼) 인스턴스 내의 AI 에이전트들을 터미널에서 **원격 제어, 모니터링 및 자동화**할 수 있게 해주는 고성능 백그라운드 자동화 데몬이자 컴포넌트 기반 리치 터미널 UI (TUI) 클라이언트 프로젝트입니다. 개발 생산성 극대화, 원격 AI 에이전트 오케스트레이션, 그리고 엔터프라이즈 SSH 개발 환경에 최적화되어 있습니다.

원격 환경에서도 AI 에이전트에 프롬프트를 자유롭게 주입하고, 코드 수정사항을 검토·수락·거절하며, 워크스페이스의 파일 트리를 탐색 및 Git 버전을 통합 관리하세요. 이 모든 제어 과정은 실시간 WebSocket 연결을 통해 매우 빠르고 안정적으로 처리되며, 기존 IDE 환경에 **에디터 확장 프로그램이나 별도 플러그인 설치를 일절 요구하지 않습니다(Zero Footprint)**. 

서버 엔진은 웹 기반의 프시케(Psyche)나 CDP 기반 스크래퍼들의 한계를 극복하기 위해 네이티브 **macOS Accessibility (AX) API** 및 **Quartz Window Services**를 독자적으로 융합 활용하여 OS 커널 최하단 수준에서 IDE의 상태를 안전하게 관찰하고 상호작용합니다.

---

## 📑 목차

- [왜 Antigravity Remote Bridge인가?](#-왜-antigravity-remote-bridge인가)
- [주요 기능](#-주요-기능)
- [아키텍처 개요](#-아키텍처-개요)
- [기술 스택](#-기술-스택)
- [사전 요구사항](#-사전-요구사항)
- [시작하기](#-시작하기)
- [TUI 단축키](#%EF%B8%8F-tui-단축키)
- [프로젝트 구조](#-프로젝트-구조)
- [활용 사례](#-활용-사례)
- [로드맵](#-로드맵)
- [FAQ](#-faq)
- [기여하기](#-기여하기)
- [라이선스](#-라이선스)

---

## 💡 왜 Antigravity Remote Bridge인가?

Antigravity 같은 최신 AI 기반 IDE는 코드를 계획·작성·테스트·검증하는 자율 에이전트를 실행합니다. 하지만 다음과 같은 상황이라면 어떨까요?

- 다른 창이나 다른 머신에서 작업하면서 **에이전트 활동을 모니터링**하고 싶을 때
- 컨텍스트 전환 없이 IDE의 AI 에이전트에 **프롬프트를 대기열에 넣고 주입**하고 싶을 때
- 가벼운 터미널 대시보드에서 **AI 코드 수정을 수락 또는 거절**하고 싶을 때
- IDE GUI를 열지 않고 **파일 시스템과 Git 변경사항을 실시간 관찰**하고 싶을 때

Antigravity Remote Bridge(`agbridge`)는 터미널과 IDE 내부 상태 사이의 견고한 **헤드리스 브릿지**를 제공하여 이러한 문제를 완벽히 해결합니다. 확장 프로그램도, 플러그인도 설치할 필요 없이, 가장 순수하고 안전한 네이티브 OS 수준 통합 환경을 경험하세요.

### 🌟 독보적인 기술적 장점 (Why agbridge?)

단순히 화면을 복제하기 위해 취약한 Chrome DevTools Protocol(CDP) 디버깅 연결 포트에 의존하거나 위험한 DOM 스크립트 강제 주입(Injection) 방식을 사용하는 타 브릿지 도구들과 달리, `agbridge`는 구조적인 안정성과 보안 측면에서 차원이 다른 완성도를 제공합니다:

1. **에디터 확장 프로그램 제로 (Zero Footprint)**: 전적으로 네이티브 macOS 접근성(AX) API를 사용하여 순수 OS 수준에서만 작동합니다. 무거운 VS Code 내부 플러그인을 설치하거나 유지보수, 업데이트할 필요가 전혀 없습니다.
2. **원천적인 데몬 보안성 확보 (Secure by Default)**: 구동 시 내부 IDE의 Chromium CDP 디버깅 포트를 개방하거나 주기적으로 폴링하는 낡은 방식을 완전히 배제했습니다. 인증 절차가 없거나 암호화되지 않은 CDP 웹소켓 포트 개방과 관련된 막대한 보안 취약점과 포트 충돌 리스크를 시스템 단계에서 차단합니다.
3. **DOM 구조 변경으로부터의 면역 기능**: IDE의 내부 CSS/HTML 렌더링 구조나 클래스명(class names)이 업데이트되면 기존 웹 스크래핑 툴들은 즉시 구동이 정지됩니다. 반면 `agbridge`는 OS가 표준적으로 제공하는 범용적인 macOS 네이티브 창 계층구조(Accessibility Tree)를 직접 해독하기 때문에, 불안정한 DOM 스크래핑의 한계를 완벽히 우회하며 IDE의 잦은 업데이트에도 파손되지 않는 장기적인 호환성을 보장합니다.
4. **터미널 퍼스트 전용 고속 렌더러 (TUI Performance)**: 배터리와 메모리를 다량 소모하는 무거운 웹 브라우저(Web/PWA) 클라이언트가 아닌, 시스템 자원 점유가 극도로 적은 초고속 키보드 주도형 터미널 UI(TUI) 엔진으로 정밀하게 튜닝되었습니다. 숙련된 개발자(Power User), SSH 기반 텔레메트리 연동, 그리고 CI/CD 컨테이너 파이프라인 자동화에 완벽하게 부합합니다.

---

## ✨ 주요 기능

| 기능 | 설명 |
|---|---|
| **📱 TUI 퍼스트 대시보드** | [Textual](https://textual.textualize.io/) 기반의 리치 키보드 주도 터미널 인터페이스. 워크스페이스 패널, 에이전트 채팅, 파일 탐색기, Git 컨트롤 제공. |
| **🔌 멀티 워크스페이스 지원** | 활성 상태의 모든 Antigravity IDE 창을 자동 감지하고 동시 연결. 각 워크스페이스를 독립적으로 관리. |
| **🤖 AI 에이전트 원격 제어** | 프롬프트 주입, 에이전트 상태 전환 모니터링, AI가 생성한 코드 변경사항 수락/거절 — 모두 터미널에서 처리. |
| **🕵️ 확장 프로그램 없는 macOS 스크래핑** | [PyObjC](https://pyobjc.readthedocs.io/)를 통해 macOS Accessibility (`AX`) 및 Quartz Window Capture API로 IDE 상태를 네이티브 읽기. 에디터 플러그인 불필요. |
| **⚡ 실시간 WebSocket 스트리밍** | 지속적 WebSocket 연결을 통해 파일 시스템 변경, Git 상태 업데이트, 에이전트 상태 변이를 푸시 기반 델타 이벤트로 전달. |
| **🔐 권한 허브** | TUI에서 직접 IDE 에이전트 권한(허용 / 거부 / 워크스페이스 / 전역 / 샌드박스)을 관리하는 스플릿 버튼 UI 내장. |
| **📋 이벤트 로그 & 진단** | `F10`을 통해 접근 가능한 전체 액션 이벤트 로그, 네트워크 상태 진단, 설정 패널. |

---

## 🏗️ 아키텍처 개요

```
┌─────────────────────────────────────────────────────────────┐
│                    macOS Desktop                            │
│                                                             │
│  ┌──────────────────────┐     ┌──────────────────────────┐  │
│  │   Antigravity IDE    │     │   Antigravity IDE        │  │
│  │   (워크스페이스 A)    │     │   (워크스페이스 B)        │  │
│  └──────────┬───────────┘     └──────────┬───────────────┘  │
│             │ AX API + Quartz            │                  │
│             └──────────┬─────────────────┘                  │
│                        ▼                                    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              agbridge-server (데몬)                  │    │
│  │                                                     │    │
│  │  ┌─────────────┐ ┌──────────┐ ┌──────────────────┐  │    │
│  │  │ AX Scraper  │ │ Git      │ │ File Watcher     │  │    │
│  │  │ + AX Poller │ │ Tracker  │ │ (watchdog)       │  │    │
│  │  └──────┬──────┘ └────┬─────┘ └────────┬─────────┘  │    │
│  │         └─────────────┼────────────────┘             │    │
│  │                       ▼                              │    │
│  │              ┌────────────────┐                      │    │
│  │              │ State Store    │                      │    │
│  │              │ + Engine       │                      │    │
│  │              └───────┬────────┘                      │    │
│  │                      ▼                               │    │
│  │              ┌────────────────┐                      │    │
│  │              │ FastAPI +      │                      │    │
│  │              │ WebSocket API  │                      │    │
│  │              └───────┬────────┘                      │    │
│  └──────────────────────┼──────────────────────────────┘    │
│                         │ ws://                              │
└─────────────────────────┼───────────────────────────────────┘
                          ▼
            ┌─────────────────────────────┐
            │     agbridge-tui (클라이언트) │
            │                             │
            │  ┌───────┐ ┌─────────────┐  │
            │  │에이전트│ │ 워크스페이스 │  │
            │  │패널   │ │ 매니저      │  │
            │  ├───────┤ ├─────────────┤  │
            │  │파일   │ │ Git         │  │
            │  │탐색기 │ │ 패널        │  │
            │  ├───────┤ ├─────────────┤  │
            │  │이벤트 │ │ 설정        │  │
            │  │로그   │ │ 패널        │  │
            │  └───────┘ └─────────────┘  │
            └─────────────────────────────┘
```

시스템은 독립적으로 설치 가능한 두 개의 Python 패키지로 구성됩니다:

1. **`agbridge-server`** — 네이티브 macOS API (Accessibility, Quartz)를 활용하여 IDE 상태를 지속적으로 스크래핑하고 연결된 클라이언트에 델타 업데이트를 스트리밍하는 백그라운드 WebSocket 데몬.
2. **`agbridge-tui`** — 서버에 연결하여 라이브 IDE 상태를 렌더링하고 사용자 명령(프롬프트 주입, 권한 부여 등)을 IDE에 전달하는 Textual 기반 터미널 대시보드.

---

## 🛠️ 기술 스택

### 서버 (`agbridge-server`)

| 범주 | 기술 | 용도 |
|---|---|---|
| 런타임 | Python 3.11+ | 핵심 언어 |
| 웹 프레임워크 | FastAPI 0.115+ | REST 및 WebSocket API 레이어 |
| ASGI 서버 | Uvicorn 0.34+ | 고성능 비동기 서버 |
| WebSocket | websockets 14.0+ | 지속적 양방향 통신 |
| 파일 감시 | watchdog 6.0+ | 파일 시스템 변경 감지 |
| macOS 브릿지 | PyObjC 11.0+ | 네이티브 AX 및 Quartz API 바인딩 |

### 클라이언트 (`agbridge-tui`)

| 범주 | 기술 | 용도 |
|---|---|---|
| 런타임 | Python 3.11+ | 핵심 언어 |
| TUI 프레임워크 | Textual 1.0+ | 리치 터미널 사용자 인터페이스 |
| WebSocket | websockets 14.0+ | 서버 연결 |
| HTTP 클라이언트 | httpx 0.28+ | REST API 호출 |

---

## 📋 사전 요구사항

Antigravity Remote Bridge를 실행하기 전에 다음 사항을 확인하세요:

- **macOS** (필수 — 서버가 macOS 전용 Accessibility 및 Quartz API 사용)
- **Python 3.11** 이상
- **Antigravity IDE** (최소 하나의 인스턴스가 실행 중이어야 함)
- **macOS 권한** (최초 실행 시 부여):
  - **손쉬운 사용 (Accessibility)** — 시스템 설정 → 개인정보 보호 및 보안 → 손쉬운 사용
  - **화면 기록 (Screen Recording)** — 시스템 설정 → 개인정보 보호 및 보안 → 화면 기록

> **참고**: 이 권한은 `agbridge-server`를 실행하는 Python 프로세스(또는 터미널 에뮬레이터)에 부여해야 합니다. 권한이 없으면 데몬이 IDE의 창 계층 구조를 관찰하거나 UI 요소와 상호작용할 수 없습니다.

---

## 🚀 시작하기

### 1. 서버 실행

```bash
# 서버 폴더로 이동 및 가상환경 설정
cd server/
python3 -m venv .venv
source .venv/bin/activate

# 에디터블 모드로 패키지 설치
pip install -e .

# 브릿지 서버 구동
agbridge-server --log-level ERROR
```

서버가 자동으로 실행 중인 모든 Antigravity IDE 인스턴스를 감지하고 상태 스트리밍을 시작합니다.

### 2. 클라이언트 실행 (새 터미널)

```bash
# 클라이언트 폴더로 이동 및 가상환경 설정
cd client/
python3 -m venv .venv
source .venv/bin/activate

# 에디터블 모드로 패키지 설치
pip install -e .

# TUI 대시보드 실행
agbridge-tui
```

연결이 완료되면 라이브 워크스페이스 데이터가 표시되는 멀티 패널 터미널 대시보드를 볼 수 있습니다.

---

## ⌨️ TUI 단축키

마우스를 전혀 사용하지 않고 전체 인터페이스를 탐색하세요:

| 키 | 동작 |
|---|---|
| `Ctrl + W` | 워크스페이스 패널로 전환 |
| `Ctrl + A` | AI 에이전트 패널로 전환 |
| `Ctrl + E` | 파일 탐색기로 전환 |
| `Ctrl + G` | Git 제어 패널로 전환 |
| `F1` – `F4` | 기능별 드롭다운 메뉴 열기 |
| `F10` | 설정, 진단, 이벤트 로그 |
| `Enter` | 프롬프트 전송 / 동작 확인 |
| `Shift + Enter` | 프롬프트 입력에 줄바꿈 삽입 |

---

## 📂 프로젝트 구조

```
antigravity-remote/
├── server/                     # agbridge-server 패키지
│   ├── agbridge/
│   │   ├── main.py             # 서버 진입점 및 라이프사이클
│   │   ├── api.py              # FastAPI 라우트 및 WebSocket 핸들러
│   │   ├── engine.py           # 코어 상태 디핑 및 이벤트 엔진
│   │   ├── state_store.py      # 인메모리 상태 관리
│   │   ├── input_queue.py      # 명령 큐 (프롬프트 주입, AX 액션)
│   │   ├── window_discovery.py # macOS 창 열거
│   │   ├── ide_monitor.py      # IDE 프로세스 라이프사이클 모니터
│   │   ├── workspace_supervisor.py # 워크스페이스별 오케스트레이션
│   │   ├── ui_locators.json    # 외부화된 AX UI 셀렉터
│   │   ├── config.py           # 서버 설정
│   │   ├── protocol.py         # WebSocket 메시지 프로토콜
│   │   ├── auth.py             # 권한 처리
│   │   └── collectors/         # 데이터 수집 모듈
│   │       ├── ax_scraper.py   # Accessibility 트리 파서
│   │       ├── ax_polling.py   # AX 상태 변경 폴링
│   │       └── git_tracker.py  # Git 상태 모니터
│   └── pyproject.toml
│
├── client/                     # agbridge-tui 패키지
│   ├── agbridge_tui/
│   │   ├── app.py              # Textual 애플리케이션 및 레이아웃
│   │   ├── connection.py       # WebSocket 클라이언트 매니저
│   │   ├── workspace_manager.py # 멀티 워크스페이스 상태 핸들러
│   │   ├── permissions.py      # 권한 UI 로직
│   │   ├── styles.tcss         # Textual CSS 스타일시트
│   │   ├── panels/             # UI 패널 컴포넌트
│   │   │   ├── agent_panel.py  # AI 에이전트 채팅 및 프롬프트 입력
│   │   │   ├── workspace_list.py # 워크스페이스 선택기
│   │   │   ├── explorer.py     # 파일 트리 브라우저
│   │   │   ├── git_panel.py    # Git 상태 및 작업
│   │   │   ├── event_log.py    # 액션 이벤트 로거
│   │   │   ├── settings_panel.py # 설정 패널
│   │   │   └── ...             # 네비게이션 바, 상태 헤더 등
│   │   └── modals/             # 다이얼로그 컴포넌트
│   └── pyproject.toml
│
├── tests/                      # 테스트 스위트
├── LICENSE                     # MIT 라이선스
└── README.md
```

---

## 🎯 활용 사례

- **헤드리스 AI 에이전트 모니터링** — IDE를 백그라운드에서 실행하고 가벼운 터미널 세션에서 모든 에이전트 상호작용을 모니터링.
- **멀티 워크스페이스 오케스트레이션** — 단일 대시보드에서 여러 IDE 인스턴스를 관리하고 프로젝트 간 즉시 전환.
- **원격 SSH 워크플로우** — 개발 머신에 SSH로 접속하여 실행 중인 IDE 인스턴스에 연결하고 TUI를 통해 원격 제어.
- **CI/CD 통합** — WebSocket API를 통해 프로그래밍 방식으로 프롬프트를 주입하고 에이전트 상태를 모니터링하여 자동화된 워크플로우 구축.
- **페어 프로그래밍** — 한 사람은 IDE를 조작하고 다른 사람은 별도의 터미널에서 모니터링 및 프롬프트 주입.

---

## 🗺️ 로드맵

- [ ] **Linux 지원** — 서버 AX 레이어를 AT-SPI/D-Bus로 포팅하여 Linux 호환성 확보
- [ ] **REST API 문서화** — 서버 API에 대한 OpenAPI/Swagger 자동 생성 문서
- [ ] **세션 지속성** — 재시작 후에도 TUI 세션 복원
- [ ] **플러그인 시스템** — 커스텀 데이터 소스를 위한 확장 가능한 수집기 아키텍처
- [ ] **Docker 지원** — 헤드리스 macOS 환경을 위한 컨테이너화된 서버 배포

---

## ❓ FAQ

<details>
<summary><strong>VS Code / Antigravity 확장 프로그램 설치가 필요한가요?</strong></summary>

아닙니다. 서버는 네이티브 macOS Accessibility (AX) 및 Quartz API를 사용하여 OS 수준에서 IDE를 읽고 상호작용합니다. 에디터 내부에 확장 프로그램이나 플러그인이 필요하지 않습니다.
</details>

<details>
<summary><strong>Linux나 Windows에서 작동하나요?</strong></summary>

아직은 아닙니다. 서버는 macOS 전용 API(PyObjC, ApplicationServices, Quartz)에 의존합니다. AT-SPI를 통한 Linux 지원이 로드맵에 있으며, UI Automation을 통한 Windows 지원도 검토 중입니다.
</details>

<details>
<summary><strong>일반 VS Code (Antigravity가 아닌)에서도 사용할 수 있나요?</strong></summary>

AX 스크래퍼는 Antigravity IDE 포크에 특정한 UI 요소를 대상으로 합니다. 일부 기능이 표준 VS Code에서 부분적으로 작동할 수 있지만, 완전한 호환성은 보장되지 않으며 공식적으로 지원되지 않습니다.
</details>

<details>
<summary><strong>WebSocket API가 문서화되어 있나요?</strong></summary>

프로토콜은 `server/agbridge/protocol.py`에 정의되어 있습니다. 전체 OpenAPI 문서화는 향후 릴리스에서 계획 중입니다.
</details>

<details>
<summary><strong>macOS 권한은 어떻게 부여하나요?</strong></summary>

최초 실행 시 macOS가 프롬프트를 표시합니다. 프롬프트가 나타나지 않으면 터미널 에뮬레이터(예: iTerm2, Terminal.app) 및/또는 Python 바이너리를 다음에 수동으로 추가하세요:
- **시스템 설정 → 개인정보 보호 및 보안 → 손쉬운 사용**
- **시스템 설정 → 개인정보 보호 및 보안 → 화면 기록**

그런 다음 터미널과 서버를 재시작하세요.
</details>

---

## 🤝 기여하기

버그 제보와 Pull Request를 환영합니다! 버그 수정, 새로운 기능, 문서 개선 등 — 모든 기여에 감사드립니다.

1. 이 저장소 Fork 하기
2. Feature 브랜치 생성 (`git checkout -b feature/AmazingFeature`)
3. Commit 작성 (`git commit -m 'Add some AmazingFeature'`)
4. Branch 푸쉬 (`git push origin feature/AmazingFeature`)
5. Pull Request 생성

---

## 📄 라이선스

Copyright © 2026 Hwanyong Yoo

이 프로젝트는 [MIT 라이선스](LICENSE)에 따라 배포됩니다. 자세한 내용은 `LICENSE` 파일을 확인하세요.
