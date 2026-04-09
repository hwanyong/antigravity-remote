---
name: agbridge-tui-architecture
description: agbridge TUI 클라이언트의 UI 아키텍처, 레이어 시스템, CSS 규칙. TUI 관련 코드 작성 시 반드시 참조.
---

# agbridge TUI Architecture Specification

## 1. Layout — Mobile-Only, Single Panel

전체 레이아웃은 **단일 컬럼, 단일 패널** 방식을 사용한다. 그리드 레이아웃은 사용하지 않는다.

### Main Screen 구조

```
┌──────────────────────────────────┐
│ Header                           │  ← Textual Header, dock: top
├──────────────────────────────────┤
│                                  │
│   Active Panel (전체 화면)        │  ← 한 번에 1개 패널만 표시
│   - WorkspaceList                │     나머지는 display: none
│   - AgentPanel                   │
│   - Explorer                     │
│                                  │
├──────────────────────────────────┤
│ [📋 WS] [🤖 Agent] [📁 Files]   │  ← NavBar, dock: bottom
├──────────────────────────────────┤
│ Footer (F1~F10)                  │  ← Textual Footer, dock: bottom
└──────────────────────────────────┘
```

### 패널 전환 규칙

- `active_panel` reactive 속성으로 현재 활성 패널을 관리한다.
- `watch_active_panel` 워쳐에서 `display = True/False`로 패널을 전환한다.
- `display = False` 처리된 패널은 DOM에서 제거되지 않으므로 상태가 보존된다.
- NavBar 버튼 또는 키바인딩(`M-1`/`M-2`/`M-3`, ESC 후 숫자키)으로 패널을 전환한다.
- 패널 ID에 `#git-panel`이 추가되어 4개 패널이 존재한다.

### CSS Layout 규칙

```css
/* Main Screen — 그리드 사용 금지, vertical 레이아웃 */
Screen {
    layout: vertical;
}

/* 패널은 기본 숨김, data 속성으로 전환 */
#workspace-list,
#agent-panel,
#explorer-panel,
#git-panel {
    display: none;
    height: 1fr;
}
```

> **주의**: `Screen` 타입 셀렉터는 ModalScreen 포함 모든 Screen 서브클래스에 매칭된다.
> 따라서 `Screen`에는 `layout: vertical` 이외의 레이아웃(grid 등)을 적용하면
> 안 된다. 모든 모달에도 동일하게 적용되기 때문이다.

---

## 2. Layer System — 4-Tier Screen Stack

Textual의 `push_screen()` 스택을 활용하여 4단계 레이어를 구성한다.

```
Z-Order (높을수록 상위):

Layer 3: SYSTEM ALERT  ← push_screen(), 전체 불투명, ESC 불가
Layer 2: ALERT          ← push_screen(), 반투명 배경, ESC 닫기
Layer 1: MODAL          ← push_screen(), 전체 화면, ESC 닫기
Layer 0: MAIN SCREEN    ← App 기본 Screen
```

### Layer 0: MAIN SCREEN

- App의 기본 Screen에서 렌더링.
- 패널 3개(WorkspaceList, AgentPanel, Explorer) + NavBar + Header + Footer.
- `layout: vertical`, 그리드 사용하지 않음.

### Layer 1: MODAL (기능 모달)

| 위젯 | 용도 | 스타일 |
|---|---|---|
| `InputModal` | 사용자 입력 | 전체 화면 |
| `TextViewerModal` | 텍스트 뷰어 | 전체 화면 |
| `FileExplorerModal` | 파일 탐색 | 전체 화면 |
| `EventLogModal` | 이벤트 로그 | 전체 화면 |
| `SettingsPanel` | 설정/진단 | 전체 화면 |
| `MenuScreen` | F키 메뉴 | 하단 드롭다운 (유일한 예외) |

**규칙**:
- 모든 Layer 1 모달은 `width: 100%; height: 100%` 고정.
- `MenuScreen`만 예외로 하단 정렬 드롭다운 유지.
- `_apply_responsive` 반응형 로직은 사용하지 않는다 (모바일 전용이므로).
- `-fullscreen` CSS 클래스 토글 패턴은 제거한다.

**CSS 패턴**:
```css
/* Layer 1 모달 — 전체 화면 고정 */
InputModal,
TextViewerModal,
FileExplorerModal,
EventLogModal,
SettingsPanel {
    layout: vertical;
    align: left top;
    background: $surface;
}

/* 내부 컨테이너도 전체 화면 */
InputModal #dialog,
TextViewerModal #dialog,
FileExplorerModal #dialog {
    width: 100%;
    height: 100%;
    border: none;
    padding: 0 1;
}
```

### Layer 2: ALERT (확인/알림)

| 위젯 | 용도 | 스타일 |
|---|---|---|
| `ConfirmModal` | 위험 작업 확인 | 반투명 배경 + 중앙 다이얼로그 |

**규칙**:
- 반투명 배경(`background: $background 60%`)으로 하위 레이어를 어두르게.
- 다이얼로그 박스를 화면 중앙에 렌더링.
- ESC 또는 Cancel로 닫기 가능.
- Layer 1 모달 위에 push 가능(예: FileExplorer → Delete 확인).

**CSS 패턴**:
```css
ConfirmModal {
    layout: vertical;
    align: center middle;
    background: $background 60%;
}

ConfirmModal #dialog {
    width: 90%;
    max-width: 50;
    max-height: 14;
    background: $surface;
    border: thick $error;
    padding: 1 2;
}
```

### Layer 3: SYSTEM ALERT (시스템 알림)

| 위젯 | 트리거 | 행동 |
|---|---|---|
| `SystemAlertScreen` | 권한 오류, 연결 끊김, 치명적 예외 | 전체 화면 블로킹 |

**규칙**:
- 전체 화면 불투명 (`background: $error` 또는 `$warning`).
- ESC로 닫을 수 없음.
- `dismiss` 조건부: 권한 부여 완료, 재연결 성공, 확인 버튼.
- 가장 높은 우선순위: 다른 모든 모달 위에 렌더링.

**CSS 패턴**:
```css
SystemAlertScreen {
    layout: vertical;
    align: center middle;
    background: $error;
}
```

---

## 3. CSS 규칙 — Textual 특화

### 3.1 Screen 셀렉터 주의사항

Textual에서 `Screen {}` 타입 셀렉터는 **모든 Screen 서브클래스**에 매칭된다:
- 기본 Screen
- ModalScreen 서브클래스
- 커스텀 Screen 서브클래스

따라서 `Screen`에 `layout: grid`를 적용하면 모든 모달에도 grid가 적용된다.

**금지**: `Screen { layout: grid; }`
**허용**: `Screen { layout: vertical; }`

### 3.2 CSS 우선순위 (Textual)

1. `DEFAULT_CSS` — 가장 낮음
2. `CSS_PATH` (App 레벨 .tcss 파일) — 중간
3. `CSS` (위젯 클래스 변수) — 가장 높음

### 3.3 상태 관리 (user_rules 준수)

Textual은 HTML `data-*` 속성을 지원하지 않지만, user_rules의 정신을 따라:
- **CSS 클래스 토글 금지**: `add_class()` / `remove_class()`로 UI 상태를 관리하지 않는다.
- **대안**: Textual `reactive` 속성 + `watch_` 메서드로 `display` 속성을 직접 제어한다.
- **예외**: Textual의 `-fullscreen` 같은 레이아웃 모드 전환은 더 이상 사용하지 않는다
  (mobile-only이므로 항상 fullscreen).

### 3.4 모달 인라인 CSS (CSS 클래스 변수)

모든 모달은 `CSS` 또는 `DEFAULT_CSS` 클래스 변수에 자체 스타일을 정의한다.
이는 `CSS_PATH`보다 높은 우선순위를 가지므로, `Screen { layout: vertical; }`이
global로 적용되더라도 모달 자체 CSS로 오버라이드된다.

### 3.5 패널 디자인 컨벤션 (border_title 패턴)

Layer 0의 모든 메인 패널은 동일한 디자인 컨벤션을 따른다:

**Python — 생성자에서 `border_title` 설정**:
```python
class MyPanel(Static):  # or Vertical
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.border_title = "Panel Name"  # ← 프레임 상단에 인라인 렌더링
```

**CSS — border + border-title 스타일**:
```css
#my-panel {
    border: solid $primary;         /* 또는 $secondary */
    border-title-color: $text;
    border-title-style: bold;
    padding: 0;
}
```

**금지 사항**:
- ❌ 내부 `Label`/`Static` 요소로 타이틀을 표시하는 것 (예: `yield Label("Title", id="header")`)
- ❌ 별도의 `#panel-header` Horizontal 영역을 만드는 것
- ❌ `border-title` 없이 패널을 구성하는 것

**현재 적용된 패널**:
| 패널 ID | border_title | border color |
|---|---|---|
| `#workspace-list` | `"Workspaces"` | `$primary` |
| `#agent-panel` | `"Agent"` | `$secondary` |
| `#explorer-panel` | `"Explorer"` | `$primary` |
| `#git-panel` | `"Source Control"` | `$primary` |

---

## 4. Agent Panel — AX 구조 및 에러 배너

### 4.1 IDE Agent Panel AX 트리 매핑

Antigravity IDE의 Agent Panel은 Electron AXWebArea 내부의 섹션[1]에 위치한다.
서버(`ax_scraper.py`)가 이 AX 트리를 파싱하여 구조화된 대화 데이터를 생성한다.

```
Agent Panel Section (layout sections[1])
  ├── 대화 메시지 컨테이너 (AXGroup, class=['gap-y-3', 'px-4'])
  │   ├── User 메시지 (class=['sticky'])
  │   └── Agent 메시지 (class=['relative'])
  │       ├── Thinking (class=['pl-3', 'overflow-hidden'])
  │       ├── Content (AXStaticText)
  │       ├── Actions (AXButton T="Explored N files" / "Edited N file")
  │       └── Error inline (AXStaticText V="Error" + error message)
  ├── 에러 배너 (AXGroup, class=['bg-agent-convo-background'])
  │   ├── AXHeading T="Agent terminated due to error"
  │   ├── AXStaticText V="You can prompt the model..."
  │   ├── AXLink D="troubleshooting guide"
  │   └── AXGroup (flex, justify-between)
  │       ├── AXButton T="Dismiss"
  │       ├── AXButton T="Copy debug info"
  │       └── AXButton T="Retry"
  ├── 입력 영역
  │   ├── AXTextArea D="Message input"
  │   └── AXButton D="Send message"
  └── 모델/모드 선택
      ├── AXPopUpButton T="Select model, current: ..."
      └── AXPopUpButton T="Select conversation mode, current: ..."
```

### 4.2 conversation_state 판별 우선순위

1. **error** — `AXHeading T="Agent terminated due to error"` 존재
2. **idle** — `AXButton D="Send message"` 존재
3. **generating** — `AXButton D="Cancel"` 존재
4. **unknown** — 어떤 마커도 없음

> **주의**: error 상태에서도 Send 버튼이 공존한다. 따라서 에러 배너 검사가 Send 버튼 검사보다 먼저 수행되어야 한다.

### 4.3 에러 배너 마커 (config.py 상수)

| 상수 | 값 | 용도 |
|------|------|------|
| `AX_ERROR_HEADING_TEXT` | `"Agent terminated due to error"` | AXHeading title 매칭 |
| `AX_RETRY_BUTTON_TITLE` | `"Retry"` | AXButton title 매칭 |
| `AX_DISMISS_BUTTON_TITLE` | `"Dismiss"` | AXButton title 매칭 |

### 4.4 Rich Markup Escape 규칙

Agent Panel의 `MessageItem`은 서버에서 수집한 외부 텍스트를 Rich 마크업으로 렌더링한다.
**모든 외부 데이터는 `rich.markup.escape()`로 반드시 이스케이프해야 한다.**

```python
from rich.markup import escape as rich_escape

# 올바른 사용
parts.append(f"[bold cyan]You[/]\n{rich_escape(content)}")

# 금지 — 대괄호 포함 텍스트가 MarkupError 유발
parts.append(f"[bold cyan]You[/]\n{content}")
```

이스케이프 대상:
- `msg_content` (사용자/에이전트 메시지 본문)
- `msg_thinking` (Agent thinking 텍스트)
- `act.get("file")`, `act.get("detail")` (액션 상세)
- `msg_files` (수정된 파일 목록)

---

## 5. 파일 구조

```
agbridge_tui/
├── app.py                    # App 클래스, reactive active_panel
├── styles.tcss               # 글로벌 CSS (Screen vertical + 패널 display 규칙)
├── connection.py             # WebSocket 연결
├── workspace_manager.py      # 워크스페이스 관리
├── permissions.py            # macOS 권한 확인
├── modals/
│   ├── __init__.py
│   ├── confirm_modal.py      # Layer 2: ALERT
│   ├── input_modal.py        # Layer 1: MODAL
│   ├── text_viewer.py        # Layer 1: MODAL
│   ├── select_modal.py       # Layer 2: 모델/모드 선택 모달
│   └── file_explorer_modal.py # Layer 1: MODAL
└── panels/
    ├── __init__.py
    ├── workspace_list.py     # Layer 0: 메인 패널
    ├── agent_panel.py        # Layer 0: 메인 패널
    ├── explorer.py           # Layer 0: 메인 패널
    ├── git_panel.py          # Layer 0: 멀티 Worktree Git 패널
    ├── nav_bar.py            # Layer 0: 패널 전환 바
    ├── event_log.py          # Layer 1: 모달
    ├── settings_panel.py     # Layer 1: 모달
    ├── file_menu.py          # Layer 1: 메뉴 (MenuScreen)
    ├── system_alert.py       # Layer 3: 시스템 알림
    ├── status_header.py      # (미사용 — Header 대체)
    └── command_palette.py    # (미사용)
```

---

## 6. 변경 금지 영역

- `connection.py` — 네트워크 로직은 UI 변경의 영향을 받지 않는다.
- `workspace_manager.py` — 비즈니스 로직은 UI 변경의 영향을 받지 않는다.
- `permissions.py` — 권한 확인 로직은 독립적이다.
