import asyncio
import os
import glob
from agbridge.cdp.bridge import CDPBridge

async def main():
    port_files = glob.glob(os.path.expanduser("~") + "/.agbridge/ports/*")
    if not port_files:
        print("No active port")
        return
    with open(port_files[0]) as f:
        port = int(f.read().strip())
        
    bridge = CDPBridge(port=port)
    await bridge.connect()
    
    # Try to dynamically locate the correct editor next to the Send button
    res = await bridge.execute_js("""
        (function() {
            var btn = document.querySelector('button[aria-label="Send message"]');
            if (!btn) btn = document.querySelector('[role="button"][aria-label="Send message"]');
            if (!btn) {
                var btns = Array.from(document.querySelectorAll('button, [role="button"]'));
                btn = btns.find(function(b) {
                    var text = (b.textContent || '').trim();
                    return text === 'Submit' || text === 'Send' || b.title === 'Send';
                });
            }
            if (!btn) return "No send button found";
            
            var walker = btn.parentElement;
            var editor = null;
            while (walker) {
                editor = walker.querySelector('[data-lexical-editor="true"]');
                if (editor) break;
                walker = walker.parentElement;
            }
            
            return editor ? "Found editor near send button" : "Could not find editor near send button";
        })()
    """)
    print(res)
    await bridge.disconnect()

asyncio.run(main())
