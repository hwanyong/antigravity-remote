import asyncio
from agbridge.cdp.bridge import CDPBridge

async def main():
    bridge = CDPBridge(pid=0, workspace_name="Accounting", port=9333)
    await bridge.connect()
    
    # 1px png base64
    b64_png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAAJcEhZcwAADsQAAA7EAZUrDhsAAAANSURBVBhXY3jP4PgfAAWpA6k4D9m0AAAAAElFTkSuQmCC"
    
    res = await bridge.execute_js(f"""
        (async function() {{
            var b64 = "{b64_png}";
            var byteString = atob(b64);
            var ab = new ArrayBuffer(byteString.length);
            var ia = new Uint8Array(ab);
            for (var i = 0; i < byteString.length; i++) {{
                ia[i] = byteString.charCodeAt(i);
            }}
            var blob = new Blob([ab], {{type: 'image/png'}});
            var file = new File([blob], "paste_test.png", {{type: 'image/png'}});
            
            var dt = new DataTransfer();
            dt.items.add(file);
            
            var pasteEvent = new ClipboardEvent("paste", {{
                clipboardData: dt,
                bubbles: true,
                cancelable: true
            }});
            
            var editor = document.querySelector('[data-lexical-editor="true"]');
            if (!editor) return "Editor not found";
            
            var beforeCount = document.querySelectorAll('img').length;
            
            editor.dispatchEvent(pasteEvent);
            
            // Wait 500ms
            await new Promise(r => setTimeout(r, 500));
            
            var afterCount = document.querySelectorAll('img').length;
            return "Before: " + beforeCount + ", After: " + afterCount;
        }})()
    """)
    print(res)
    await bridge.disconnect()

asyncio.run(main())
