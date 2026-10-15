"""Real browser checks against the local service and a simulated Foundry host.

Run separately from unittest discovery: python tests/browser_checks.py
Set PLAYWRIGHT_CHROMIUM_EXECUTABLE only to use an existing local Chromium.
"""
import json
import base64
import os
from pathlib import Path
import sys
import tempfile
import threading
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from token_tracker.bridge import BridgeState
from token_tracker.dashboard import dashboard_server

ROOT = Path(__file__).resolve().parents[1]
KEY = "browser-test-token-at-least-16-characters"
HOST = """<!doctype html><html><head><link rel="stylesheet" href="/foundry/styles/panel.css"></head>
<body><h1>Simulated Foundry test host</h1><p>This is not a running Foundry world.</p>
<script type="module" src="/foundry-host.js"></script></body></html>"""
SCRIPT = """
const once=new Map(),hooks=new Map(),values=new Map();
const token={id:'goblin-token',name:'Goblin token',x:0,y:0,width:1,height:1,
  async update(pos){Object.assign(this,pos);window.appliedCount=(window.appliedCount||0)+1;}};
const scene={id:'scene',grid:{type:1,size:100},dimensions:{sceneX:0,sceneY:0,sceneWidth:1200,sceneHeight:800},tokens:new Map([[token.id,token]])};
scene.tokens.map=fn=>[...scene.tokens.values()].map(fn);
window.Hooks={once:(name,fn)=>once.set(name,fn),on:(name,fn)=>hooks.set(name,fn)};
window.CONST={GRID_TYPES:{SQUARE:1}};
window.game={user:{isGM:true},modules:new Map([['game-token-tracking',{}]]),settings:{register:(id,key,data)=>values.set(key,data.default),get:(id,key)=>values.get(key),set:async(id,key,value)=>{values.set(key,value);return value;}}};
window.canvas={ready:true,scene,tokens:{controlled:[{document:token}]}};
window.ui={notifications:{warn:console.warn,info:console.info}};
await import('/foundry/scripts/module.mjs');once.get('init')();once.get('ready')();
window.tracker=game.modules.get('game-token-tracking').api;
"""


def main():
    with tempfile.TemporaryDirectory() as directory:
        server=dashboard_server(BridgeState("scene",12,8),KEY,"http://localhost:30000",0,directory)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base="http://127.0.0.1:"+str(server.server_port)
        try:
            with sync_playwright() as playwright:
                executable=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
                browser=playwright.chromium.launch(**({"executable_path":executable} if executable else {}))
                context=browser.new_context(viewport={"width":1440,"height":1100},reduced_motion="reduce")
                errors=[]
                context.on("page",lambda p:p.on("pageerror",lambda error:errors.append(str(error))))
                page=context.new_page()
                page.goto(base+"/#key="+KEY)
                expect(page.locator("#connection")).to_have_text("Bridge connected")
                assert "key=" not in page.url
                page.get_by_role("button",name="Start simulation",exact=True).click()
                expect(page.locator("#run-state")).to_have_text("Running")
                page.get_by_role("button",name="Column 3, row 2",exact=True).click()
                expect(page.locator("#history")).to_contain_text("Bridge accepted")
                expect(page.locator("#pieces")).to_contain_text("Square 3, 2")
                page.get_by_role("button",name="Pause",exact=True).click()
                expect(page.locator("#run-state")).to_have_text("Paused")
                page.get_by_role("button",name="Column 4, row 2",exact=True).click()
                expect(page.locator("#toast")).to_contain_text("Start simulation")
                page.locator("summary").click()
                page.locator("#inventory").fill("goblin_1\ngoblin_1")
                page.get_by_role("button",name="Save inventory",exact=True).click()
                expect(page.locator("#toast")).to_contain_text("unique")
                page.get_by_role("button",name="Cameras",exact=True).click()
                expect(page.locator("#camera-tools")).to_be_visible()
                page.get_by_role("button",name="Start tracking",exact=True).click()
                expect(page.locator("#toast")).to_contain_text("Open cameras")
                # Calibration interaction uses a synthetic image; real geometry is
                # separately tested by test_calibration.py, not by this UI stub.
                image=page.evaluate("""() => {const c=document.createElement('canvas');c.width=800;c.height=600;const x=c.getContext('2d');x.fillStyle='#142b21';x.fillRect(0,0,800,600);x.strokeStyle='#b8efcf';x.strokeRect(80,80,640,440);return c.toDataURL('image/png').split(',')[1];}""")
                page.route("**/api/freeze",lambda r:r.fulfill(body=base64.b64decode(image),content_type="image/png"))
                saved=[]
                def calibration_route(route):
                    saved.append(route.request.post_data_json)
                    return route.fulfill(json={"residual_cells":0.003,"image_size":[800,600]})
                page.route("**/api/calibrate",calibration_route)
                page.get_by_role("button",name="Freeze for calibration",exact=True).click()
                expect(page.locator("#calibration-hint")).to_contain_text("Click reference 1")
                canvas=page.locator("#preview")
                box=canvas.bounding_box()
                for x,y in ((80,80),(720,80),(720,520),(80,520)):
                    canvas.click(position={"x":x*box['width']/800,"y":y*box['height']/600})
                page.get_by_role("button",name="Save calibration",exact=True).click()
                expect(page.locator("#calibration-result")).to_contain_text("Saved")
                assert len(saved)==1 and len(saved[0]['image_points'])==4
                assert abs(saved[0]['image_points'][0][0]-80)<3
                page.unroute("**/api/freeze");page.unroute("**/api/calibrate")
                page.get_by_role("button",name="Simulation",exact=True).click()
                page.locator("summary").click()
                page.get_by_role("button",name="Start simulation",exact=True).click()
                page.get_by_role("button",name="Column 3, row 2",exact=True).click()
                page.locator("#pieces button").nth(1).click()
                page.get_by_role("button",name="Column 6, row 4",exact=True).click()
                page.locator("#pieces button").nth(2).click()
                page.get_by_role("button",name="Column 8, row 3",exact=True).click()
                page.get_by_role("button",name="Pause",exact=True).click()
                page.evaluate("document.getElementById('toast').hidden=true")
                output=ROOT/"test-results";output.mkdir(exist_ok=True)
                page.screenshot(path=str(output/"dashboard-desktop.png"),full_page=True)
                page.set_viewport_size({"width":390,"height":844})
                page.screenshot(path=str(output/"dashboard-mobile.png"),full_page=True)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Mobile page overflows: " + str(page.evaluate("[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>innerWidth).map(e=>[e.tagName,e.id,e.className,e.getBoundingClientRect().right]).slice(0,10)"))
                page.set_viewport_size({"width":1440,"height":1100})

                # Load the actual Foundry module and panel against mocked globals,
                # while retaining real HTTP requests to the running bridge.
                def route(request):
                    path=request.request.url.split(base,1)[-1]
                    if path=="/foundry-host.html":return request.fulfill(body=HOST,content_type="text/html")
                    if path=="/foundry-host.js":return request.fulfill(body=SCRIPT,content_type="text/javascript")
                    if path.startswith("/foundry/"):
                        relative=Path(path.removeprefix("/foundry/"))
                        return request.fulfill(body=(ROOT/"foundry/game-token-tracking"/relative).read_text(encoding="utf-8"),content_type="text/css; charset=utf-8" if path.endswith('.css') else "text/javascript; charset=utf-8")
                    return request.continue_()
                context.route(base+"/**",route)
                gm=context.new_page();gm.goto(base+"/foundry-host.html")
                gm.get_by_role("button",name="Token Tracker",exact=True).click()
                gm.get_by_role("button",name="Use viewed scene",exact=True).click()
                gm.locator('input[name="bridgeURL"]').fill(base)
                gm.locator('input[name="bridgeKey"]').fill(KEY)
                gm.get_by_role("button",name="Save connection",exact=True).click()
                gm.get_by_role("button",name="Check bridge",exact=True).click()
                expect(gm.locator(".gtt-feedback")).to_contain_text("Bridge ready")
                gm.get_by_placeholder("goblin_1").fill("goblin_1")
                gm.get_by_role("button",name="Pair with selected token",exact=True).click()
                expect(gm.locator(".gtt-pairings")).to_contain_text("Goblin token")
                gm.get_by_role("button",name="Start sync",exact=True).click()
                expect(gm.locator(".gtt-status")).to_contain_text("SYNCING")
                page.get_by_role("button",name="Start simulation",exact=True).click()
                page.locator("#pieces button").first.click()
                page.get_by_role("button",name="Column 5, row 4",exact=True).click()
                expect(gm.locator(".gtt-history")).to_contain_text("5, 4")
                assert gm.evaluate("canvas.scene.tokens.get('goblin-token').x")==500
                assert gm.evaluate("canvas.scene.tokens.get('goblin-token').y")==400
                gm.locator("summary").click()
                gm.screenshot(path=str(output/"foundry-panel-simulated-host.png"),full_page=True)
                gm.get_by_role("button",name="Stop sync",exact=True).click()
                expect(gm.locator(".gtt-status")).to_contain_text("STOPPED")
                gm.get_by_role("button",name="Remove pairing for goblin_1",exact=True).click()
                expect(gm.locator(".gtt-pairings")).to_contain_text("No pairings")
                gm.get_by_role("button",name="Close panel",exact=True).click()
                expect(gm.locator("dialog")).to_have_count(0)
                gm.get_by_role("button",name="Token Tracker",exact=True).click()
                expect(gm.locator("dialog")).to_have_count(1)
                # Confirm actual disconnected rendering; API failure is deliberate.
                page.route("**/api/status",lambda r:r.abort())
                expect(page.locator("#connection")).to_have_text("Disconnected")
                expect(page.locator("#start")).to_be_disabled()
                page.unroute("**/api/status")
                expect(page.locator("#connection")).to_have_text("Bridge connected")
                assert not errors, errors
                browser.close()
                print("Browser checks passed: desktop/mobile, real HTTP simulation, pairing, applied updates, stop, removal, reconnect.")
                print("Foundry host was simulated; live Foundry compatibility remains unverified.")
        finally:
            server.shutdown();server.runtime.close();server.server_close();thread.join()


if __name__=="__main__":main()
