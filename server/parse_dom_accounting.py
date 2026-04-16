import asyncio
from agbridge.cdp.bridge import CDPBridge

async def main():
    # Connect to the IDE workspace specifically indicated by the user
    bridge = CDPBridge(pid=55216, workspace_name="Accounting", port=9333)
    await bridge.connect()
    
    # Parse the DOM for the Lexical editors and all surrounding buttons
    res = await bridge.execute_js("""
        (function() {
            var editors = Array.from(document.querySelectorAll('[data-lexical-editor="true"]'));
            var results = editors.map((ed, i) => {
                var buttonsNear = [];
                var walker = ed;
                var limit = 7;
                while (walker && limit > 0) {
                    var siblings = Array.from(walker.querySelectorAll('button, [role="button"]'));
                    siblings.forEach(b => {
                        if (!buttonsNear.includes(b)) buttonsNear.push(b);
                    });
                    walker = walker.parentElement;
                    limit--;
                }
                
                return {
                    editorIndex: i,
                    editorVisible: ed.offsetParent !== null,
                    text: ed.textContent.trim(),
                    buttons: buttonsNear.map(b => ({
                        tag: b.tagName,
                        className: b.className,
                        ariaLabel: b.getAttribute('aria-label') || '',
                        title: b.title || '',
                        disabled: b.disabled || b.getAttribute('aria-disabled') === 'true',
                        outerHTML: b.outerHTML.substring(0, 500) // truncate if too long
                    }))
                };
            });
            return JSON.stringify(results, null, 2);
        })()
    """)
    print(res)
    await bridge.disconnect()

asyncio.run(main())
