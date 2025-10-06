from flask import Flask, request, redirect, render_template_string, flash, send_file
import subprocess, os, re, pathlib, glob, html

APP = Flask(__name__)
APP.secret_key = "fakecam-netui-tabs-stable2"

NET_FILE = "/etc/systemd/network/05-fakecam.network"
IFACE_DEFAULT = "ens4"   # <-- CAMBIA QUI se diverso
HTPASS = "/etc/nginx/.htpasswd"
NGINX_SITE = "/etc/nginx/sites-available/fakecam"
PUBLISHER_SERVICE = "fakecam"

OVERLAY_FILE = "/etc/fakecam/overlay.txt"
SRC_FILE = "/etc/fakecam/source.txt"
PAT_FILE = "/etc/fakecam/pattern.txt"
COLOR_FILE = "/etc/fakecam/color.txt"
TS_ON_FILE = "/etc/fakecam/timestamp.enabled"
TS_FMT_FILE = "/etc/fakecam/timestamp.format"
PRESETS_DIR = "/etc/fakecam/presets.d"

TIMESYNCD_CONF = "/etc/systemd/timesyncd.conf"

def sh(args): return subprocess.run(args, check=False, capture_output=True, text=True)

def write_atomic(path, text):
    tmp = path + ".tmp"
    pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(tmp,"w") as f: f.write(text)
    os.replace(tmp, path)

def current_net(iface):
    cur = {"mode":"dhcp","ip":"","mask":"","gw":"","dns":[],"iface":iface}
    p = sh(["ip","-4","addr","show","dev",iface]).stdout or ""
    m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)/(\d+)", p)
    if m:
        cur["ip"]=m.group(1); bits=int(m.group(2))
        mask_int=(0xffffffff << (32-bits)) & 0xffffffff
        cur["mask"]=".".join(str((mask_int>>s)&255) for s in (24,16,8,0))
    r = sh(["ip","route","show","default","dev",iface]).stdout or ""
    g = re.search(r"default via (\d+\.\d+\.\d+\.\d+)", r)
    if g: cur["gw"]=g.group(1)
    try:
        with open(NET_FILE) as f: cur["mode"]="static" if "Address=" in f.read() else "dhcp"
    except FileNotFoundError: pass
    try:
        with open("/etc/resolv.conf") as f:
            cur["dns"]=[l.split()[1] for l in f if l.startswith("nameserver")]
    except: pass
    return cur

def apply_net(iface):
    sh(["systemctl","enable","--now","systemd-networkd"])
    sh(["networkctl","reload"])
    sh(["networkctl","reconfigure", iface])

def get_nginx_port():
    try:
        with open(NGINX_SITE) as f:
            for line in f:
                m = re.search(r'^\s*listen\s+(\d+)\s+default_server;', line)
                if m: return int(m.group(1))
    except FileNotFoundError: return 80
    return 80

def set_nginx_port(port:int):
    with open(NGINX_SITE) as f: txt=f.read()
    txt = re.sub(r'listen\s+\d+\s+default_server;', 'listen {} default_server;'.format(port), txt)
    write_atomic(NGINX_SITE, txt); sh(["nginx","-t"]); sh(["systemctl","reload","nginx"])

def list_presets():
    pathlib.Path(PRESETS_DIR).mkdir(parents=True, exist_ok=True)
    out=[]
    for p in sorted(glob.glob(os.path.join(PRESETS_DIR,"*.url"))):
        name=os.path.splitext(os.path.basename(p))[0]
        try: src=open(p).read().strip()
        except: src=""
        out.append((name,src))
    return out

BASE = """
<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>FakeCam – NetUI</title>
<style>
:root{color-scheme:dark light}
body{font-family:system-ui,Arial;margin:0;background:#0b0e14;color:#e6e6e6}
.nav{display:flex;gap:.6rem;flex-wrap:wrap;padding:12px;border-bottom:1px solid #222;background:#0f131a}
.nav a{padding:.5rem .7rem;border:1px solid #333;border-radius:10px;color:#e6e6e6;text-decoration:none}
.wrap{max-width:980px;margin:1.2rem auto;padding:0 1rem}
.card{background:#151a22;border:1px solid #222;border-radius:12px;padding:1rem}
input,select,button,textarea{width:100%;padding:.6rem;border-radius:10px;border:1px solid #333;background:#0f131a;color:#e6e6e6}
.row{display:flex;gap:1rem;flex-wrap:wrap}.row>*{flex:1 1 240px}
.ok{color:#9f9}.err{color:#f99}
table{width:100%;border-collapse:collapse;margin-top:.6rem}
td,th{border:1px solid #222;padding:.5rem;vertical-align:top}
.actions form{display:inline-block;margin-right:.4rem}
small{opacity:.8}
</style>
<div class="nav">
  <a href="/netui/">Rete</a>
  <a href="/netui/overlay">Overlay</a>
  <a href="/netui/stream">Streaming</a>
  <a href="/netui/change-password">Password</a>
  <a href="/netui/diagnostics">Diagnostica</a>
  <a href="/netui/http-port">Porta HTTP</a>
  <a href="/netui/time">Orario/NTP</a>
  <a href="/netui/config-pack">Config Pack</a>
  <a href="/">Home</a>
</div>
<div class="wrap">
{% with msgs=get_flashed_messages(with_categories=true) %}{% for c,m in msgs %}<p class="{{'ok' if c=='ok' else 'err'}}">{{m}}</p>{% endfor %}{% endwith %}
<div class="card">{{ body|safe }}</div>
</div>
"""

@APP.route("/", methods=["GET","POST"])
def net_index():
    iface=(request.form.get("iface") or IFACE_DEFAULT).strip() if request.method=="POST" else IFACE_DEFAULT
    if request.method=="POST":
        mode=request.form.get("mode","dhcp")
        if mode=="dhcp":
            content="[Match]\nName=en* eth*\n\n[Network]\nDHCP=yes\n"
        else:
            ip=(request.form.get("ip") or "").strip()
            mask=(request.form.get("mask") or "").strip()
            gw=(request.form.get("gw") or "").strip()
            dns=[d for d in (request.form.get("dns") or "").split() if d]
            if not ip or not mask: flash("IP e Netmask obbligatori.","err"); return redirect("/netui/")
            try:
                parts=[int(x) for x in mask.split(".")]
                if len(parts)!=4 or any(p<0 or p>255 for p in parts): raise ValueError
                bits=sum(bin(p).count("1") for p in parts)
            except: flash("Netmask non valida.","err"); return redirect("/netui/")
            content="[Match]\nName=en* eth*\n\n[Network]\nAddress={}/{}\n".format(ip,bits)
            if gw: content+="Gateway={}\n".format(gw)
            if dns: content+="DNS={}\n".format(" ".join(dns))
        write_atomic(NET_FILE, content); apply_net(iface); flash("Configurazione rete applicata.","ok"); return redirect("/netui/")
    cur=current_net(IFACE_DEFAULT)
    BODY = """
    <h2>Config rete</h2>
    <form method="post">
      <label>Interfaccia</label><input name="iface" value="{iface}">
      <label>Metodo</label>
      <select name="mode" onchange="document.getElementById('static').style.display=this.value==='static'?'block':'none'">
        <option value="dhcp" {sel_dhcp}>DHCP</option>
        <option value="static" {sel_static}>Statico</option>
      </select>
      <div id="static" style="display:{static_disp};margin-top:.6rem">
        <div class="row">
          <div><label>IP</label><input name="ip" value="{ip}"></div>
          <div><label>Netmask</label><input name="mask" value="{mask}"></div>
        </div>
        <div class="row">
          <div><label>Gateway</label><input name="gw" value="{gw}"></div>
          <div><label>DNS (spazio sep.)</label><input name="dns" value="{dns}"></div>
        </div>
      </div>
      <button type="submit" style="margin-top:.8rem">Applica</button>
    </form>
    """.format(
        iface=cur['iface'],
        sel_dhcp=("selected" if cur['mode']=="dhcp" else ""),
        sel_static=("selected" if cur['mode']=="static" else ""),
        static_disp=("block" if cur['mode']=="static" else "none"),
        ip=cur.get('ip',''), mask=cur.get('mask',''), gw=cur.get('gw',''),
        dns=" ".join(cur.get('dns',[]))
    )
    return render_template_string(BASE, body=BODY)

@APP.route("/overlay", methods=["GET","POST"])
def overlay():
    if request.method=="POST":
        label=(request.form.get("label") or "").strip()
        if not label: flash("Inserisci un testo.","err"); return redirect("/netui/overlay")
        write_atomic(OVERLAY_FILE, label+"\n"); sh(["systemctl","restart",PUBLISHER_SERVICE])
        flash("Etichetta aggiornata.","ok"); return redirect("/netui/overlay")
    try: label=open(OVERLAY_FILE).read().strip()
    except: label="CAM01"
    BODY = """
    <h2>Overlay video</h2>
    <form method="post">
      <label>Testo (es. CAM01)</label>
      <input name="label" value="{label}">
      <button type="submit" style="margin-top:.8rem">Salva</button>
    </form>
    """.format(label=html.escape(label))
    return render_template_string(BASE, body=BODY)

@APP.route("/stream", methods=["GET","POST"])
def stream():
    action=request.form.get("action","")
    if request.method=="POST":
        if action=="apply":
            src=(request.form.get("source") or "").strip()
            pat=(request.form.get("pattern") or "testsrc").strip()
            col=(request.form.get("color") or "red").strip()
            ts  ="on" if request.form.get("ts")=="on" else "off"
            tf  =(request.form.get("tsfmt") or "%Y-%m-%d %H\\:%M\\:%S").strip()
            write_atomic(SRC_FILE, (src+"\n") if src else "")
            write_atomic(PAT_FILE, pat+"\n")
            write_atomic(COLOR_FILE, col+"\n")
            write_atomic(TS_ON_FILE, ts+"\n")
            write_atomic(TS_FMT_FILE, tf+"\n")
            sh(["systemctl","restart",PUBLISHER_SERVICE])
            flash("Streaming aggiornato.","ok"); return redirect("/netui/stream")

        if action=="use_preset":
            name=request.form.get("preset",""); p=os.path.join(PRESETS_DIR,f"{name}.url")
            if os.path.isfile(p):
                src=open(p).read().strip()
                write_atomic(SRC_FILE, src+"\n")
                sh(["systemctl","restart",PUBLISHER_SERVICE])
                flash("Sorgente impostata dal preset '{}'.".format(name),"ok")
            else:
                flash("Preset non trovato.","err")
            return redirect("/netui/stream")

        if action=="add_preset":
            pname=(request.form.get("pname","").strip() or "preset").lower()
            pname=re.sub(r'[^a-z0-9._-]+','-',pname); pname=re.sub(r'-+','-',pname).strip('-') or "preset"
            purl=(request.form.get("purl") or "").strip()
            if not purl: flash("URL/Path mancante.","err")
            else: write_atomic(os.path.join(PRESETS_DIR,f"{pname}.url"), purl+"\n"); flash("Preset aggiunto.","ok")
            return redirect("/netui/stream")

        if action=="del_preset":
            pname=request.form.get("preset",""); p=os.path.join(PRESETS_DIR,f"{pname}.url")
            if os.path.isfile(p): os.remove(p); flash("Preset eliminato.","ok")
            else: flash("Preset inesistente.","err")
            return redirect("/netui/stream")

    def rd(p,default=""):
        try: return open(p).read().strip()
        except: return default

    src=rd(SRC_FILE,""); pat=rd(PAT_FILE,"testsrc"); col=rd(COLOR_FILE,"red")
    ts = rd(TS_ON_FILE,"on").lower()=="on"
    tf=rd(TS_FMT_FILE,"%Y-%m-%d %H\\:%M\\:%S")
    presets=list_presets()

    options = """
      <option value="testsrc" {s1}>testsrc (griglia)</option>
      <option value="testsrc2" {s2}>testsrc2</option>
      <option value="smptebars" {s3}>smptebars</option>
      <option value="smptehdbars" {s4}>smptehdbars (HD)</option>
      <option value="color" {s5}>color (pieno)</option>
    """.format(
        s1=("selected" if pat=="testsrc" else ""),
        s2=("selected" if pat=="testsrc2" else ""),
        s3=("selected" if pat=="smptebars" else ""),
        s4=("selected" if pat=="smptehdbars" else ""),
        s5=("selected" if pat=="color" else "")
    )

    rows = ""
    for n,s in presets:
        rows += "<tr><td><code>{}</code></td><td><small>{}</small></td><td class='actions'>".format(
            html.escape(n), html.escape(s)
        )
        rows += "<form method='post'><input type='hidden' name='action' value='use_preset'><input type='hidden' name='preset' value='{}'><button>Usa</button></form> ".format(html.escape(n))
        rows += "<form method='post' onsubmit=\"return confirm('Eliminare preset {}?')\"><input type='hidden' name='action' value='del_preset'><input type='hidden' name='preset' value='{}'><button>Elimina</button></form>".format(html.escape(n), html.escape(n))
        rows += "</td></tr>"

    BODY = """
    <h2>Streaming</h2>
    <form method="post">
      <input type="hidden" name="action" value="apply">
      <label>Fonte (vuoto = pattern): file o URL (http/https/rtsp)</label>
      <input name="source" value="{src}">
      <label>Pattern</label>
      <select name="pattern">{options}</select>
      <div style="margin:.4rem 0 .6rem;opacity:.8">Se scegli <code>color</code>, usa il campo Colore (es. <code>red</code> o <code>#00ff88</code>).</div>
      <label>Colore</label>
      <input name="color" value="{col}">
      <hr style="border-color:#222">
      <label><input type="checkbox" name="ts" {chk} onclick="document.getElementById('tsfmt').style.display=this.checked?'block':'none'"> Timestamp in overlay</label>
      <div id="tsfmt" style="display:{disp};margin-top:.6rem">
        <label>Formato timestamp (strftime)</label>
        <input name="tsfmt" value="{tf}">
        <div style="opacity:.75;margin-top:.2rem">Esempi: <code>%Y-%m-%d %H\:%M\:%S</code> · <code>%d/%m/%Y %H\:%M:%S</code></div>
      </div>
      <button type="submit" style="margin-top:1rem">Applica</button>
    </form>

    <h3 style="margin-top:1.2rem">Preset sorgenti</h3>
    <form method="post" style="margin:.4rem 0">
      <input type="hidden" name="action" value="add_preset">
      <div class="row">
        <div><label>Nome preset</label><input name="pname" placeholder="nome-breve"></div>
        <div><label>URL/Path</label><input name="purl" placeholder="https://... oppure /path/file.mp4"></div>
      </div>
      <button type="submit" style="margin-top:.6rem">Aggiungi preset</button>
    </form>

    <table>
      <tr><th>Nome</th><th>Sorgente</th><th>Azione</th></tr>
      {rows}
    </table>
    """.format(
        src=html.escape(src), options=options, col=html.escape(col),
        chk=("checked" if ts else ""), disp=("block" if ts else "none"),
        tf=html.escape(tf), rows=rows
    )
    return render_template_string(BASE, body=BODY)

@APP.route("/change-password", methods=["GET","POST"])
def change_password():
    from subprocess import run, PIPE, STDOUT
    if request.method=="POST":
        u=(request.form.get("user") or "").strip(); op=request.form.get("oldpw") or ""
        n1=request.form.get("new1") or ""; n2=request.form.get("new2") or ""
        if not u or not op or not n1 or not n2: flash("Compila tutti i campi.","err"); return redirect("/netui/change-password")
        if n1!=n2: flash("Le nuove password non coincidono.","err"); return redirect("/netui/change-password")
        if run(["htpasswd","-vb",HTPASS,u,op], stdout=PIPE, stderr=STDOUT, text=True).returncode!=0:
            flash("Credenziali attuali non valide.","err"); return redirect("/netui/change-password")
        if run(["htpasswd","-bB",HTPASS,u,n1], stdout=PIPE, stderr=STDOUT, text=True).returncode!=0:
            flash("Impossibile aggiornare la password.","err"); return redirect("/netui/change-password")
        flash("Password aggiornata.","ok"); return redirect("/netui/change-password")
    BODY = """
    <h2>Cambia password</h2>
    <form method="post">
      <label>Utente</label><input name="user" value="admin">
      <label>Password attuale</label><input type="password" name="oldpw">
      <label>Nuova password</label><input type="password" name="new1">
      <label>Conferma</label><input type="password" name="new2">
      <button type="submit" style="margin-top:.8rem">Aggiorna</button>
    </form>
    """
    return render_template_string(BASE, body=BODY)

@APP.route("/diagnostics")
def diag():
    iface=IFACE_DEFAULT
    ip=sh(["ip","-4","addr","show","dev",iface]).stdout
    rt=sh(["ip","route"]).stdout
    svc=sh(["systemctl","is-active","mediamtx"]).stdout.strip()
    pub=sh(["systemctl","is-active",PUBLISHER_SERVICE]).stdout.strip()
    BODY="<h2>Diagnostica</h2><pre>iface: {}\n\n--- ip -4 addr ---\n{}\n--- route ---\n{}\n--- services ---\nmediamtx: {}\n{}: {}\n</pre>".format(
        iface, ip, rt, svc, PUBLISHER_SERVICE, pub
    )
    return render_template_string(BASE, body=BODY)

@APP.route("/http-port", methods=["GET","POST"])
def http_port():
    cur=get_nginx_port()
    if request.method=="POST":
        try:
            p=int(request.form.get("port","80"))
            if 1<=p<=65535:
                set_nginx_port(p); flash("Porta HTTP aggiornata a {}. Riapri la pagina su :{}.".format(p,p),"ok")
            else: raise ValueError
        except Exception as e: flash("Errore: {}".format(e),"err")
        return redirect("/netui/http-port")
    BODY="""
    <h2>Porta HTTP</h2>
    <form method="post">
      <label>Porta di ascolto Nginx</label>
      <input name="port" value="{cur}">
      <button type="submit" style="margin-top:.8rem">Cambia porta</button>
    </form>
    <p style="opacity:.75;margin-top:.5rem">Dopo il cambio apri <code>http://IP:{cur}</code>.</p>
    """.format(cur=cur)
    return render_template_string(BASE, body=BODY)

@APP.route("/time", methods=["GET","POST"])
def time_tab():
    if request.method=="POST":
        act=request.form.get("action","")
        if act=="save":
            tz=(request.form.get("timezone") or "Europe/Rome").strip()
            ntp=(request.form.get("ntp") or "pool.ntp.org").strip()
            sh(["timedatectl","set-timezone",tz])
            write_atomic(TIMESYNCD_CONF, "[Time]\nNTP={}\nFallbackNTP=pool.ntp.org\n".format(ntp))
            sh(["systemctl","enable","--now","systemd-timesyncd"])
            sh(["timedatectl","set-ntp","true"])
            sh(["systemctl","restart","systemd-timesyncd"])
            flash("Impostazioni orario/NTP salvate.","ok")
        elif act=="syncnow":
            sh(["timedatectl","set-ntp","true"]); sh(["systemctl","restart","systemd-timesyncd"])
            flash("Sync NTP richiesto.","ok")
        return redirect("/netui/time")

    td=sh(["timedatectl"]).stdout
    try: conf=open(TIMESYNCD_CONF).read()
    except: conf="[Time]\nNTP=\nFallbackNTP=pool.ntp.org\n"
    tz_cur=re.search(r"Time zone:\s+([^\s]+)", td or "")
    tz_val=tz_cur.group(1) if tz_cur else "Europe/Rome"
    ntp_match=re.search(r"^NTP=(.*)$", conf, re.M|re.I)
    ntp_val=(ntp_match.group(1).strip() if ntp_match else "pool.ntp.org") or "pool.ntp.org"

    BODY = """
    <h2>Orario / NTP</h2>
    <form method="post">
      <input type="hidden" name="action" value="save">
      <div class="row">
        <div><label>Timezone</label><input name="timezone" value="{tz}"><small>Esempio: Europe/Rome</small></div>
        <div><label>Server NTP</label><input name="ntp" value="{ntp}"><small>Es: 0.it.pool.ntp.org 1.it.pool.ntp.org</small></div>
      </div>
      <button type="submit" style="margin-top:.8rem">Salva</button>
    </form>
    <form method="post" style="margin-top:.6rem">
      <input type="hidden" name="action" value="syncnow">
      <button>Sync now</button>
    </form>
    <h3 style="margin-top:1rem">Stato timedatectl</h3>
    <pre>{td}</pre>
    """.format(tz=tz_val, ntp=ntp_val, td=html.escape(td))
    return render_template_string(BASE, body=BODY)

@APP.route("/export-config.json")
def export_config_json():
    import json, re, os, html
    def rd(p, default=""):
        try:
            with open(p) as f: return f.read().strip()
        except:
            return default
    data = {
        "version": "1",
        "iface_default": IFACE_DEFAULT,
        # overlay & streaming
        "overlay": rd("/etc/fakecam/overlay.txt"),
        "source": rd("/etc/fakecam/source.txt"),
        "pattern": rd("/etc/fakecam/pattern.txt","testsrc"),
        "color": rd("/etc/fakecam/color.txt","red"),
        "timestamp_enabled": rd("/etc/fakecam/timestamp.enabled","on"),
        "timestamp_format": rd("/etc/fakecam/timestamp.format","%Y-%m-%d %H\\:%M\\:%S"),
        # rete (file networkd grezzo) + snapshot stato corrente
        "networkd_file": None,
        "network_snapshot": {},
        # nginx
        "nginx_port": None,
        # presets
        "presets": {}
    }

    # nginx port
    try:
        with open("/etc/nginx/sites-available/fakecam") as nf:
            for line in nf:
                m = re.search(r'^\s*listen\s+(\d+)\s+default_server;', line)
                if m:
                    data["nginx_port"] = int(m.group(1))
                    break
    except:
        pass

    # networkd file
    try:
        with open("/etc/systemd/network/05-fakecam.network") as sf:
            data["networkd_file"] = sf.read()
    except:
        data["networkd_file"] = None

    # snapshot rete (utile quando usi DHCP)
    try:
        snap = current_net(IFACE_DEFAULT)
        data["network_snapshot"] = {
            "mode": snap.get("mode"),
            "ip": snap.get("ip"),
            "mask": snap.get("mask"),
            "gw": snap.get("gw"),
            "dns": snap.get("dns")
        }
    except:
        pass

    # presets
    try:
        pdir = "/etc/fakecam/presets.d"
        if os.path.isdir(pdir):
            for p in sorted(os.listdir(pdir)):
                if p.endswith(".url"):
                    name = p[:-4]
                    data["presets"][name] = rd(os.path.join(pdir,p),"")
    except:
        pass

    js = json.dumps(data, indent=2, ensure_ascii=False)
    return APP.response_class(js, mimetype="application/json")

@APP.route("/export-config")
def export_config_page():
    BODY = """
    <h2>Export Config</h2>
    <p>Scarica solo la <b>configurazione</b> della cam (rete, streaming, overlay, timestamp, porta HTTP, preset), senza includere file binari o la VM.</p>
    <p>
      <a href="/netui/export-config.json" style="text-decoration:none">
        <button>Scarica export (JSON)</button>
      </a>
    </p>
    <p style="opacity:.75">Suggerimento: versiona il JSON in Git per tenere traccia delle modifiche.</p>
    """
    return render_template_string(BASE, body=BODY)



# ---------- Config Pack: export/import/default ----------
DEFAULT_JSON = "/etc/fakecam/default.json"

def _rd(path, default=""):
    try:
        with open(path) as f: return f.read().strip()
    except: return default

def _write_atomic(path, text):
    import pathlib, os
    tmp = path + ".tmp"
    pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(tmp, "w") as f: f.write(text)
    os.replace(tmp, path)

def _gather_config_dict():
    import re, os, glob, json
    # streaming/overlay
    data = {
        "version": "1",
        "iface_default": IFACE_DEFAULT,
        "overlay": _rd("/etc/fakecam/overlay.txt"),
        "source": _rd("/etc/fakecam/source.txt"),
        "pattern": _rd("/etc/fakecam/pattern.txt","testsrc"),
        "color": _rd("/etc/fakecam/color.txt","red"),
        "timestamp_enabled": _rd("/etc/fakecam/timestamp.enabled","on"),
        "timestamp_format": _rd("/etc/fakecam/timestamp.format","%Y-%m-%d %H\\:%M\\:%S"),
        "nginx_port": None,
        "networkd_file": None,
        "network_snapshot": {},
        "presets": {}
    }
    # nginx port
    try:
        with open("/etc/nginx/sites-available/fakecam") as nf:
            for line in nf:
                m = re.search(r'^\s*listen\s+(\d+)\s+default_server;', line)
                if m: data["nginx_port"] = int(m.group(1)); break
    except: pass
    # network file
    try:
        with open("/etc/systemd/network/05-fakecam.network") as nf:
            data["networkd_file"] = nf.read()
    except: pass
    # snapshot rete (utile se DHCP)
    try:
        snap = current_net(IFACE_DEFAULT)
        data["network_snapshot"] = {
            "mode": snap.get("mode"),
            "ip": snap.get("ip"),
            "mask": snap.get("mask"),
            "gw": snap.get("gw"),
            "dns": snap.get("dns")
        }
    except: pass
    # presets
    try:
        for p in sorted(glob.glob("/etc/fakecam/presets.d/*.url")):
            name = os.path.splitext(os.path.basename(p))[0]
            data["presets"][name] = _rd(p, "")
    except: pass
    return data

def _apply_config_dict(data, replace_presets=False):
    import json, re, os, subprocess
    # campi base
    if isinstance(data, str):
        data = json.loads(data)

    # overlay/streaming
    if "overlay" in data:            _write_atomic("/etc/fakecam/overlay.txt", str(data["overlay"]) + "\n")
    if "source" in data:             _write_atomic("/etc/fakecam/source.txt",  (str(data["source"]).strip()+"\n") if data["source"] else "")
    if "pattern" in data:            _write_atomic("/etc/fakecam/pattern.txt", str(data["pattern"]) + "\n")
    if "color" in data:              _write_atomic("/etc/fakecam/color.txt",   str(data["color"]) + "\n")
    if "timestamp_enabled" in data:  _write_atomic("/etc/fakecam/timestamp.enabled", (str(data["timestamp_enabled"]).strip().lower()) + "\n")
    if "timestamp_format" in data:   _write_atomic("/etc/fakecam/timestamp.format",  str(data["timestamp_format"]) + "\n")

    # nginx port
    if "nginx_port" in data and data["nginx_port"]:
        try:
            with open("/etc/nginx/sites-available/fakecam") as f:
                txt = f.read()
            txt = re.sub(r'listen\s+\d+\s+default_server;', 'listen {} default_server;'.format(int(data["nginx_port"])), txt)
            _write_atomic("/etc/nginx/sites-available/fakecam", txt)
            sh(["nginx","-t"])
            sh(["systemctl","reload","nginx"])
        except Exception as e:
            flash("Impossibile aggiornare la porta HTTP: {}".format(e), "err")

    # network: se fornito il file networkd grezzo lo scriviamo
    if "networkd_file" in data and data["networkd_file"]:
        _write_atomic("/etc/systemd/network/05-fakecam.network", data["networkd_file"])
        try:
            sh(["systemctl","enable","--now","systemd-networkd"])
            sh(["networkctl","reload"])
            # se IFACE_DEFAULT è valido, prova reconfigure
            sh(["networkctl","reconfigure", IFACE_DEFAULT])
        except: pass

    # presets
    if "presets" in data and isinstance(data["presets"], dict):
        import glob
        os.makedirs("/etc/fakecam/presets.d", exist_ok=True)
        if replace_presets:
            for p in glob.glob("/etc/fakecam/presets.d/*.url"):
                try: os.remove(p)
                except: pass
        for name, val in data["presets"].items():
            safe = re.sub(r'[^a-z0-9._-]+','-', str(name).lower()).strip('-') or "preset"
            _write_atomic("/etc/fakecam/presets.d/{}.url".format(safe), str(val).strip()+"\n")

    # riavvia pipeline video
    sh(["systemctl","restart","fakecam"])
    # mediamtx in genere non serve riavviare ma non fa male
    sh(["systemctl","reload","nginx"])
    return True

@APP.route("/config.json")
def config_json_download():
    # Esporta JSON della configurazione corrente
    import json, io, time
    data = _gather_config_dict()
    js = json.dumps(data, indent=2, ensure_ascii=False)
    return APP.response_class(js, mimetype="application/json")

@APP.route("/config-pack", methods=["GET","POST"])
def config_pack():
    import json, os, tempfile, time
    if request.method == "POST":
        act = request.form.get("action","")
        if act == "export":
            # redirect verso l'endpoint JSON scaricabile
            return redirect("/netui/config.json.dl")

        if act == "import":
            f = request.files.get("cfg")
            replace = (request.form.get("replace_presets") == "on")
            if not f:
                flash("Seleziona un file JSON.", "err")
                return redirect("/netui/config-pack")
            try:
                js = f.read().decode("utf-8")
                _apply_config_dict(js, replace_presets=replace)
                flash("Configurazione importata.", "ok")
            except Exception as e:
                flash("Errore import: {}".format(e), "err")
            return redirect("/netui/config-pack")

        if act == "save_default":
            try:
                data = _gather_config_dict()
                _write_atomic(DEFAULT_JSON, json.dumps(data, indent=2, ensure_ascii=False))
                flash("Default salvato in {}.".format(DEFAULT_JSON), "ok")
            except Exception as e:
                flash("Errore salvataggio default: {}".format(e), "err")
            return redirect("/netui/config-pack")

        if act == "apply_default":
            try:
                if not os.path.isfile(DEFAULT_JSON):
                    flash("Default assente: {} non trovato.".format(DEFAULT_JSON), "err")
                    return redirect("/netui/config-pack")
                js = open(DEFAULT_JSON, "r", encoding="utf-8").read()
                replace = (request.form.get("replace_presets") == "on")
                _apply_config_dict(js, replace_presets=replace)
                flash("Default applicato.", "ok")
            except Exception as e:
                flash("Errore applicazione default: {}".format(e), "err")
            return redirect("/netui/config-pack")

    # GET → pagina
    has_default = os.path.isfile(DEFAULT_JSON)
    BODY = """
    <h2>Config Pack</h2>

    <h3>Export</h3>
    <form method="post" style="margin-bottom:.8rem">
      <input type="hidden" name="action" value="export">
      <button>Scarica configurazione (JSON)</button>
    </form>

    <h3>Import</h3>
    <form method="post" enctype="multipart/form-data" style="margin-bottom:.8rem">
      <input type="hidden" name="action" value="import">
      <label>Seleziona file JSON</label>
      <input type="file" name="cfg" accept="application/json">
      <label style="display:block;margin-top:.4rem"><input type="checkbox" name="replace_presets"> Sostituisci tutti i preset</label>
      <button style="margin-top:.6rem" onclick="return confirm('Confermi l\\'import? Verranno sovrascritti i file di configurazione.')">Importa</button>
    </form>

    <h3>Default</h3>
    <form method="post" style="margin-bottom:.5rem">
      <input type="hidden" name="action" value="save_default">
      <button>Salva l'attuale configurazione come Default</button>
    </form>
    <form method="post">
      <input type="hidden" name="action" value="apply_default">
      <label style="display:block;margin-bottom:.4rem"><input type="checkbox" name="replace_presets"> Sostituisci tutti i preset</label>
      <button {disabled}>Applica Default salvato</button>
    </form>
    <p style="opacity:.75;margin-top:.6rem">Default attuale: {status}</p>
    """.format(
        disabled=("disabled" if not has_default else ""),
        status=(DEFAULT_JSON if has_default else "Nessun default salvato")
    )
    return render_template_string(BASE, body=BODY)

@APP.route("/config.json.dl")
def config_json_download_attachment():
    import json, time
    # riusa lo stesso gather della route normale
    data = _gather_config_dict()
    js = json.dumps(data, indent=2, ensure_ascii=False)
    resp = APP.response_class(js, mimetype="application/json")
    resp.headers["Content-Disposition"] = "attachment; filename=fakecam-config-{}.json".format(
        time.strftime("%Y%m%d-%H%M%S")
    )
    return resp




if __name__ == "__main__":
    APP.run(host="127.0.0.1", port=5001)
