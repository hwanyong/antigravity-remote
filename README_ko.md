# Antigravity Remote Bridge 🌉

### 터미널에서 AI IDE를 제어하세요 — 확장 프로그램 설치 불필요

[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg?logo=fastapi)](https://fastapi.tiangolo.com)
[![Textual](https://img.shields.io/badge/Textual-TUI-purple.svg)](https://textual.textualize.io/)
[![macOS Support](https://img.shields.io/badge/macOS-supported-lightgrey.svg?logo=apple)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![WebSocket](https://img.shields.io/badge/protocol-WebSocket-blueviolet.svg)]()

*[Read this in English](README.md)*

**Antigravity Remote Bridge** (`agbridge`)는 [Antigravity IDE](https://github.com/nicolo-ribaudo/tc39-proposal-bigint)(VS Code 기반의 에이전트 중심 AI 개발 플랫폼) 인스턴스 내의 AI 에이전트들을 터미널에서 **원격 제어, 모니터링 및 자동화**할 수 있게 해주는 고성능 이벤트 드리븐 백그라운드 자동화 데몬이자 컴포넌트 기반 리치 터미널 UI (TUI) 클라이언트입니다. 개발 생산성 극대화, 원격 AI 에이전트 오케스트레이션, 그리고 엔터프라이즈 SSH 개발 환경에 최적화되어 있습니다.

원격 환경에서도 독립적인 다중 라인 에디터를 활용해 AI 에이전트에 정밀한 프롬프트를 주입하고, 코드 수정사항을 검토·수락·거절하며, 워크스페이스의 파일 트리를 탐색하고 Git 버전을 통합 관리하세요. 이 모든 제어 과정은 실시간 이벤트 기반 WebSocket 연결을 통해 매우 빠르고 안정적으로 처리되며, 기존 IDE 환경에 **에디터 확장 프로그램이나 별도 플러그인 설치를 일절 요구하지 않습니다(Zero Footprint)**. 

서버 엔진은 네이티브 **macOS Accessibility (AX) API**와 고도로 타겟팅된 **Chrome DevTools Protocol (CDP)** 바인딩을 결합한 하이브리드 아키텍처를 채택하여, 창 분리부터 결정론적 DOM 이벤트 모니터링 및 상태 주입까지 완벽한 OS-레벨 제어권을 제공합니다.

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

- 다른 창이나 머신에서 작업하면서 **이벤트 기반으로 지연 없이 에이전트 활동을 모니터링**하고 싶을 때
- 외부 터미널에서 클립보드 붙여넣기 방식이 아닌, **결정론적으로 IDE 메인 에디터에 프롬프트를 직분사**하고 싶을 때
- 가벼운 다중 패널 터미널 대시보드에서 **AI 코드 수정을 수락 또는 거절**하고 싶을 때
- IDE GUI를 열지 않고 **워크스페이스의 전체 파일 시스템과 Git 트리를 실시간 탐색**하고 싶을 때

Antigravity Remote Bridge(`agbridge`)는 터미널과 IDE 내부 상태 사이의 견고한 **하이브리드 이벤트 브릿지**를 제공하여 이러한 문제를 완벽히 해결합니다. 확장 프로그램도, 플러그인도 설치할 필요 없이, 가장 순수하고 안전한 네이티브 OS 통합과 CDP 바인딩을 경험하세요.

### 🌟 독보적인 기술적 장점 (Why agbridge?)

1. **에디터 확장 프로그램 제로 (Zero Footprint)**: 전적으로 네이티브 macOS 접근성(AX) API와 윈도우 타이틀 매칭을 통한 CDP 격리 환경만을 사용합니다. 무거운 VS Code 내부 플러그인을 설치하거나 유지보수할 필요가 일절 없습니다.
2. **하이브리드 AX + CDP 이벤트 드리븐 아키텍처**: 과거의 불안정한 폴링 방식을 전면 폐기하고 `MutationObserver` (DOMWatcher) 및 CDP의 `Runtime.addBinding`을 채택했습니다. 모든 DOM과 상태 변경은 서버에서 ACK/DONE/FAIL 라이프사이클을 갖춘 실시간 WebSocket 푸시 이벤트로 변환되어, 로딩 스피너부터 AI 생성 추적에 이르기까지 지연 없는 반응성을 보장합니다.
3. **결정론적 Lexical 프롬프트 주입 (Lexical Injection)**: 타이밍 에러가 잦았던 키보드 타이핑이나 망가지는 클립보드 매크로에 의존하지 않습니다. `agbridge`는 프롬프트 멘션(`@[file]`) 및 워크플로우 토큰을 JSON 에디터 상태로 직렬화한 후, IDE 내부 Lexical 에디터에 `editor.parseEditorState()` 구문으로 직접 주입시킵니다. UTF-8 인코딩 손실과 공백 무시 문제가 완벽히 차단됩니다.
4. **엄격한 워크스페이스 격리 및 디스패치**: 여러 창이 떠 있어도 정확한 OS 윈도우 타이틀 매칭 및 CDP 타겟 개별 분리를 통해 각 프로젝트 간의 상태 충돌이나 레이스 컨디션을 물리적으로 완벽히 격리합니다.
5. **터미널 최우선(TUI) 복원력 확보**: Textual 엔진을 고도화하여 TUI 클라이언트가 서버 재시작이나 네트워크 끊김 상황에서도 죽지 않고 자동으로 재연결을 시도하는 디커플링 라이프사이클을 완성했습니다. SSH 텔레메트리와 파이프라인 지속성에 가장 완벽한 툴킷입니다.

---

## ✨ 주요 기능

| 기능 | 설명 |
|---|---|
| **📱 반응형 TUI 대시보드** | Textual로 구축된 고급 리치 인터페이스. 에이전트 채팅, 워크스페이스 제어뿐 아니라 복합 프롬프트 작성을 위한 다중 라인 `TextArea` 모달 지원. |
| **📁 전용 파일 뷰어 & 탐색기** | 불필요한 바이너리 및 미디어 파일을 자동 필터링하는 전용 파일 트리 패널과 소스 코드 오버레이 탐색기 지원. |
| **🔌 멀티 워크스페이스 동시 컨트롤** | 활성 상태의 모든 IDE 창을 감지하고, CDP 내부 식별자를 통해 프로젝트별 명령을 오차 없이 분산 라우팅. |
| **🤖 원시 토큰 보존 (Token Preserving)** | 사용자가 입력한 컨텍스트 토큰과 멘션을 순서대로 온전히 보존하여 AI 에이전트에 파손 없이 주입 및 상태 변이 모니터링 수행. |
| **🧠 완벽한 Undo & 초기화 메커니즘** | TUI에서 작업 취소 시, AX 시뮬레이션을 통해 물리적인 "Select All + Delete"를 IDE 내부에서 즉각 수행해 철저한 초기화 보장. |
| **⚡ 실시간 ACK/DONE 이벤트 통신** | 파일 시스템의 변동과 AI 에이전트의 워크플로우 이벤트가 Push 기반 WebSocket 델타 스트리밍 프로토콜 위에서 초고속 매핑됨. |
| **📋 진단 로거 (Diagnostic Recorder)** | 시스템 이상 발생 시 TUI 상태와 AX 트리 스냅샷을 실시간 보존하는 롤링 파일 핸들러(RotatingFileHandler) 인프라 지원 (`F10`을 통해 확인). |

---

## 🏗️ 아키텍처 개요

```
┌─────────────────────────────────────────────────────────────┐
│                    macOS Desktop                            │
│                                                             │
│  ┌──────────────────────┐     ┌──────────────────────────┐  │
│  │   Antigravity IDE    │     │   Antigravity IDE        │  │
│  │   (워크스페이스 A)      │     │   (워크스페이스 B)           │  │
│  └──────────┬───────────┘     └──────────┬───────────────┘  │
│             │ AX API + Quartz + CDP      │                  │
│             └──────────┬─────────────────┘                  │
│                        ▼                                    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              agbridge-server (데몬)                  │    │
│  │                                                     │    │
│  │  ┌─────────────┐ ┌──────────┐ ┌──────────────────┐  │    │
│  │  │ AX Scraper  │ │ Git      │ │ CDP Bridge       │  │    │
│  │  │ + Lexical   │ │ Tracker  │ │ + DOM Watcher    │  │    │
│  │  │ Injector    │ │          │ │                  │  │    │
│  │  └──────┬──────┘ └────┬─────┘ └────────┬─────────┘  │    │
│  │         └─────────────┼────────────────┘             │    │
│  │                       ▼                              │    │
│  │              ┌────────────────┐                      │    │
│  │              │ Event Engine   │                      │    │
│  │              │ (ACK/DONE/FAIL)│                      │    │
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
            │     agbridge-tui (클라이언트)  │
            │                             │
            │  ┌───────┐ ┌─────────────┐  │
            │  │Agent  │ │ Workspace   │  │
            │  │Chat   │ │ Manager     │  │
            │  ├───────┤ ├─────────────┤  │
            │  │File   │ │ Git         │  │
            │  │Tree   │ │ Panel       │  │
            │  ├───────┤ ├─────────────┤  │
            │  │Event  │ │ Diagnostics │  │
            │  │Log    │ │ Panel       │  │
            │  └───────┘ └─────────────┘  │
            └─────────────────────────────┘
```

시스템은 독립적으로 설치 가능한 두 개의 Python 패키지로 구성됩니다:

1. **`agbridge-server`** — macOS API를 통해 IDE 인스턴스를 발견하고 제한된 CDP 연결을 수립하는 백그라운드 데몬입니다. 이 서버는 AI의 모든 행동 이벤트를 비동기적으로 감지 및 송출하는 핵심 이벤트 엔진으로 작동합니다.
2. **`agbridge-tui`** — 서버와 생명주기가 완전히 분리된(Decoupled) 터미널 클라이언트입니다. 다중 라인 에디터를 지원하고, 워크스페이스의 파일 트리를 렌더링하며, 사용자의 프롬프트를 시퀀스 기반으로 변환하여 안전하게 서버로 전송합니다.

---

## 🛠️ 기술 스택

### 서버 (`agbridge-server`)

| 범주 | 기술 | 용도 |
|---|---|---|
| 런타임 | Python 3.11+ | 핵심 언어 |
| 웹 프레임워크 | FastAPI 0.115+ | REST 및 WebSocket API 레이어 |
| WebSocket | websockets 14.0+ | ACK/DONE/FAIL 이벤트 기반 통신 프로토콜 |
| 브라우저 자동화 | PyChromeDevTools | CDP 바인딩 및 `MutationObserver` 훅 |
| macOS 브릿지 | PyObjC 11.0+ | 네이티브 시스템 창 매핑 및 AX 폴백 제어 |
| 로깅 | RotatingFileHandler | 이벤트 추적 및 스냅샷 저장 아키텍처 |

### 클라이언트 (`agbridge-tui`)

| 범주 | 기술 | 용도 |
|---|---|---|
| 런타임 | Python 3.11+ | 핵심 언어 |
| TUI 프레임워크 | Textual 1.0+ | 반응형 터미널 그리드 및 모달 렌더링 |
| 레이아웃 및 입력 | Textual TextArea | 다중 줄바꿈 지원 텍스트 에디터 엔진 |
| 연결 관리 | Auto-Reconnecting WS | 서버 강제 종류 후에도 TUI 유지 및 복구 보장 |

---

## 📋 사전 요구사항

Antigravity Remote Bridge를 실행하기 전에 다음 사항을 확인하세요:

- **macOS** (필수 — 시스템 레벨 윈도우 타이틀 조회 기능 등 전용 API 사용)
- **Python 3.11** 이상
- **Antigravity IDE** (최소 하나의 인스턴스가 실행 중이어야 함)
- **macOS 권한** (최초 실행 시 부여):
  - **손쉬운 사용 (Accessibility)** — 시스템 설정 → 개인정보 보호 및 보안 → 손쉬운 사용
  - **화면 기록 (Screen Recording)** — 시스템 설정 → 개인정보 보호 및 보안 → 화면 기록

---

## 🚀 시작하기

### 1. 서버 실행

```bash
# 서버 폴더로 이동 및 가상환경 설정
cd server/
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# 브릿지 서버 구동
agbridge-server --log-level INFO
```

### 2. 클라이언트 실행 (새 터미널)

```bash
# 클라이언트 폴더로 이동 및 가상환경 설정
cd client/
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# TUI 대시보드 실행
agbridge-tui
```

---

## ⌨️ TUI 단축키

마우스를 쓰지 않는 생산성을 위한 반응형 인터페이스 숏컷을 제공합니다:

| 키 | 동작 |
|---|---|
| `Ctrl + W` | 워크스페이스 패널로 전환 |
| `Ctrl + A` | AI 에이전트 채팅 패널로 전환 |
| `Ctrl + E` | 원격 파일 탐색기 및 뷰어 열기 |
| `Ctrl + G` | Git 제어 패널로 전환 |
| `F1` – `F4` | 기능별 드롭다운 메뉴 열기 |
| `F10` | 설정 열기, 디버깅 진단 세션 및 이벤트 로그 기록 확인 |
| `Enter` | 프롬프트 즉시 전송 / 동작 확인 |
| `Shift + Enter` | 다중 라인 에디터 (TextArea) 내부 줄바꿈 적용 |

---

## 📂 프로젝트 구조

```
antigravity-remote/
├── server/                     # agbridge-server 패키지
│   ├── agbridge/
│   │   ├── main.py             # 서버 진입점 및 라이프사이클 처리
│   │   ├── api.py              # FastAPI 라우트 및 WebSocket 연결망
│   │   ├── engine.py           # 핵심 ACK/DONE/FAIL 이벤트 비동기 엔진
│   │   ├── state_store.py      # 인메모리 상태 관리 및 브로드캐스터
│   │   ├── input_queue.py      # 프로그램 가능한 Lexical 프롬프트 상태 변이 큐
│   │   ├── window_discovery.py # macOS AX 기반 IDE 타겟 추출기
│   │   ├── ide_monitor.py      # CDP 타겟 격리 및 접속 매니저
│   │   ├── diagnostics.py      # 상태 덤프 및 RotatingFileHandler 로거
│   │   └── collectors/         # 데이터 및 돔 수집기
│   │       ├── dom_scraper.py  # CDP 기반 이벤트 디스패치 파이프라인
│   │       ├── ax_scraper.py   # 네이티브 AX 실행기 및 Undo 복원 모듈
│   │       └── git_tracker.py  # Git 상태 모니터
│   └── pyproject.toml
│
├── client/                     # agbridge-tui 패키지
│   ├── agbridge_tui/
│   │   ├── app.py              # Textual 애플리케이션 및 유연한 뷰 레이아웃 분배
│   │   ├── connection.py       # Auto-reconnect 기반 WS 추적기
│   │   ├── workspace_manager.py# 다중 워크스페이스 메모리 및 UI 스위처
│   │   ├── styles.tcss         # Textual 반응형 (Grid/Flex) 스타일시트
│   │   ├── panels/             # 구역별 UI 컴포넌트
│   │   │   ├── agent_panel.py  # 다중 라인 TextArea 입출력 및 리더
│   │   │   ├── explorer.py     # 전용 리치 트리를 통한 파일 브라우저
│   │   │   └── event_log.py    # 액션 이벤트 로거
│   │   └── modals/             # 이벤트를 구독하여 자가 종료(Auto-close)되는 모달 체계
│   └── pyproject.toml
│
├── tests/
├── LICENSE
└── README.md
```

---

## 🎯 활용 사례

- **헤드리스 AI 에이전트 모니터링** — 무거운 IDE GUI를 최소화하고, 가벼운 터미널 세션 내부에서 푸시 방식의 이벤트 기반 에이전트 액션을 실시간으로 감시할 수 있습니다.
- **다중 라인 프롬프트 엔지니어링 수행** — `TextArea`를 통해 컨텍스트 토큰을 정확히 보존하는 고난이도의 복잡한 프롬프트를 직분사합니다.
- **안정적인 멀티 워크스페이스 오케스트레이션** — 독립형 타이틀 매칭을 통해 IDE 화면이 수십 개 열려 있어도 각 프로젝트 간의 메세지 혼선 없이 단일 TUI상에서 워크스페이스를 실시간 제어할 수 있습니다.
- **원격 SSH 텔레메트리 연동** — 멀리 떨어진 서버나 컨테이너 개발 머신에 SSH로 접근해 구동 중인 IDE 배포본에 즉각 연결, 통신이 끊어지더라도 TUI의 자체 지속성 기능을 매개로 개발 파이프라인을 복구할 수 있습니다.

---

## 🗺️ 로드맵

- [ ] **Linux 지원** — 서버 AX 레이어를 AT-SPI/D-Bus로 재작성하여 완벽한 Linux 개발환경 호환성을 확보합니다.
- [ ] **OpenAPI 문서화** — 신규 도입된 Event Engine API 전용 Swagger 문서를 자동화 구축합니다.
- [ ] **세션 이력 지속성 (Persistence)** — TUI 및 IDE가 재시작되어도 기존 입력된 프롬프트나 상태 모달, 파일 탐색 이력이 보존되는 구조를 구상 중입니다.

---

## ❓ FAQ

<details>
<summary><strong>VS Code나 Antigravity 쪽 내부에 익스텐션을 설치해야만 작동하나요?</strong></summary>
아닙니다. 서버는 macOS가 기본적으로 지원하는 접근성(AX) API와 격리된 CDP 포트를 연동하여 모든 이벤트를 주고받습니다. 코어 에디터에는 어떠한 플러그인 설치나 백도어 스크립트 강제 주입도 요구하지 않습니다.
</details>

<details>
<summary><strong>입력 속도나 프롬프트 주입 안정성은 얼마나 뛰어난가요?</strong></summary>
과거처럼 키보드를 빠르게 무작위로 치게 만들고 클립보드를 오염시키던 낡은 방식에서 완전히 벗어났습니다. `agbridge`는 당신의 문장과 코드, 토큰들을 JSON 에디터 트리 포맷으로 직렬화한 후, IDE 속 Lexical 코어 본체에 파싱(`parseEditorState`) 함수로 즉각 주입시킵니다. 타이밍 꼬임에 의한 오류나 한글 및 특수문자 깨짐이 제로에 수렴합니다.
</details>

---

## 🤝 기여하기

버그 제보와 Pull Request를 언제나 환영합니다! 

1. 이 저장소 Fork 하기
2. Feature 브랜치 생성 (`git checkout -b feature/AmazingFeature`)
3. Commit 작성 (`git commit -m 'Add some AmazingFeature'`)
4. Branch 푸쉬 (`git push origin feature/AmazingFeature`)
5. Pull Request 생성

---

## 📄 라이선스

Copyright © 2026 Hwanyong Yoo

이 프로젝트는 [MIT 라이선스](LICENSE)에 따라 배포됩니다.
