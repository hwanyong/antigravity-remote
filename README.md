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

Inject prompts into AI agents, review and accept/reject code edits, browse the remote file tree, and manage Git workflows — all over a real-time WebSocket connection, with **zero editor extensions** or plugins. The server leverages native **macOS Accessibility (AX) APIs** and **Quartz Window Services** to observe and interact with the IDE at the OS level, avoiding fragile CDP setups entirely.

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
- **Queue and inject prompts** into the IDE's AI agent without switching contexts?
- **Accept or reject AI code edits** from a lightweight terminal dashboard?
- **Observe file system and Git changes** in real time without opening the IDE GUI?

Antigravity Remote Bridge (`agbridge`) solves these problems by providing a **headless bridge** between your terminal and the IDE's internal state — no extensions, no plugins, just robust OS-level integration.

### 🌟 Unmatched Technical Advantages

Unlike other web-centric remote monitoring tools for Antigravity that rely on fragile Chrome DevTools Protocol (CDP) debugging connections or risky DOM-injection scripts, `agbridge` offers unparalleled control, stability, and security:

1. **Zero Editor Extensions (Zero Footprint)**: Operates purely at the OS level using native macOS Accessibility (AX) APIs. There are no VS Code IDE plugins to install, update, or maintain.
2. **Secure by Default via Endpoint Isolation**: Completely avoids exposing or polling internal Chromium CDP debugging ports. Eradicates the massive security vulnerabilities and rate-limits associated with unsecured CDP web sockets.
3. **Immune to DOM Breakage**: Visual interfaces break when the IDE's internal CSS/HTML structure updates. By reading the universal macOS native window hierarchy and accessibility tree, we bypass brittle DOM-scraping completely, ensuring long-term compatibility.
4. **Terminal-First (TUI) Performance**: Designed specifically as a high-speed, keyboard-driven Terminal UI rather than a heavyweight Web/PWA client. Perfectly tuned for power users, SSH telemetry, and developer CI/CD pipelines.

---

## ✨ Key Features

| Feature | Description |
|---|---|
| **📱 TUI-First Dashboard** | A rich, keyboard-driven terminal interface built with [Textual](https://textual.textualize.io/), featuring workspace panels, agent chat, file explorer, and Git controls. |
| **🔌 Multi-Workspace Support** | Automatically discovers and connects to all active Antigravity IDE windows simultaneously, each managed independently. |
| **🤖 AI Agent Remote Control** | Inject prompts, monitor agent state transitions, and accept or reject AI-generated code changes — all from the terminal. |
| **🕵️ Extension-Free macOS Scraping** | Reads IDE state natively via macOS Accessibility (`AX`) and Quartz Window Capture APIs through [PyObjC](https://pyobjc.readthedocs.io/). No editor plugins needed. |
| **⚡ Real-Time WebSocket Streaming** | Push-based delta events for file system changes, Git status updates, and agent state mutations over persistent WebSocket connections. |
| **🔐 Permission Hub** | Built-in split-button UI for managing IDE agent permissions (Allow / Deny / Workspace / Global / Sandbox) directly from the TUI. |
| **📋 Event Log & Diagnostics** | Full action event log, network status diagnostics, and settings panel accessible via `F10`. |

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
│             │ AX API + Quartz            │                  │
│             └──────────┬─────────────────┘                  │
│                        ▼                                    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              agbridge-server (Daemon)                │    │
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
            │     agbridge-tui (Client)   │
            │                             │
            │  ┌───────┐ ┌─────────────┐  │
            │  │Agent  │ │ Workspace   │  │
            │  │Panel  │ │ Manager     │  │
            │  ├───────┤ ├─────────────┤  │
            │  │File   │ │ Git         │  │
            │  │Explorer│ │ Panel      │  │
            │  ├───────┤ ├─────────────┤  │
            │  │Event  │ │ Settings    │  │
            │  │Log    │ │ Panel       │  │
            │  └───────┘ └─────────────┘  │
            └─────────────────────────────┘
```

The system is composed of two independently installable Python packages:

1. **`agbridge-server`** — A background WebSocket daemon that continuously scrapes IDE state using native macOS APIs (Accessibility, Quartz) and streams delta updates to connected clients.
2. **`agbridge-tui`** — A Textual-based terminal dashboard that connects to the server, renders live IDE state, and transmits user commands (prompt injection, permission grants, etc.) back to the IDE.

---

## 🛠️ Tech Stack

### Server (`agbridge-server`)

| Category | Technology | Purpose |
|---|---|---|
| Runtime | Python 3.11+ | Core language |
| Web Framework | FastAPI 0.115+ | REST & WebSocket API layer |
| ASGI Server | Uvicorn 0.34+ | High-performance async server |
| WebSocket | websockets 14.0+ | Persistent bidirectional communication |
| File Watching | watchdog 6.0+ | File system change detection |
| macOS Bridge | PyObjC 11.0+ | Native AX & Quartz API bindings |

### Client (`agbridge-tui`)

| Category | Technology | Purpose |
|---|---|---|
| Runtime | Python 3.11+ | Core language |
| TUI Framework | Textual 1.0+ | Rich terminal user interface |
| WebSocket | websockets 14.0+ | Server connection |
| HTTP Client | httpx 0.28+ | REST API calls |

---

## 📋 Prerequisites

Before running Antigravity Remote Bridge, ensure you have:

- **macOS** (required — the server uses macOS-exclusive Accessibility and Quartz APIs)
- **Python 3.11** or later
- **Antigravity IDE** (at least one instance running)
- **macOS Permissions** (granted on first run):
  - **Accessibility** — System Settings → Privacy & Security → Accessibility
  - **Screen Recording** — System Settings → Privacy & Security → Screen Recording

> **Note**: These permissions must be granted to the Python process (or your terminal emulator) that runs `agbridge-server`. Without them, the daemon cannot observe the IDE's window hierarchy or interact with UI elements.

---

## 🚀 Getting Started

### 1. Launch the Server

```bash
# Navigate to the server folder and set up virtual environment
cd server/
python3 -m venv .venv
source .venv/bin/activate

# Install the package in editable mode
pip install -e .

# Start the Bridge Server
agbridge-server --log-level ERROR
```

The server will automatically discover all running Antigravity IDE instances and begin streaming their state.

### 2. Launch the Client (New Terminal)

```bash
# Navigate to the client folder and set up virtual environment
cd client/
python3 -m venv .venv
source .venv/bin/activate

# Install the package in editable mode
pip install -e .

# Start the TUI Dashboard
agbridge-tui
```

Once connected, you'll see a multi-panel terminal dashboard with live workspace data.

---

## ⌨️ TUI Keybindings

Navigate the entire interface without touching your mouse:

| Key | Action |
|---|---|
| `Ctrl + W` | Switch to Workspaces Panel |
| `Ctrl + A` | Switch to AI Agent Panel |
| `Ctrl + E` | Switch to File Explorer |
| `Ctrl + G` | Switch to Git Control Panel |
| `F1` – `F4` | Open feature-specific dropdown menus |
| `F10` | Settings, diagnostics, and event log |
| `Enter` | Submit prompt / confirm action |
| `Shift + Enter` | Insert newline in prompt input |

---

## 📂 Project Structure

```
antigravity-remote/
├── server/                     # agbridge-server package
│   ├── agbridge/
│   │   ├── main.py             # Server entry point & lifecycle
│   │   ├── api.py              # FastAPI routes & WebSocket handlers
│   │   ├── engine.py           # Core state diffing & event engine
│   │   ├── state_store.py      # In-memory state management
│   │   ├── input_queue.py      # Command queue (prompt injection, AX actions)
│   │   ├── window_discovery.py # macOS window enumeration
│   │   ├── ide_monitor.py      # IDE process lifecycle monitor
│   │   ├── workspace_supervisor.py # Per-workspace orchestration
│   │   ├── ui_locators.json    # Externalized AX UI selectors
│   │   ├── config.py           # Server configuration
│   │   ├── protocol.py         # WebSocket message protocol
│   │   ├── auth.py             # Permission handling
│   │   └── collectors/         # Data collection modules
│   │       ├── ax_scraper.py   # Accessibility tree parser
│   │       ├── ax_polling.py   # AX state change polling
│   │       └── git_tracker.py  # Git status monitor
│   └── pyproject.toml
│
├── client/                     # agbridge-tui package
│   ├── agbridge_tui/
│   │   ├── app.py              # Textual application & layout
│   │   ├── connection.py       # WebSocket client manager
│   │   ├── workspace_manager.py # Multi-workspace state handler
│   │   ├── permissions.py      # Permission UI logic
│   │   ├── styles.tcss         # Textual CSS stylesheet
│   │   ├── panels/             # UI panel components
│   │   │   ├── agent_panel.py  # AI agent chat & prompt input
│   │   │   ├── workspace_list.py # Workspace selector
│   │   │   ├── explorer.py     # File tree browser
│   │   │   ├── git_panel.py    # Git status & operations
│   │   │   ├── event_log.py    # Action event logger
│   │   │   ├── settings_panel.py # Configuration panel
│   │   │   └── ...             # Nav bar, status header, etc.
│   │   └── modals/             # Dialog components
│   └── pyproject.toml
│
├── tests/                      # Test suite
├── LICENSE                     # MIT License
└── README.md
```

---

## 🎯 Use Cases

- **Headless AI Agent Monitoring** — Run the IDE in the background and monitor all agent interactions from a lightweight terminal session.
- **Multi-Workspace Orchestration** — Manage multiple IDE instances from a single dashboard, switching between projects instantly.
- **Remote SSH Workflows** — SSH into a development machine, attach to running IDE instances, and control them remotely via the TUI.
- **CI/CD Integration** — Programmatically inject prompts and monitor agent state through the WebSocket API for automated workflows.
- **Pair Programming** — One person operates the IDE while another monitors and injects prompts from a separate terminal.

---

## 🗺️ Roadmap

- [ ] **Linux Support** — Port the server AX layer to AT-SPI/D-Bus for Linux compatibility
- [ ] **REST API Documentation** — OpenAPI/Swagger auto-generated docs for the server API
- [ ] **Session Persistence** — Resume TUI sessions across restarts
- [ ] **Plugin System** — Extensible collector architecture for custom data sources
- [ ] **Docker Support** — Containerized server deployment for headless macOS environments

---

## ❓ FAQ

<details>
<summary><strong>Does this require installing any VS Code / Antigravity extensions?</strong></summary>

No. The server uses native macOS Accessibility (AX) and Quartz APIs to read and interact with the IDE at the OS level. No extensions or plugins are needed inside the editor.
</details>

<details>
<summary><strong>Does it work on Linux or Windows?</strong></summary>

Not yet. The server relies on macOS-specific APIs (PyObjC, ApplicationServices, Quartz). Linux support via AT-SPI is on the roadmap. Windows support via UI Automation is under consideration.
</details>

<details>
<summary><strong>Can I use this with regular VS Code (not Antigravity)?</strong></summary>

The AX scraper targets UI elements specific to the Antigravity IDE fork. While some features may partially work with standard VS Code, full compatibility is not guaranteed and not officially supported.
</details>

<details>
<summary><strong>Is the WebSocket API documented?</strong></summary>

The protocol is defined in `server/agbridge/protocol.py`. Full OpenAPI documentation is planned for a future release.
</details>

<details>
<summary><strong>How do I grant macOS permissions?</strong></summary>

On first run, macOS will prompt you. If the prompts don't appear, manually add your terminal emulator (e.g., iTerm2, Terminal.app) and/or the Python binary to:
- **System Settings → Privacy & Security → Accessibility**
- **System Settings → Privacy & Security → Screen Recording**

Then restart your terminal and the server.
</details>

---

## 🤝 Contributing

Bug reports and pull requests are welcome! Whether it's a bug fix, a new feature, or documentation improvements — all contributions are appreciated.

1. Fork this repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📄 License

Copyright © 2026 Hwanyong Yoo

This project is distributed under the [MIT License](LICENSE). See the `LICENSE` file for details.
