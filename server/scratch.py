import asyncio
from agbridge.cdp.bridge import CDPBridge

async def main():
    bridge = CDPBridge(port=9333, workspace_name="Accounting")
    await bridge.connect()
    
    res = await bridge.execute_js("""
        (function() {
            var fileInputs = Array.from(document.querySelectorAll('input[type="file"]'));
            return JSON.stringify(fileInputs.map(fi => ({
                id: fi.id,
                className: fi.className,
                accept: fi.accept,
                multiple: fi.multiple,
                inAgentPanel: !!fi.closest('#conversation, .agent-panel, .antigravity-panel, .sidebar')
            })), null, 2);
        })()
    """)
    print("File Inputs:", res)
    await bridge.disconnect()

asyncio.run(main())
