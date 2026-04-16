import asyncio
import os
import glob
import json
from agbridge.cdp.bridge import CDPBridge

async def main():
    # Find port
    port_files = glob.glob(os.path.expanduser("~") + "/.agbridge/ports/*")
    if not port_files:
        print("No active port")
        return
    with open(port_files[0]) as f:
        port = int(f.read().strip())
        
    bridge = CDPBridge(port=port)
    await bridge.connect()
    res = await bridge.execute_js("""
        (function() {
            var editors = document.querySelectorAll('[data-lexical-editor="true"]');
            var results = [];
            for (var i = 0; i < editors.length; i++) {
                results.push({
                    index: i,
                    text: editors[i].textContent,
                    visible: editors[i].offsetParent !== null,
                    classList: Array.from(editors[i].classList)
                });
            }
            return JSON.stringify(results);
        })()
    """)
    print("Found editors:")
    print(res)
    await bridge.disconnect()

asyncio.run(main())
