import asyncio
from agbridge.cdp.bridge import CDPBridge

async def main():
    bridge = CDPBridge()
    await bridge.connect()
    
    res = await bridge.execute_js("""
        (function() {
            var editors = document.querySelectorAll('[data-lexical-editor="true"]');
            var results = [];
            for (var i = 0; i < editors.length; i++) {
                results.push({
                    index: i,
                    text: editors[i].textContent,
                    visible: editors[i].offsetParent !== null
                });
            }
            return JSON.stringify(results);
        })()
    """)
    print(res)
    await bridge.disconnect()

asyncio.run(main())
