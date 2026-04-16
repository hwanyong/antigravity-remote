var editor = document.querySelector('[data-lexical-editor="true"]');
if (editor) {
    editor.dispatchEvent(new Event('input', { bubbles: true, cancelable: true }));
    console.log("dispatched");
}
