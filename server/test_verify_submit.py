import asyncio
import time
from agbridge.cdp.bridge import CDPBridge

async def main():
    bridge = CDPBridge(pid=55216, workspace_name="antigravity-remote", port=9333)
    await bridge.connect()
    
    unique_text = f"@[/analyzer] SYSTEM VERIFICATION TEST {int(time.time())}"
    
    # 1. Inject the text
    import base64
    b64_json = base64.b64encode(f'{{"root":{{"children":[{{"children":[{{"detail":0,"format":0,"mode":"normal","style":"","text":"{unique_text}","type":"text","version":1}}],"direction":"ltr","format":"","indent":0,"type":"paragraph","version":1,"textFormat":0,"textStyle":""}}],"direction":"ltr","format":"","indent":0,"type":"root","version":1}}}}'.encode()).decode()
    
    print(f"Injecting text: {unique_text}")
    
    res1 = await bridge.execute_js(f"""
        (function() {{
            if (!window.__agbridge) return 'No agbridge';
            var result = window.__agbridge.setContent('{b64_json}');
            return 'SetContent result: ' + result;
        }})()
    """)
    print("Step 1:", res1)
    
    # Wait a bit to simulate user behavior
    await asyncio.sleep(0.5)
    
    # 2. Find button, remove disabled, and click
    res2 = await bridge.execute_js("""
        (function() {
            var btn = document.querySelector('button[aria-label="Send message"]');
            if (!btn) btn = document.querySelector('[role="button"][aria-label="Send message"]');
            if (!btn) return 'Button not found';
            
            var wasDisabled = btn.disabled;
            var classes = btn.className;
            
            // First, trigger an InputEvent to gracefully tell React we typed something
            var editor = document.querySelector('[data-lexical-editor="true"]');
            if (editor) {
                editor.dispatchEvent(new InputEvent('input', { bubbles: true, cancelable: true }));
            }
            
            // THE CRITICAL FIX: remove disabled and click
            btn.removeAttribute('disabled');
            btn.click();
            
            return 'Button found. Was disabled: ' + wasDisabled + ', Clicked successfully.';
        })()
    """)
    print("Step 2:", res2)
    
    print("Waiting 1.5 seconds for UI render...")
    await asyncio.sleep(1.5)
    
    res3 = await bridge.execute_js(f"""
        (function() {{
            var allText = document.body.innerText;
            if (allText.indexOf('{unique_text}') !== -1) {{
                var editor = document.querySelector('[data-lexical-editor="true"]');
                var is_empty = false;
                if (editor) {{
                     var content = editor.textContent.trim();
                     if (content === '') is_empty = true;
                }}
                return 'SUCCESS! Text found in chat history. Editor is empty: ' + is_empty;
            }} else {{
                return 'FAILED! Text missing from chat history.';
            }}
        }})()
    """)
    print("Step 3:", res3)
    
    await bridge.disconnect()

asyncio.run(main())
