import asyncio
from agbridge.cdp.bridge import CDPBridge

async def main():
    bridge = CDPBridge(pid=0, workspace_name="Accounting", port=9333)
    await bridge.connect()
    
    # 1. Enable DOM domain
    await bridge._send_command("DOM.enable")
    
    # 2. Get document root
    root = await bridge._send_command("DOM.getDocument")
    root_node_id = root["root"]["nodeId"]
    
    # 3. Query the file input
    node = await bridge._send_command("DOM.querySelector", {
        "nodeId": root_node_id,
        "selector": 'input[type="file"].hidden'
    })
    
    if node and "nodeId" in node:
        node_id = node["nodeId"]
        print("Found file input, NodeID:", node_id)
        
        # 4. Set file (create a dummy file first in python)
        import os
        with open("dummy_test.png", "wb") as f:
            f.write(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\n\x9c\xb2T\x00\x00\x00\x00IEND\xaeB`\x82')
        abs_path = os.path.abspath("dummy_test.png")
        
        # 5. Set files
        res = await bridge._send_command("DOM.setFileInputFiles", {
            "files": [abs_path],
            "nodeId": node_id
        })
        print("Set files result:", res)
        
        # Wait a sec
        await asyncio.sleep(1)
        
        # Check images count now (might have increased, or trigger might be needed)
        imgs = await bridge.execute_js("document.querySelectorAll('img').length")
        print("Images count now:", imgs)
    else:
        print("File input not found via DOM.querySelector")
    
    await bridge._send_command("DOM.disable")
    await bridge.disconnect()

asyncio.run(main())
