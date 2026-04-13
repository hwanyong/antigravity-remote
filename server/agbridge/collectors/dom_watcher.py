"""
agbridge.collectors.dom_watcher — DOM event monitoring via MutationObserver

Injects MutationObserver instances into the IDE Renderer to watch
for DOM changes in specific UI sections. When a section changes,
the observer calls the __agb__ binding which triggers a
Runtime.bindingCalled CDP event received by the Engine.

Sections monitored:
  - agent:    #conversation (chat messages, state changes)
  - controls: .antigravity-agent-side-panel (buttons, model/mode)
  - editor:   [role="tablist"] (active editor tab changes)
  - dialog:   body direct children (modals, undo dialogs)

Each section has independent 100ms debouncing to prevent
flooding the CDP channel with rapid successive mutations.
"""

import json
import logging

from agbridge.config import CDP_DEBOUNCE_MS

logger = logging.getLogger("agbridge.dom_watcher")

# Binding function name injected into Renderer global scope
BINDING_NAME = "__agb__"


class DOMWatcher:
    """Manages MutationObserver injection and event parsing."""

    def __init__(self):
        self._installed = False

    @property
    def is_installed(self):
        return self._installed

    async def install(self, bridge):
        """Inject MutationObserver JS into IDE Renderer.

        Creates observers for each UI section with per-section
        debouncing. All observers share the __agb__ binding.

        Args:
            bridge: CDPBridge instance (must be connected).
        """
        # Register the binding first
        await bridge.add_binding(BINDING_NAME)

        # Inject observer JS
        js = _build_observer_js(CDP_DEBOUNCE_MS)
        result = await bridge.execute_js(js)

        if result == "installed":
            self._installed = True
            logger.info("DOMWatcher installed (debounce=%dms)", CDP_DEBOUNCE_MS)
        else:
            logger.warning("DOMWatcher install returned: %s", result)
            self._installed = False

    async def uninstall(self, bridge):
        """Disconnect all observers and remove binding."""
        if not self._installed:
            return

        cleanup_js = """
        (function() {
            if (window.__agb_observers__) {
                for (var key in window.__agb_observers__) {
                    window.__agb_observers__[key].disconnect();
                }
                delete window.__agb_observers__;
            }
            if (window.__agb_timers__) {
                for (var key in window.__agb_timers__) {
                    clearTimeout(window.__agb_timers__[key]);
                }
                delete window.__agb_timers__;
            }
            return 'cleaned';
        })();
        """
        await bridge.execute_js(cleanup_js)
        await bridge.remove_binding(BINDING_NAME)
        self._installed = False
        logger.info("DOMWatcher uninstalled")

    async def reinstall(self, bridge):
        """Re-inject observers after page reload or reconnection."""
        self._installed = False
        await self.install(bridge)

    @staticmethod
    def parse_event(payload_str):
        """Parse binding payload string → dict.

        Args:
            payload_str: JSON string from Runtime.bindingCalled payload.

        Returns:
            dict with at least {section: str} or None on parse failure.
        """
        try:
            data = json.loads(payload_str)
            if "section" not in data:
                return None
            return data
        except (json.JSONDecodeError, TypeError):
            return None


def _build_observer_js(debounce_ms):
    """Build the MutationObserver injection JavaScript.

    Creates 4 independent observers, each with its own debounce timer.
    All call window.__agb__(payload) which triggers Runtime.bindingCalled.

    Args:
        debounce_ms: Debounce delay in milliseconds per section.

    Returns:
        JavaScript code string.
    """
    return f"""
    (function() {{
        // Cleanup previous installation
        if (window.__agb_observers__) {{
            for (var key in window.__agb_observers__) {{
                window.__agb_observers__[key].disconnect();
            }}
        }}
        if (window.__agb_timers__) {{
            for (var key in window.__agb_timers__) {{
                clearTimeout(window.__agb_timers__[key]);
            }}
        }}

        window.__agb_observers__ = {{}};
        window.__agb_timers__ = {{}};

        function createDebouncedObserver(section, target, config) {{
            if (!target) return false;

            var observer = new MutationObserver(function() {{
                if (window.__agb_timers__[section]) return;
                window.__agb_timers__[section] = setTimeout(function() {{
                    window.__agb_timers__[section] = null;
                    try {{
                        window.{BINDING_NAME}(JSON.stringify({{
                            section: section,
                            ts: Date.now()
                        }}));
                    }} catch(e) {{
                        // Binding may be removed during shutdown
                    }}
                }}, {debounce_ms});
            }});

            observer.observe(target, config);
            window.__agb_observers__[section] = observer;
            return true;
        }}

        var results = {{}};

        var panelTarget = document.querySelector('.antigravity-agent-side-panel');

        // 1. Agent panel: conversation messages and state
        // We observe the top-level panel instead of #conversation because
        // Antigravity's React re-renders might unmount #conversation entirely.
        results.agent = createDebouncedObserver('agent', panelTarget, {{
            childList: true,
            subtree: true,
            characterData: true
        }});

        // 2. Controls: buttons, model/mode selectors
        results.controls = createDebouncedObserver('controls', panelTarget, {{
            childList: true,
            subtree: true
        }});

        // 3. Editor tabs: active file changes
        var tabTarget = document.querySelector('[role="tablist"]');
        results.editor = createDebouncedObserver('editor', tabTarget, {{
            childList: true,
            subtree: true,
            attributes: true,
            attributeFilter: ['aria-selected', 'class']
        }});

        // 4. Dialog/modal: undo confirmation, permission dialogs
        //    Watch body direct children only (modals are appended to body)
        results.dialog = createDebouncedObserver('dialog', document.body, {{
            childList: true
        }});

        // 5. Button State Manager (Independent Event-Driven)
        // Watches the cancel button to decouple IDE state from heavy dom tracking
        window.__agb_state__ = 'idle';
        var stateObserver = new MutationObserver(function() {{
            var cancelBtn = document.querySelector('button[aria-label="Cancel generation"], button[aria-label="Cancel"]');
            var newState = (cancelBtn && cancelBtn.offsetParent !== null) ? 'generating' : 'idle';
            if (newState !== window.__agb_state__) {{
                window.__agb_state__ = newState;
                try {{
                    window.{BINDING_NAME}(JSON.stringify({{
                        section: 'state',
                        status: newState,
                        ts: Date.now()
                    }}));
                }} catch(e) {{}}
            }}
        }});
        
        stateObserver.observe(document.body, {{
            childList: true,
            subtree: true,
            attributes: true,
            attributeFilter: ['style', 'class']
        }});
        results.state = true;

        return 'installed';
    }})();
    """
