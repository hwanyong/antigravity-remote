import asyncio
from agbridge.cdp.bridge import CDPBridge

async def main():
    bridge = CDPBridge(pid=55216, workspace_name="Accounting", port=9333)
    await bridge.connect()
    
    res = await bridge.execute_js("""
        (function() {
            var btns = Array.from(document.querySelectorAll('button[aria-label="Send message"], [role="button"][aria-label="Send message"]'));
            return JSON.stringify(btns.map(b => ({
                tag: b.tagName,
                className: b.className,
                ariaLabel: b.getAttribute('aria-label'),
                disabled: b.disabled || b.getAttribute('aria-disabled') === 'true',
                offsetParent: b.offsetParent !== null,
                text: b.textContent.trim(),
                is_hidden: b.style.display === 'none' || b.style.visibility === 'hidden'
            })), null, 2);
        })()
    """)
    print("ALL 'Send message' BUTTONS IN DOM:")
    print(res)
    await bridge.disconnect()

asyncio.run(main())
