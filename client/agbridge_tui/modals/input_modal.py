"""
InputModal — multi-step input dialog.

Used for commands requiring user input (prompt, path, git message, etc.)
Supports single-field and multi-field configurations.

Layer 1: MODAL — always fullscreen.
"""

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, RadioButton, RadioSet


class InputModal(ModalScreen):
    """Modal dialog for user input."""

    CSS = """
    InputModal {
        layout: vertical;
        align: center middle;
        background: transparent;
    }
    #dialog {
        width: 90%;
        max-width: 60;
        height: auto;
        background: $surface;
        border: tall $primary;
        padding: 1 2;
    }
    InputModal Label {
        margin-bottom: 1;
    }
    InputModal Input {
        margin-bottom: 1;
    }
    InputModal Horizontal {
        align: right middle;
        height: 3;
    }
    InputModal Button {
        margin-left: 1;
    }
    """

    def __init__(
        self,
        title="Input",
        fields=None,
        callback=None,
        **kwargs,
    ):
        """
        Args:
            title: Dialog title
            fields: List of field dicts: [{"name": "path", "label": "Path:", "placeholder": "..."}]
                    Or a field with type="radio": {"name": "type", "label": "Type:", "options": ["directory", "file"]}
            callback: async def callback(values: dict) — called with field values on submit
        """
        super().__init__(**kwargs)
        self._title = title
        self._fields = fields or [{"name": "value", "label": "Value:", "placeholder": ""}]
        self._callback = callback

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(f"[bold]{self._title}[/]")

            for field in self._fields:
                yield Label(field.get("label", ""))
                if field.get("options"):
                    with RadioSet(id=f"radio-{field['name']}"):
                        for i, opt in enumerate(field["options"]):
                            yield RadioButton(opt, value=i == 0)
                else:
                    yield Input(
                        placeholder=field.get("placeholder", ""),
                        id=f"input-{field['name']}",
                    )

            with Horizontal():
                yield Button("Cancel", variant="default", id="cancel")
                yield Button("Submit", variant="primary", id="submit")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "cancel":
            self.dismiss(None)
            return

        if event.button.id == "submit":
            self._submit_values()

    def on_input_submitted(self, event: Input.Submitted):
        """Allow Enter in input to submit."""
        self._submit_values()

    def _submit_values(self):
        """Collect field values and dismiss."""
        values = {}
        for field in self._fields:
            name = field["name"]
            if field.get("options"):
                try:
                    radio_set = self.query_one(f"#radio-{name}", RadioSet)
                    values[name] = field["options"][radio_set.pressed_index]
                except Exception:
                    values[name] = field["options"][0]
            else:
                try:
                    inp = self.query_one(f"#input-{name}", Input)
                    values[name] = inp.value
                except Exception:
                    values[name] = ""
        self.dismiss(values)

    def on_click(self, event):
        """Click outside the dialog → dismiss."""
        try:
            main_content = self.query_one("#dialog")
            if event.screen_offset not in main_content.region:
                self.dismiss(None)
        except Exception:
            pass
