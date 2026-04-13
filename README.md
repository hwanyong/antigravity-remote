# Antigravity Remote Bridge 🌉

### Control Your AI-Powered IDE from the Terminal — No Extensions Required

[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg?logo=fastapi)](https://fastapi.tiangolo.com)
[![Textual](https://img.shields.io/badge/Textual-TUI-purple.svg)](https://textual.textualize.io/)
[![macOS Support](https://img.shields.io/badge/macOS-supported-lightgrey.svg?logo=apple)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![WebSocket](https://img.shields.io/badge/protocol-WebSocket-blueviolet.svg)]()

*[한국어로 읽기](README_ko.md)*

**Antigravity Remote Bridge** (`agbridge`) is an advanced headless automation daemon and rich Terminal UI (TUI) client engineered to let you **remotely control, monitor, and automate AI Agents** within the [Antigravity IDE](https://github.com/nicolo-ribaudo/tc39-proposal-bigint) (a VS Code–based, agent-centric development platform) entirely from your terminal. Ideal for developer productivity, AI assistant telemetry, and remote agent orchestration.

Inject prompts into AI agents, review and accept/reject code edits, browse the remote file tree, and manage Git workflows — all over a real-time event-driven WebSocket connection, with **zero editor extensions** or plugins. The server leverages a hybrid architecture combining native **macOS Accessibility (AX) APIs** for strict window isolation and targeted **Chrome DevTools Protocol (CDP)** bindings for deterministic, real-time DOM event dispatching.

---

## 📑 Table of Contents

- [Why Antigravity Remote Bridge?](#-why-antigravity-remote-bridge)
- [Key Features](#-key-features)
- [Architecture Overview](#-architecture-overview)
- [Tech Stack](#-tech-stack)
- [Prerequisites](#-prerequisites)
- [Getting Started](#-getting-started)
- [TUI Keybindings](#%EF%B8%8F-tui-keybindings)
- [Project Structure](#-project-structure)
- [Use Cases](#-use-cases)
- [Roadmap](#-roadmap)
- [FAQ](#-faq)
- [Contributing](#-contributing)
- [License](#-license)

---

## 💡 Why Antigravity Remote Bridge?

Modern AI-powered IDEs like Antigravity run autonomous agents that can plan, write, test, and validate code. But what if you want to:

- **Monitor agent activity** while working in another window or on a different machine?
- **Queue and inject prompts** deterministically into the IDE's AI agent without clipboard-paste hacks?
- **Accept or reject AI code edits** from a lightweight terminal dashboard?
- **Observe file system and Git changes** in real time without opening the IDE GUI?

Antigravity Remote Bridge (`agbridge`) solves these problems by providing a **headless bridge** between your terminal and the IDE's internal state — no extensions, no plugins, just robust OS-level and CDP integration.

### 🌟 Unmatched Technical Advantages

1. **Zero Editor Extensions (Zero Footprint)**: Operates using native macOS Accessibility (AX) APIs and isolated CDP targets. There are no VS Code IDE plugins to install, update, or maintain.
2. **Hybrid AX + CDP Event-Driven Architecture**: Bypasses legacy polling by utilizing `MutationObserver` (DOMWatcher) and `Runtime.addBinding` via CDP. State mutations trigger instant WebSocket push events (ACK/DONE/FAIL lifecycle), ensuring ultra-responsive UI updates (like loading spinners and generation tracking) without sacrificing performance.
3. **Deterministic Lexical Prompt Injection**: Instead of relying on fragile, timing-dependent clipboard pasting, `agbridge` serializes prompt tokens (workflows, mentions) into JSON and injects them programmatically via `editor.parseEditorState()` directly into the IDE's Lexical editor. This guarantees correct UTF-8 encoding and whitespace preservation, and prevents typeahead dropdown failures.
4. **Strict Workspace Isolation**: Enforces exact OS window title matching and isolated CDP targets to ensure prompt injections and command routing operate reliably without cross-workspace interference or race conditions.
5. **Terminal-First (TUI) Resilience**: The Textual-based client features fully decoupled lifecycle management with automatic WebSocket reconnection and diagnostic logging, ensuring it gracefully survives server restarts and network dips. Perfectly tuned for SSH telemetry and CI/CD.

---

## ✨ Key Features

| Feature | Description |
|---|---|
| **📱 TUI-First Dashboard** | Keyboard-driven terminal interface built with Textual, featuring workspace panels, agent chat, Git controls, and a dedicated multi-line `TextArea` for complex prompt input. |
| **📁 File Viewer & Explorer** | Integrated file tree explorer in a dedicated Files panel with overlay support, filtering out binary/media files for seamless remote code inspection. |
| **🔌 Multi-Workspace Support** | Automatically discovers active Antigravity IDE windows simultaneously, isolating each via exact title-matching CDP targets. |
| **🤖 AI Agent Remote Control** | Inject sequence-preserving tokenized prompts, monitor agent state transitions, and accept/reject AI-generated code changes. |
| **🧠 Deterministic Undo/Reset** | Robust undo mechanism that performs "Select All + Delete" via AX simulation after confirmation to reliably clear IDE state. |
| **⚡ Real-Time WebSocket Streaming** | Push-based delta events for file system changes, AI action steps, and UI state mutations over an ACK/DONE/FAIL WebSocket protocol. |
| **📋 Advanced Diagnostics** | Context-aware `DiagnosticRecorder` and `RotatingFileHandler` capture complete UI states and AX-tree snapshots when anomalies occur, accessible via `F10`. |

---

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    macOS Desktop                            │
│                                                             │
│  ┌──────────────────────┐     ┌──────────────────────────┐  │
│  │   Antigravity IDE    │     │   Antigravity IDE        │  │
│  │   (Workspace A)      │     │   (Workspace B)          │  │
│  └──────────┬───────────┘     └──────────┬───────────────┘  │
│             │ AX API + Quartz + CDP      │                  │
│             └──────────┬─────────────────┘                  │
│                        ▼                                    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              agbridge-server (Daemon)                │    │
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
            │     agbridge-tui (Client)   │
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

The system is composed of two independently installable Python packages:

1. **`agbridge-server`** — A background WebSocket daemon that discovers IDE instances via macOS APIs and establishes isolated CDP connections. It acts as an event-driven engine dispatching and reacting to AI state changes asynchronously.
2. **`agbridge-tui`** — A responsive Textual-based terminal dashboard featuring decoupled lifecycle management. It connects to the server, renders multi-line inputs, handles file exploration, and transmits sequence-preserving user commands back to the IDE.

---

## 🛠️ Tech Stack

### Server (`agbridge-server`)

| Category | Technology | Purpose |
|---|---|---|
| Runtime | Python 3.11+ | Core language |
| Web Framework | FastAPI 0.115+ | REST & WebSocket API layer |
| WebSocket | websockets 14.0+ | ACK/DONE/FAIL Event-Driven Protocol |
| Browser Automation | PyChromeDevTools | CDP bindings & `MutationObserver` |
| macOS Bridge | PyObjC 11.0+ | Native AX window discovery & fallback automation |
| Logging | RotatingFileHandler | Advanced diagnostic recording |

### Client (`agbridge-tui`)

| Category | Technology | Purpose |
|---|---|---|
| Runtime | Python 3.11+ | Core language |
| TUI Framework | Textual 1.0+ | Rich, responsive terminal interface (Grid/Flex) |
| Layout & Input | Textual TextArea | Multi-line input editing & Modals |
| Connectivity | Auto-Reconnecting WS | TUI-Server lifecycle decoupling |

---

## 📋 Prerequisites

Before running Antigravity Remote Bridge, ensure you have:

- **macOS** (required — the server uses macOS exclusive APIs for window discovery)
- **Python 3.11** or later
- **Antigravity IDE** (at least one instance running)
- **macOS Permissions** (granted on first run):
  - **Accessibility** — System Settings → Privacy & Security → Accessibility
  - **Screen Recording** — System Settings → Privacy & Security → Screen Recording

---

## 🚀 Getting Started

### 1. Launch the Server

```bash
# Navigate to the server folder and set up virtual environment
cd server/
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Start the Bridge Server
agbridge-server --log-level INFO
```

### 2. Launch the Client (New Terminal)

```bash
# Navigate to the client folder and set up virtual environment
cd client/
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Start the TUI Dashboard
agbridge-tui
```

---

## ⌨️ TUI Keybindings

Navigate the entirely responsive interface without touching your mouse:

| Key | Action |
|---|---|
| `Ctrl + W` | Switch to Workspaces Panel |
| `Ctrl + A` | Switch to AI Agent Chat Panel |
| `Ctrl + E` | Open File Explorer / Viewer |
| `Ctrl + G` | Switch to Git Control Panel |
| `F1` – `F4` | Open feature-specific dropdown menus |
| `F10` | Settings, Deep Diagnostics, and Event Log |
| `Enter` | Submit prompt / confirm action |
| `Shift + Enter` | Insert newline in the TextArea prompt input |

---

## 📂 Project Structure

```
antigravity-remote/
├── server/                     # agbridge-server package
│   ├── agbridge/
│   │   ├── main.py             # Server entry point & lifecycle
│   │   ├── api.py              # FastAPI routes & WebSocket handlers
│   │   ├── engine.py           # Core ACK/DONE/FAIL event engine
│   │   ├── state_store.py      # In-memory state management
│   │   ├── input_queue.py      # Lexical prompt & action queue
│   │   ├── window_discovery.py # macOS AX window enumeration
│   │   ├── ide_monitor.py      # CDP target isolation & lifecycle
│   │   ├── diagnostics.py      # State-dumping & RotatingFileHandler
│   │   └── collectors/         # Data pipeline
│   │       ├── dom_scraper.py  # CDP-based Observation
│   │       ├── ax_scraper.py   # Native AX execution fallback
│   │       └── git_tracker.py  # Git status monitor
│   └── pyproject.toml
│
├── client/                     # agbridge-tui package
│   ├── agbridge_tui/
│   │   ├── app.py              # Textual application & responsive layout
│   │   ├── connection.py       # Auto-reconnecting WS manager
│   │   ├── workspace_manager.py# Multi-workspace state handler
│   │   ├── styles.tcss         # Textual CSS stylesheet (Flex/Grid)
│   │   ├── panels/             # UI panel components
│   │   │   ├── agent_panel.py  # AI agent TextArea & chat
│   │   │   ├── explorer.py     # File tree browser
│   │   │   └── event_log.py    # Action event logger
│   │   └── modals/             # Auto-closing dialogs
│   └── pyproject.toml
│
├── tests/
├── LICENSE
└── README.md
```

---

## 🎯 Use Cases

- **Headless AI Agent Monitoring** — Run the IDE in the background and monitor all event-driven agent interactions from a lightweight terminal session.
- **Precision Prompt Engineering** — Utilize the Textual TextArea for multi-line inputs with exact token preservation.
- **Robust Multi-Workspace Orchestration** — Manage multiple isolated IDE instances from a single dashboard, switching between projects instantly without cross-talk.
- **Remote SSH Workflows** — SSH into a development machine, attach to running IDE instances, and control them remotely via the auto-reconnecting TUI.

---

## 🗺️ Roadmap

- [ ] **Linux Support** — Port the server AX layer to AT-SPI/D-Bus for full Linux compatibility.
- [ ] **OpenAPI Documentation** — Auto-generated Swagger docs for the new Event Engine API.
- [ ] **Session Persistence** — Resume complex TUI sessions and prompts across IDE restarts.

---

## ❓ FAQ

<details>
<summary><strong>Does this require installing any VS Code / Antigravity extensions?</strong></summary>
No. The server uses native macOS Accessibility (AX) APIs and isolated CDP to orchestrate interactions. No extensions or plugins are needed inside the editor.
</details>

<details>
<summary><strong>How is prompt injection so reliable?</strong></summary>
We moved away from legacy accessibility typing and clipboard-pasting. `agbridge` serializes prompts into JSON editor states and injects them natively into Antigravity's Lexical editor, completely bypassing input-timing issues.
</details>

---

## 🤝 Contributing

Bug reports and pull requests are welcome! 

1. Fork this repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📄 License

Copyright © 2026 Hwanyong Yoo

This project is distributed under the [MIT License](LICENSE).
