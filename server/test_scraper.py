import asyncio
from agbridge.collectors.cdp_client import CDPBridge

async def main():
    bridge = CDPBridge()
    await bridge.connect()
    js = """
    (function() {
        var panel = document.querySelector('.antigravity-agent-side-panel');
        if (!panel) return "NO_PANEL";
        // Find elements that might be artifacts or "Task", "Walkthrough" buttons
        var buttons = panel.querySelectorAll('button');
        var res = [];
        for (var i=0; i<buttons.length; i++) {
            var b = buttons[i];
            if (b.textContent.includes("Implementation Plan") || b.textContent.includes("Task") || b.textContent.includes("Open")) {
                res.push(b.outerHTML);
            }
        }
        var containers = panel.querySelectorAll('.group\\\\/file-summary');
        var res2 = [];
        for(var i=0; i<containers.length; i++) {
            res2.push(containers[i].outerHTML);
        }
        
        // Let's just find anything with 'Implementation Plan'
        var allDivs = panel.querySelectorAll('div');
        var artifactHTML = "";
        for(var i=0; i<allDivs.length; i++) {
             if (allDivs[i].textContent.includes("Implementation Plan") && allDivs[i].outerHTML.length < 2000) {
                 artifactHTML = allDivs[i].outerHTML;
                 break;
             }
        }
        return JSON.stringify({buttons: res, files: res2, artifact: artifactHTML});
    })();
    """
    res = await bridge.execute_js(js)
    print(res)

asyncio.run(main())
