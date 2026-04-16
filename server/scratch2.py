import asyncio
import json
from agbridge.cdp.bridge import CDPBridge

async def main():
    bridge = CDPBridge(pid=0, workspace_name="Accounting", port=9333)
    await bridge.connect()
    
    # 1. Get Editor State
    editor_state_json = await bridge.execute_js("window.__agbridge.getEditorState()")
    print("=== EDITOR STATE ===")
    if editor_state_json:
        try:
            state = json.loads(editor_state_json)
            # Print without the huge base64 strings to avoid spamming the console
            def truncate_base64(obj):
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if isinstance(v, str) and v.startswith("data:image"):
                            obj[k] = v[:40] + "...(truncated)"
                        else:
                            truncate_base64(v)
                elif isinstance(obj, list):
                    for item in obj:
                        truncate_base64(item)
            truncate_base64(state)
            print(json.dumps(state, indent=2))
        except Exception as e:
            print("Failed to parse Editor State JS JSON:", e)
    else:
        print("Empty or null Editor State")

    # 2. Check for File Inputs or attachment pills
    res = await bridge.execute_js("""
        (function() {
            var fileInputs = document.querySelectorAll('input[type="file"]');
            var imgTags = document.querySelectorAll('img');
            var customNodes = document.querySelectorAll('[data-lexical-decorator="true"]');
            return JSON.stringify({
                fileInputs: fileInputs.length,
                imgTags: imgTags.length,
                decorators: customNodes.length
            });
        })()
    """)
    print("=== DOM ANALYSIS ===")
    print(res)
    
    await bridge.disconnect()

asyncio.run(main())
