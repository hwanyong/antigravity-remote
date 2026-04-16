import asyncio
from agbridge.cdp.bridge import CDPBridge

async def main():
    bridge = CDPBridge(pid=0, workspace_name="test", port=18080)
    await bridge.connect()
    res = await bridge.execute_js("""
        var conv = document.getElementById('conversation');
        return conv ? conv.innerHTML : 'No conv';
    """)
    print(res)
    await bridge.disconnect()

asyncio.run(main())
