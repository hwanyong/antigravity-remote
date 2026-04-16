import asyncio
from agbridge.cdp.bridge import CDPBridge

async def main():
    bridge = CDPBridge(pid=55216, workspace_name="Accounting", port=9333)
    await bridge.connect()
    
    res = await bridge.execute_js("""
        (function() {
            var editors = Array.from(document.querySelectorAll('[data-lexical-editor="true"]'));
            return JSON.stringify(editors.map(ed => ed.textContent.trim()), null, 2);
        })()
    """)
    print("ALL EDITORS TEXT:")
    print(res)
    await bridge.disconnect()

asyncio.run(main())
