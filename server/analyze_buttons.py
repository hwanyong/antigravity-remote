import asyncio
import os
import glob
import json
from agbridge.cdp.bridge import CDPBridge

async def main():
    port_files = glob.glob(os.path.expanduser("~") + "/.agbridge/ports/*")
    if not port_files:
        print("IDE is not connected.")
        return
    with open(port_files[0]) as f:
        port = int(f.read().strip())
        
    bridge = CDPBridge(port=port)
    await bridge.connect()
    
    # Scrape all buttons in the DOM and return their properties
    res = await bridge.execute_js("""
        (function() {
            var btns = Array.from(document.querySelectorAll('button, [role="button"], div[class*="submit"], div[class*="send"]'));
            var results = btns.map(b => ({
                tag: b.tagName,
                className: b.className,
                ariaLabel: b.getAttribute('aria-label') || '',
                title: b.title || '',
                text: (b.textContent || '').trim().substring(0, 20),
                disabled: b.disabled || b.getAttribute('aria-disabled') === 'true'
            })).filter(b => b.ariaLabel.toLowerCase().includes('send') || 
                            b.ariaLabel.toLowerCase().includes('submit') || 
                            b.title.toLowerCase().includes('send') ||
                            b.title.toLowerCase().includes('submit') ||
                            b.className.toLowerCase().includes('submit') ||
                            b.className.toLowerCase().includes('send'));
            return JSON.stringify(results, null, 2);
        })()
    """)
    print("MATCHING BUTTON CANDIDATES:")
    print(res)
    await bridge.disconnect()

asyncio.run(main())
