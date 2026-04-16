import asyncio
from agbridge.cdp.bridge import CDPBridge

async def main():
    bridge = CDPBridge(pid=0, workspace_name="Accounting", port=9333)
    await bridge.connect()
    
    # Click the first delete button inside the attachment list
    res = await bridge.execute_js("""
        (function() {
            var imgs = document.querySelectorAll('img');
            var targetImg = null;
            for (var i=0; i<imgs.length; i++) {
                if (imgs[i].alt && imgs[i].alt.includes('upload')) {
                    targetImg = imgs[i];
                    break;
                }
            }
            if (!targetImg) return "No uploaded image found";
            
            // Find parent container
            var container = targetImg.parentElement;
            
            // Find delete button
            var btn = container.querySelector('button, [role="button"]');
            if (btn) {
                btn.click();
                return "Clicked delete button on image";
            }
            
            // Or maybe the button is a sibling or something
            if (container.parentElement) {
                btn = container.parentElement.querySelector('button');
                if (btn) {
                    btn.click();
                    return "Clicked delete button on parent";
                }
            }
            return "No delete button found";
        })()
    """)
    print(res)
    
    await asyncio.sleep(0.5)
    
    # Now execute paste again!
    b64_png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAAJcEhZcwAADsQAAA7EAZUrDhsAAAANSURBVBhXY3jP4PgfAAWpA6k4D9m0AAAAAElFTkSuQmCC"
    
    res2 = await bridge.execute_js(f"""
        (async function() {{
            var editor = document.querySelector('[data-lexical-editor="true"]');
            if (!editor) return "Editor not found";
            
            var beforeCount = document.querySelectorAll('img').length;
            
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
            
            editor.dispatchEvent(pasteEvent);
            
            await new Promise(r => setTimeout(r, 500));
            var afterCount = document.querySelectorAll('img').length;
            return "Before paste: " + beforeCount + ", After paste: " + afterCount;
        }})()
    """)
    print(res2)
    
    await bridge.disconnect()

asyncio.run(main())
