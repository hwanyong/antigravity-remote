import asyncio
import json
from agbridge.cdp.bridge import CDPBridge

async def main():
    bridge = CDPBridge(pid=0, workspace_name="Accounting", port=9333)
    await bridge.connect()
    
    # Analyze the structure around the images
    res = await bridge.execute_js("""
        (function() {
            var imgs = document.querySelectorAll('img');
            var results = [];
            imgs.forEach(function(img) {
                var parent = img.parentElement;
                while(parent && !parent.className.includes('attachment') && typeof parent.className === 'string') {
                    if (parent.className.includes('wrapper') || parent.className.includes('container') || parent.className.includes('context')) break;
                    parent = parent.parentElement;
                }
                results.push({
                    srcType: img.src.substring(0, 30),
                    alt: img.alt,
                    className: img.className,
                    parentClass: parent ? parent.className : null
                });
            });
            
            var fileInput = document.querySelector('input[type="file"]');
            var fileInfo = fileInput ? {
                id: fileInput.id,
                className: fileInput.className,
                accept: fileInput.accept,
                multiple: fileInput.multiple
            } : null;
            
            return JSON.stringify({
                images: results,
                fileInput: fileInfo,
            }, null, 2);
        })()
    """)
    print("=== DEEP DOM ANALYSIS ===")
    print(res)
    
    await bridge.disconnect()

asyncio.run(main())
