import asyncio
from agbridge.cdp.bridge import CDPBridge

async def main():
    bridge = CDPBridge(pid=55216, workspace_name="Accounting", port=9333)
    await bridge.connect()
    
    res = await bridge.execute_js("""
        (function() {
            var editors = Array.from(document.querySelectorAll('[data-lexical-editor="true"]'));
            
            var results = editors.map((ed, i) => {
                var buttonsNear = [];
                var walker = ed;
                var limit = 7; // Go up 7 levels
                while (walker && limit > 0) {
                    var siblings = Array.from(walker.querySelectorAll('button, [role="button"], .submit, .send, .generate'));
                    siblings.forEach(b => {
                        if (!buttonsNear.includes(b)) buttonsNear.push(b);
                    });
                    walker = walker.parentElement;
                    limit--;
                }
                
                return {
                    editorIndex: i,
                    editorVisible: ed.offsetParent !== null,
                    text: ed.textContent,
                    buttonsNear: buttonsNear.map(b => ({
                        tag: b.tagName,
                        className: b.className,
                        ariaLabel: b.getAttribute('aria-label'),
                        title: b.title,
                        text: b.textContent.trim(),
                        htmlLength: b.innerHTML.length
                    }))
                };
            });
            return JSON.stringify(results, null, 2);
        })()
    """)
    print("MATCHING EDITORS AND BUTTONS:")
    print(res)
    await bridge.disconnect()

asyncio.run(main())
