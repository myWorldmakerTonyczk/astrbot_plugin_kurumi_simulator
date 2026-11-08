"""Edge smoke check for instance-only toolbar visibility and access card layout."""
import http.server
import logging
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import types

ROOT = Path(__file__).resolve().parents[1]
for name in ("astrbot", "astrbot.api"):
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)
sys.modules["astrbot.api"].logger = logging.getLogger("astrbot")
sys.path.insert(0, str(ROOT))
source = (ROOT / "tests/smoke_view.py").read_text(encoding="utf-8")
source = source.split("with sync_playwright() as p:", 1)[0].replace("from playwright.sync_api import sync_playwright", "")
fixture = {"__file__":str(ROOT / "tests/smoke_view.py")}
exec(compile(source, "smoke-fixture", "exec"), fixture)
checks = r"""
const wait=()=>new Promise(resolve=>setTimeout(resolve,180));
const visible=el=>getComputedStyle(el).display!=='none'&&el.getBoundingClientRect().height>0;
const assert=(ok,message)=>{if(!ok)throw Error(message)};
(async()=>{try{
 await wait(); await wait();
 document.querySelector('.instance-card').click();await wait();await wait();
 const context=document.getElementById('instance-context'),access=document.getElementById('portal-access');
 assert(visible(context),'Instance toolbar missing');
 access.open=true;await wait();
 const text=document.getElementById('portal-umos').getBoundingClientRect();
 const card=access.getBoundingClientRect();
 const settings=document.getElementById('open-instance-settings').getBoundingClientRect();
 assert(card.top>=settings.bottom,'Expanded permissions overlap toolbar');
 assert(text.width>Math.min(450,card.width*.7),'Textarea too narrow');
 assert(text.left>=card.left&&text.right<=card.right,'Textarea overflow');
 assert(document.documentElement.scrollWidth<=innerWidth+1,'Horizontal page overflow');
 document.getElementById('workspace-settings').click();await wait();
 assert(!visible(context),'Instance toolbar leaked into global settings');
 document.getElementById('refresh').click();await wait();await wait();
 assert(!visible(context),'Refresh restored instance toolbar in settings');
 document.getElementById('workspace-instances').click();await wait();
 assert(visible(context)&&!access.open,'Returning to instance did not restore collapsed toolbar');
 document.getElementById('back-to-catalog').click();await wait();
 assert(!visible(context),'Instance toolbar leaked into catalog');
 document.body.dataset.qa='instance-controls-passed';
}catch(error){document.body.dataset.qa='failed: '+error.message;}})();
"""
html=(ROOT / "views/dashboard/index.html").read_text(encoding="utf-8")
bootstrap=fixture["js"]+"\nwindow.fixture.portal_instance={owned:true,username:'bot:FriendMessage:123',trade:false,chat_umos:[]};"
html=html.replace("<head>","<head><script>"+bootstrap+"</script>")
html=html.replace("</body>","<script>"+checks+"</script></body>")
class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs): super().__init__(*args,directory=str(ROOT / "views/dashboard"),**kwargs)
    def log_message(self,*args): pass
    def do_GET(self):
        if self.path=="/qa":
            self.send_response(200)
            self.send_header("Content-Type","text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode())
        else: super().do_GET()
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
try:
    for size in ('1440,1000','460,900'):
        with tempfile.TemporaryDirectory(prefix='kurumi-instance-ui-') as profile:
            run=subprocess.run([r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe','--headless','--disable-gpu','--no-first-run','--user-data-dir='+profile,'--window-size='+size,'--virtual-time-budget=6500','--dump-dom',f'http://127.0.0.1:{server.server_port}/qa'],capture_output=True,timeout=25)
            assert b'data-qa="instance-controls-passed"' in run.stdout,run.stdout[-2000:]
            print('Instance controls browser check passed: '+size)
finally:
    server.shutdown()
    fixture['engine'].db.close()
