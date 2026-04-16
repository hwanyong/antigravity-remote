/**
 * agbridge.editor.runtime_bootstrap — Lexical command pre-registration
 *
 * Injected by DOMWatcher on install. Provides deterministic editor
 * control via window.__agbridge API, replacing the deprecated
 * document.execCommand trick.
 *
 * The setContent() function uses setEditorState + editor.update()
 * to guarantee Lexical's registerUpdateListener fires, which in turn
 * triggers React's onChange → Send button activation.
 */
(function() {
    'use strict';

    function getActiveEditor() {
        var btn = document.querySelector('button[aria-label="Send message"]') || document.querySelector('[role="button"][aria-label="Send message"]');
        
        var editor = null;
        if (btn) {
            var walker = btn.parentElement;
            while (walker) {
                editor = walker.querySelector('[data-lexical-editor="true"]');
                if (editor) break;
                walker = walker.parentElement;
            }
        }
        
        if (!editor) {
            var all = Array.from(document.querySelectorAll('[data-lexical-editor="true"]'));
            editor = all.find(e => e.offsetParent !== null) || all[all.length - 1];
        }
        return editor;
    }

    function getCmds(lex) {
        if (lex.__cachedAgbridgeCmds) return lex.__cachedAgbridgeCmds;
        var cmds = {};
        lex._commands.forEach(function(v, k) { cmds[k.type] = k; });
        lex.__cachedAgbridgeCmds = cmds;
        return cmds;
    }

    window.__agbridge = {
        /**
         * Set editor content from a Lexical EditorState JSON string.
         *
         * Uses setEditorState + editor.update() to ensure:
         * 1. Parser constructs proper Lexical nodes
         * 2. update() callback triggers registerUpdateListener
         * 3. React onChange fires -> Send button becomes enabled
         *
         * @param {string} b64StateJSON - Base64-encoded EditorState JSON
         * @returns {boolean|string} true on success, error string on failure
         */
        setContent: function(b64StateJSON) {
            try {
                var editor = getActiveEditor();
                if (!editor || !editor.__lexicalEditor) return 'no editor';
                var lex = editor.__lexicalEditor;
                
                var bin = atob(b64StateJSON);
                var bytes = new Uint8Array(bin.length);
                for (var i = 0; i < bin.length; i++) {
                    bytes[i] = bin.charCodeAt(i);
                }
                var stateJSON = new TextDecoder().decode(bytes);
                var newState = lex.parseEditorState(stateJSON);

                lex.setEditorState(newState);

                // Critical: editor.update() triggers registerUpdateListener
                // callbacks which drive React onChange → Send button activation.
                // Without this, setEditorState alone leaves React state stale.
                lex.update(function() {
                    // Empty callback — the important thing is that update()
                    // triggers the listener pipeline. No node manipulation needed
                    // because setEditorState already set the correct state.
                }, { tag: 'agbridge-inject' });

                editor.focus();
                return true;
            } catch (e) {
                return 'setContent error: ' + e.message;
            }
        },

        /**
         * Clear all editor content.
         *
         * Uses Lexical's SELECT_ALL + DELETE_CHARACTER commands
         * which properly trigger all listeners.
         *
         * @returns {boolean}
         */
        clearContent: function() {
            try {
                var editor = getActiveEditor();
                if (!editor) return false;
                var lex = editor.__lexicalEditor;
                var cmds = getCmds(lex);
                
                editor.focus();
                if (cmds.SELECT_ALL_COMMAND) {
                    lex.dispatchCommand(cmds.SELECT_ALL_COMMAND);
                }
                if (cmds.DELETE_CHARACTER_COMMAND) {
                    lex.dispatchCommand(cmds.DELETE_CHARACTER_COMMAND, true);
                }
                return true;
            } catch (e) {
                return false;
            }
        },

        /**
         * Read current text content from the editor.
         *
         * @returns {string}
         */
        getTextContent: function() {
            var editor = getActiveEditor();
            if (!editor) return '';
            return (editor.textContent || '').trim();
        },

        /**
         * Read the current Lexical EditorState as JSON string.
         *
         * Used to capture mention node structures created by IDE
         * for reverse-engineering Lexical node formats.
         *
         * @returns {string|null} JSON string of EditorState, or null
         */
        getEditorState: function() {
            var editor = getActiveEditor();
            if (!editor || !editor.__lexicalEditor) return null;
            return JSON.stringify(
                editor.__lexicalEditor.getEditorState().toJSON()
            );
        },

        /**
         * Check if the __agbridge API is ready.
         *
         * @returns {boolean}
         */
        isReady: function() {
            var editor = getActiveEditor();
            return !!editor && !!editor.__lexicalEditor;
        },

        /**
         * API version for compatibility checking.
         */
        version: 2
    };
})();
