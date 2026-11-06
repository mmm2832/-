#!/usr/bin/env python3
"""MC 서버 패널 - 폰(Termux)에서 마인크래프트 자바 서버를 앱처럼 관리
실행: python mcpanel.py  → 출력되는 주소를 폰 브라우저로 열기
필요: pkg install python openjdk-21   (구버전 마크는 openjdk-17)
"""
import json, os, secrets, shutil, subprocess, threading, time, zipfile
import urllib.parse, urllib.request
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

ROOT = os.path.expanduser("~/mcpanel")
SRV, BAK, CFG = f"{ROOT}/server", f"{ROOT}/backups", f"{ROOT}/config.json"
for d in (SRV, BAK):
    os.makedirs(d, exist_ok=True)
UA = {"User-Agent": "mcpanel/1.0"}
TOKEN = os.environ.get("MCPANEL_TOKEN") or secrets.token_urlsafe(8)
state = {"proc": None, "log": [], "task": ""}
cfg = {"loader": "paper", "version": "", "ram": "2G", "installed": False}
if os.path.exists(CFG):
    cfg.update(json.load(open(CFG)))

def save_cfg(): json.dump(cfg, open(CFG, "w"))
def log(s): state["log"].append(s.rstrip()); del state["log"][:-500]
def get(url): return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30)
def jget(url): return json.load(get(url))
def running(): p = state["proc"]; return bool(p and p.poll() is None)
def java():
    j = shutil.which("java")
    if not j: raise Exception("Java 없음: pkg install openjdk-21")
    return j
def vkey(v): return [int(x) for x in v.split(".") if x.isdigit()]
def mdir(): return f"{SRV}/{'plugins' if cfg['loader'] == 'paper' else 'mods'}"
def safe(n):
    n = os.path.basename(n or "")
    if not n or n.startswith("."): raise Exception("잘못된 파일 이름")
    return n

def download(url, dest):
    log(f"[패널] 다운로드: {url}")
    with get(url) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)

# ---------- 버전 목록 / 설치 ----------
PAPER = "https://api.papermc.io/v2/projects/paper"
FORGE_PROMO = "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"
NEO = "https://maven.neoforged.net/api/maven/versions/releases/net/neoforged/neoforge"

def versions(l):
    if l == "paper":
        return jget(PAPER)["versions"][::-1]
    if l == "fabric":
        return [v["version"] for v in jget("https://meta.fabricmc.net/v2/versions/game") if v["stable"]]
    if l == "forge":
        promos = jget(FORGE_PROMO)["promos"]
        return sorted({k.rsplit("-", 1)[0] for k in promos}, key=vkey, reverse=True)
    if l == "neoforge":
        out = []
        for v in jget(NEO)["versions"]:
            a, b = (v.split(".") + ["0"])[:2]
            if a.isdigit() and int(a) >= 20:
                mc = "1." + a + ("" if b == "0" else "." + b)
                if mc not in out: out.append(mc)
        return sorted(out, key=vkey, reverse=True)
    raise Exception("지원하지 않는 로더")

def run_installer(jar):
    p = subprocess.Popen([java(), "-jar", jar, "--installServer"], cwd=SRV,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in p.stdout: log(line)
    if p.wait(): raise Exception("인스톨러 실패")

def install(l, v):
    for f in os.listdir(SRV):
        if f in ("server.jar", "run.sh", "run.bat", "user_jvm_args.txt") or f.startswith(("forge-", "neoforge-")):
            os.remove(f"{SRV}/{f}") if os.path.isfile(f"{SRV}/{f}") else None
    if l == "paper":
        b = jget(f"{PAPER}/versions/{v}")["builds"][-1]
        download(f"{PAPER}/versions/{v}/builds/{b}/downloads/paper-{v}-{b}.jar", f"{SRV}/server.jar")
    elif l == "fabric":
        lo = next(x["version"] for x in jget("https://meta.fabricmc.net/v2/versions/loader") if x["stable"])
        ins = next(x["version"] for x in jget("https://meta.fabricmc.net/v2/versions/installer") if x["stable"])
        download(f"https://meta.fabricmc.net/v2/versions/loader/{v}/{lo}/{ins}/server/jar", f"{SRV}/server.jar")
    elif l == "forge":
        promos = jget(FORGE_PROMO)["promos"]
        fv = promos.get(f"{v}-recommended") or promos[f"{v}-latest"]
        full = f"{v}-{fv}"
        download(f"https://maven.minecraftforge.net/net/minecraftforge/forge/{full}/forge-{full}-installer.jar",
                 f"{SRV}/installer.jar")
        run_installer("installer.jar")
    elif l == "neoforge":
        p = v.split(".")
        pre = f"{p[1]}.{p[2] if len(p) > 2 else 0}."
        cands = [x for x in jget(NEO)["versions"] if x.startswith(pre) and "beta" not in x and "alpha" not in x]
        nv = sorted(cands, key=vkey)[-1]
        download(f"https://maven.neoforged.net/releases/net/neoforged/neoforge/{nv}/neoforge-{nv}-installer.jar",
                 f"{SRV}/installer.jar")
        run_installer("installer.jar")
    cfg.update(loader=l, version=v, installed=True); save_cfg()

# ---------- 서버 열기 / 닫기 ----------
def send(c):
    p = state["proc"]
    if not running(): raise Exception("서버가 꺼져 있어요")
    p.stdin.write(c + "\n"); p.stdin.flush()

def start_cmd():
    ram = f"-Xmx{cfg['ram']}"
    if cfg["loader"] in ("paper", "fabric"):
        return [java(), ram, "-jar", "server.jar", "nogui"]
    if os.path.exists(f"{SRV}/run.sh"):
        open(f"{SRV}/user_jvm_args.txt", "w").write(ram + "\n")
        return ["bash", "run.sh", "nogui"]
    jar = next(f for f in os.listdir(SRV) if f.startswith("forge-") and f.endswith(".jar") and "installer" not in f)
    return [java(), ram, "-jar", jar, "nogui"]

def reader(p):
    for line in p.stdout: log(line)
    log(f"[패널] 서버 종료됨 (코드 {p.wait()})")

def start():
    if running(): raise Exception("이미 실행 중")
    if state["task"]: raise Exception("작업 중: " + state["task"])
    if not cfg["installed"]: raise Exception("먼저 '설치' 탭에서 설치하세요")
    open(f"{SRV}/eula.txt", "w").write("eula=true\n")
    p = subprocess.Popen(start_cmd(), cwd=SRV, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True)
    state["proc"] = p
    subprocess.run(["termux-wake-lock"], stderr=subprocess.DEVNULL) if shutil.which("termux-wake-lock") else None
    threading.Thread(target=reader, args=(p,), daemon=True).start()

def stop():
    send("stop")
    p = state["proc"]
    threading.Timer(90, lambda: p.poll() is None and p.kill()).start()

# ---------- 백업 ----------
def backup(prefix=""):
    live = running()
    if live: send("save-off"); send("save-all flush"); time.sleep(5)
    try:
        name = prefix + time.strftime("%Y%m%d-%H%M%S") + ".zip"
        with zipfile.ZipFile(f"{BAK}/{name}", "w", zipfile.ZIP_DEFLATED) as z:
            for r, _, fs in os.walk(SRV):
                for f in fs:
                    if f != "session.lock":
                        pth = os.path.join(r, f)
                        try: z.write(pth, os.path.relpath(pth, SRV))
                        except OSError: pass
        log(f"[패널] 백업 생성: {name}")
    finally:
        if live and running(): send("save-on")

def restore(name):
    if running(): raise Exception("서버를 먼저 닫으세요")
    src = f"{BAK}/{safe(name)}"
    backup("pre-restore-")
    for f in os.listdir(SRV):
        pth = f"{SRV}/{f}"
        shutil.rmtree(pth) if os.path.isdir(pth) else os.remove(pth)
    with zipfile.ZipFile(src) as z: z.extractall(SRV)

def task(name, fn, *a):
    if state["task"]: raise Exception("작업 중: " + state["task"])
    state["task"] = name
    def w():
        try: fn(*a); log(f"[패널] {name} 완료")
        except Exception as e: log(f"[패널] {name} 실패: {e}")
        finally: state["task"] = ""
    threading.Thread(target=w, daemon=True).start()

# ---------- 플러그인 / 모드 ----------
def files():
    os.makedirs(mdir(), exist_ok=True)
    return [{"name": f, "off": f.endswith(".disabled")} for f in sorted(os.listdir(mdir()))]

def file_act(act, name):
    pth = f"{mdir()}/{safe(name)}"
    if act == "delete": os.remove(pth)
    elif act == "toggle":
        os.rename(pth, pth[:-9] if pth.endswith(".disabled") else pth + ".disabled")

def baks():
    return sorted(({"name": f, "mb": round(os.path.getsize(f"{BAK}/{f}") / 1e6, 1)} for f in os.listdir(BAK)),
                  key=lambda x: x["name"], reverse=True)

# ---------- HTTP ----------
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def out(self, code, body, ct="application/json"):
        b = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code); self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def handle_any(self):
        u = urllib.parse.urlparse(self.path); q = dict(urllib.parse.parse_qsl(u.query))
        if u.path == "/":
            if q.get("t") != TOKEN: return self.out(403, b"token required", "text/plain")
            return self.out(200, HTML.replace("__T__", TOKEN).encode(), "text/html; charset=utf-8")
        if self.headers.get("X-T") != TOKEN or not u.path.startswith("/api/"):
            return self.out(403, {"error": "forbidden"})
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try: self.out(200, self.api(u.path[5:], q, raw))
        except Exception as e: self.out(400, {"error": str(e)})
    do_GET = do_POST = handle_any
    def api(self, p, q, raw):
        d = {} if p == "upload" or not raw else json.loads(raw)
        if p == "status":
            return {"running": running(), "task": state["task"], "loader": cfg["loader"], "version": cfg["version"],
                    "ram": cfg["ram"], "installed": cfg["installed"], "log": state["log"][-200:],
                    "dir": "plugins" if cfg["loader"] == "paper" else "mods", "files": files(), "backups": baks()}
        if p == "versions": return {"versions": versions(q["loader"])}
        if p == "install":
            if running(): raise Exception("서버를 먼저 닫으세요")
            cfg["ram"] = d.get("ram") or "2G"; save_cfg()
            task(f"{d['loader']} {d['version']} 설치", install, d["loader"], d["version"])
        elif p == "start": start()
        elif p == "stop": stop()
        elif p == "cmd": send(d["cmd"])
        elif p == "upload":
            os.makedirs(mdir(), exist_ok=True)
            open(f"{mdir()}/{safe(q.get('name'))}", "wb").write(raw)
        elif p == "addurl":
            n = safe(urllib.parse.unquote(d["url"].split("?")[0].rsplit("/", 1)[-1]))
            os.makedirs(mdir(), exist_ok=True); download(d["url"], f"{mdir()}/{n}")
        elif p == "file": file_act(d["act"], d["name"])
        elif p == "backup": task("백업", backup)
        elif p == "restore": task("백업 복원", restore, d["name"])
        elif p == "delbackup": os.remove(f"{BAK}/{safe(d['name'])}")
        else: raise Exception("알 수 없는 요청")
        return {"ok": True}

HTML = r"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>MC 서버 패널</title>
<style>
:root{color-scheme:light dark;font-family:sans-serif}
body{margin:auto;padding:12px;max-width:640px}
nav{display:flex;gap:6px;margin-bottom:12px}nav button{flex:1}
button,select,input{font-size:16px;padding:8px;margin:2px 0}
.row{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.item{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #8884;padding:6px 0;word-break:break-all;gap:6px}
pre{background:#111;color:#ddd;padding:8px;height:280px;overflow:auto;font-size:12px;white-space:pre-wrap}
.tab{display:none}.tab.on{display:block}#cmd{flex:1}
</style>
<h3 id=st>…</h3>
<nav><button onclick="tab('srv')">서버</button><button onclick="tab('ins')">설치</button><button onclick="tab('fil')">플러그인/모드</button><button onclick="tab('bak')">백업</button></nav>
<div id=srv class="tab on">
 <div class=row><button onclick="go('start')">▶ 서버 열기</button><button onclick="go('stop')">■ 서버 닫기</button></div>
 <pre id=log></pre>
 <div class=row><input id=cmd placeholder="명령어 (예: op 닉네임)"><button onclick="sc()">전송</button></div>
</div>
<div id=ins class=tab>
 <div>서버 종류</div><select id=ld onchange="lv()"><option value=paper>Paper</option><option value=fabric>Fabric</option><option value=forge>Forge</option><option value=neoforge>NeoForge</option></select>
 <div>마인크래프트 버전</div><select id=ver></select>
 <div>램 (예: 2G, 3G)</div><input id=ram value=2G size=5><br>
 <button onclick="inst()">설치</button> <small>월드는 유지돼요. 로더를 바꾸면 플러그인/모드 폴더가 달라져요.</small>
</div>
<div id=fil class=tab>
 <h4>현재 폴더: <span id=dn></span></h4>
 <input type=file id=up multiple onchange="upl(event)">
 <div class=row><input id=url placeholder="jar 직접 다운로드 주소" style="flex:1"><button onclick="au()">추가</button></div>
 <div id=fl></div><small>서버를 재시작해야 적용돼요.</small>
</div>
<div id=bak class=tab><button onclick="go('backup')">💾 지금 백업</button><div id=bl></div></div>
<script>
const T="__T__",$=i=>document.getElementById(i);let S={files:[],backups:[],log:[]};
const esc=s=>s.replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
async function api(p,b,raw){const o={headers:{"X-T":T}};if(b!==undefined){o.method="POST";o.body=raw?b:JSON.stringify(b)}
 const r=await fetch("/api/"+p,o),j=await r.json();if(j.error)alert(j.error);return j}
function tab(n){document.querySelectorAll(".tab").forEach(e=>e.classList.toggle("on",e.id==n));if(n=="ins"&&!$("ver").value)lv()}
async function go(p){await api(p,{});poll()}
async function sc(){const c=$("cmd").value;if(c){await api("cmd",{cmd:c});$("cmd").value=""}}
async function lv(){$("ver").innerHTML="<option>불러오는 중…";const r=await api("versions?loader="+$("ld").value);
 $("ver").innerHTML=(r.versions||[]).map(v=>`<option>${v}</option>`).join("")}
async function inst(){if(!$("ver").value||!confirm($("ld").value+" "+$("ver").value+" 설치할까요?"))return;
 await api("install",{loader:$("ld").value,version:$("ver").value,ram:$("ram").value});tab("srv");poll()}
async function upl(e){for(const f of e.target.files)await api("upload?name="+encodeURIComponent(f.name),f,true);e.target.value="";poll()}
async function au(){if($("url").value){await api("addurl",{url:$("url").value});$("url").value="";poll()}}
async function fa(act,i){if(act=="delete"&&!confirm("삭제할까요?"))return;await api("file",{act,name:S.files[i].name});poll()}
async function ba(act,i){const n=S.backups[i].name;
 if(act=="restore"&&!confirm(n+" 로 복원할까요? 현재 상태는 자동 백업돼요."))return;
 if(act=="delbackup"&&!confirm("삭제할까요?"))return;await api(act,{name:n});poll()}
function render(){
 $("st").textContent=(S.running?"🟢 열림":"🔴 닫힘")+" · "+S.loader+" "+S.version+(S.task?" · ⏳ "+S.task:"");
 const l=$("log"),bot=l.scrollTop+l.clientHeight>=l.scrollHeight-30;l.textContent=S.log.join("\n");if(bot)l.scrollTop=l.scrollHeight;
 $("dn").textContent=S.dir+"/";
 $("fl").innerHTML=S.files.map((f,i)=>`<div class=item><span>${esc(f.name)}${f.off?" (꺼짐)":""}</span><span><button onclick="fa('toggle',${i})">${f.off?"켜기":"끄기"}</button><button onclick="fa('delete',${i})">삭제</button></span></div>`).join("")||"<p>비어 있음</p>";
 $("bl").innerHTML=S.backups.map((b,i)=>`<div class=item><span>${esc(b.name)} (${b.mb}MB)</span><span><button onclick="ba('restore',${i})">복원</button><button onclick="ba('delbackup',${i})">삭제</button></span></div>`).join("")||"<p>백업 없음</p>"}
async function poll(){try{S=await fetch("/api/status",{headers:{"X-T":T}}).then(r=>r.json());render()}catch(e){}}
poll();setInterval(poll,2000);
</script>"""

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"\n폰 브라우저에서 열기 → http://127.0.0.1:{port}/?t={TOKEN}\n(이 주소는 실행할 때마다 바뀌고, 폰 안에서만 접속돼요)\n")
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
