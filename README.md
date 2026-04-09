# Antigravity Remote Bridge 🌉

[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg?logo=fastapi)](https://fastapi.tiangolo.com)
[![Textual](https://img.shields.io/badge/Textual-TUI-purple.svg)](https://textual.textualize.io/)
[![macOS Support](https://img.shields.io/badge/macOS-supported-lightgrey.svg?logo=apple)]()

*[Read this in Korean](README_ko.md)*

**Antigravity Remote Bridge** is a background daemon and Terminal UI (TUI) client system designed to externally control and monitor instances of the Antigravity IDE (VS Code based).
Interact with AI agents, navigate the file system, and manage Git operations of an IDE running in the background—all without leaving your terminal!

---

## ✨ Features

*   **📱 TUI First**: Sleek, mobile-first `Textual` based terminal UI.
*   **🔌 Multi-Workspace**: Automatically detects and manages multiple active Antigravity IDE windows independently.
*   **🤖 AI Agent Remote Control**: Inject prompts (`CMD_INJECT_PROMPT`), view state changes, and accept or reject AI code edits instantly from the terminal.
*   **🕵️ Native macOS Scraping**: Access IDE elements natively without any editor extensions using macOS `Accessibility (AX)` and `Quartz` Window Capture APIs via PyObjC.
*   **⚡ Real-Time Streaming**: Push-based delta events for Git status and file system changes over WebSockets powered by FastAPI.

## 🏗️ Architecture

The project is structured into two main components:

1.  **`server` (`agbridge-server`)**: A background WebSocket push daemon that aggressively scrapes and streams internal IDE state using native OS-level permissions.
2.  **`client` (`agbridge-tui`)**: The front-end terminal dashboard that connects to the server to display live updates and transmit your command sequences back to the IDE workspace.

## 🚀 Getting Started

### 1. Launching the Server
The daemon (server) is uniquely built for **macOS** and requires specific OS-level security permissions upon initial startup.

```bash
# 1. Navigate to the server folder and set up virtual environment
cd server/
python3 -m venv .venv
source .venv/bin/activate

# 2. Install required packages
pip install -e .

# 3. Start the Bridge Server
agbridge-server --log-level ERROR
```
> **Note**: During the first execution, it is mandatory to manually grant **Accessibility** and **Screen Recording** permissions in the macOS System Settings to the executing Python process so it can properly scan the display and window hierarchy.

### 2. Launching the Client (in a New Terminal)

```bash
# 1. Navigate to the client folder and set up virtual environment
cd client/
python3 -m venv .venv
source .venv/bin/activate

# 2. Install required packages
pip install -e .

# 3. Start the TUI Dashboard
agbridge-tui
```

## ⌨️ Keybindings (TUI)

Navigate through the TUI rapidly with zero mouse interaction by using these bindings:
- `Ctrl + W`: Switch to Workspaces Panel
- `Ctrl + A`: Switch to AI Agent Panel
- `Ctrl + E`: 📁 Switch to File Explorer
- `Ctrl + G`: 🌲 Switch to Git Control Panel
- `F1 ~ F4`: Open Top Dropdown Menus for specific features
- `F10`: ⚙️ Enter Settings, Diagnostics, and the Action Event Log

## 🤝 Contributing

Bug reports and pull requests are welcome! Feel free to push improvements or suggest new features.

1. Fork this repository
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📄 License
This repository is distributed under the MIT License. See `LICENSE` for more information.
