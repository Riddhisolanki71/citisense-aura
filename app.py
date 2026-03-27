from flask import Flask, request, jsonify, render_template_string, session
import math, random, datetime
from collections import Counter
from functools import wraps

app = Flask(__name__)
app.secret_key = "citisense_aura_secret_2024"

AUTHORITY_CREDENTIALS = {"admin": "admin@123", "officer1": "officer@456", "supervisor": "super@789"}

issues = []
public_log = []
next_issue_id = 1

DEPARTMENT_SLA_HOURS = {"Sanitation":48,"Safety":24,"Infrastructure":72,"Utilities":48,"Campus Services":36,"General Administration":60}
DEPARTMENT_STAFF = {"Sanitation":4,"Safety":3,"Infrastructure":3,"Utilities":2,"Campus Services":2,"General Administration":2}

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authority_logged_in"):
            return jsonify({"error":"Unauthorized","redirect":"/authority-login"}), 401
        return f(*args, **kwargs)
    return decorated

def now_iso(): return datetime.datetime.now().isoformat(timespec="seconds")
def parse_dt(s): return datetime.datetime.fromisoformat(s)
def hours_since(created_at): return (datetime.datetime.now()-parse_dt(created_at)).total_seconds()/3600.0

def emotional_intensity_scale(text):
    if not text: return 1
    t=text.lower()
    score=1
    score+=sum(2 for w in["danger","emergency","urgent","unsafe","attack","panic","collapse","critical","help","immediately","severe"] if w in t)
    score+=sum(1 for w in["bad","dirty","smell","broken","waste","garbage","leak","fear","dark","crowded","angry","frustrated","terrible","awful","failed","damage","crack","noise"] if w in t)
    score-=sum(1 for w in["okay","average","normal","fine","decent"] if w in t)
    score+=min(2,text.count("!"))
    score+=min(2,sum(1 for w in text.split() if len(w)>2 and w.isupper()))
    return max(1,min(10,score))

def sentiment_label(s):
    if s>=8: return "Highly Distressed"
    if s>=6: return "Negative"
    if s>=4: return "Concerned"
    return "Stable"

def ai_select_department(category, comment):
    c,cm=(category or "").lower(),(comment or "").lower()
    if any(x in c or x in cm for x in["garbage","waste","cleanliness","smell"]): return "Sanitation"
    if any(x in c or x in cm for x in["unsafe","security","fight","harassment","dark"]): return "Safety"
    if any(x in c or x in cm for x in["road","crack","surface","pothole","bench","structure","vibration"]): return "Infrastructure"
    if any(x in c or x in cm for x in["water","leak","electricity","light","temperature","utility"]): return "Utilities"
    if any(x in c or x in cm for x in["service","queue","canteen","campus"]): return "Campus Services"
    return "General Administration"

def dual_source_truth_engine(fb, sensor):
    ha=((5-fb.get("cleanliness",3))*10+(5-fb.get("safety",3))*10+(5-fb.get("service_quality",3))*8+fb.get("emotional_intensity",5)*5+(10-fb.get("mood_score",5))*3)
    sa=(sensor.get("bluetoothDensity",0)*3+sensor.get("vibration",0)*8+sensor.get("temperatureDrift",0)*6+sensor.get("wifiFluctuation",0)*5)
    fs=round(ha*0.55+sa*0.45,2)
    if ha>35 and sa>35: conf,val="High",True
    elif ha>25 or sa>25: conf,val="Medium",True
    else: conf,val="Low",False
    return {"humanAnomalyScore":round(ha,2),"sensorAnomalyScore":round(sa,2),"fusionScore":fs,"validated":val,"confidence":conf,"hiddenIssueFlag":sa>45 and ha<20,"likelyFalseReport":ha>40 and sa<10}

def predictive_civic_stress_map(location, ei, fs):
    sl=[i for i in issues if i["location"].strip().lower()==location.strip().lower()]
    hc,uc=len(sl),sum(1 for i in sl if i["status"]!="Resolved")
    ah=sum(i["fusion"]["fusionScore"] for i in sl)/len(sl) if sl else 0
    ps=round(fs*0.55+ei*4+hc*3+uc*5+ah*0.12,2)
    z="Critical" if ps>=80 else "Warning" if ps>=50 else "Normal"
    return {"predictedStressScore":ps,"predictedZone":z,"historicalIssueCount":hc,"unresolvedNearbyCount":uc}

def issue_severity(fs, ei):
    s=fs*0.7+ei*4
    if s>=70: return "Critical"
    if s>=45: return "High"
    if s>=25: return "Medium"
    return "Low"

def auto_escalation(issue):
    r=[]
    if issue["fusion"]["validated"]: r.append("Sensor-verified anomaly")
    if sum(1 for i in issues if i["location"].strip().lower()==issue["location"].strip().lower() and i["status"]!="Resolved")>=2: r.append("Repeated issue in same location")
    if issue["severity"] in["Critical","High"]: r.append("High severity")
    return {"autoAssigned":len(r)>0,"reasons":r,"slaHours":DEPARTMENT_SLA_HOURS.get(issue["department"],48)}

def sla_predictive_alert(issue):
    dept=issue["department"]
    oid=[i for i in issues if i["department"]==dept and i["status"]!="Resolved"]
    wf=len(oid)/max(1,DEPARTMENT_STAFF.get(dept,2))
    sf={"Low":0.8,"Medium":1.0,"High":1.25,"Critical":1.5}[issue["severity"]]
    erh=round(18*sf*max(1,wf),2)
    return {"department":dept,"currentOpenLoad":len(oid),"availableStaff":DEPARTMENT_STAFF.get(dept,2),"estimatedResolutionHoursFromNow":erh,"slaHours":issue["accountability"]["slaHours"],"riskOfBreachWithin72Hours":hours_since(issue["createdAt"])+erh>=max(0,issue["accountability"]["slaHours"]-72)}

def add_public_log(issue_id, actor, action, notes):
    public_log.append({"issueId":issue_id,"actor":actor,"action":action,"notes":notes,"time":now_iso()})

def sample_coordinates_from_location(location):
    base={"main gate":(17.4435,78.3772),"canteen":(17.4440,78.3780),"library":(17.4446,78.3777),"hostel":(17.4450,78.3789),"parking":(17.4431,78.3791),"block a":(17.4441,78.3768),"block b":(17.4447,78.3763)}
    key=(location or "").strip().lower()
    return base.get(key,(round(17.443+random.random()*0.003,6),round(78.376+random.random()*0.004,6)))

def distance_meters(lat1,lon1,lat2,lon2):
    r=6371000;p1,p2=math.radians(lat1),math.radians(lat2);dp,dl=math.radians(lat2-lat1),math.radians(lon2-lon1)
    a=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return r*2*math.atan2(math.sqrt(a),math.sqrt(1-a))

# ─── ROUTES ───────────────────────────────────────────────────────────────────

@app.route("/authority-login")
def authority_login_page():
    return render_template_string(LOGIN_HTML)

@app.route("/api/authority-login", methods=["POST"])
def authority_login():
    d=request.get_json(force=True)
    u,p=d.get("username","").strip(),d.get("password","").strip()
    if AUTHORITY_CREDENTIALS.get(u)==p:
        session["authority_logged_in"]=True; session["authority_user"]=u
        return jsonify({"success":True,"username":u})
    return jsonify({"success":False,"message":"Invalid credentials"}),401

@app.route("/api/authority-logout", methods=["POST"])
def authority_logout():
    session.clear(); return jsonify({"success":True})

@app.route("/api/authority-status")
def authority_status():
    return jsonify({"loggedIn":session.get("authority_logged_in",False),"username":session.get("authority_user","")})

@app.route("/")
def index():
    return render_template_string(MAIN_HTML)

@app.route("/api/issues", methods=["POST"])
def create_issue():
    global next_issue_id
    d=request.get_json(force=True)
    loc=d.get("location","").strip(); cat=d.get("category","General"); comment=d.get("comment",""); mood=d.get("mood","Concerned")
    cl,sf,sq=int(d.get("cleanliness",3)),int(d.get("safety",3)),int(d.get("serviceQuality",3))
    ms=int(d.get("moodScore",5)); cg=d.get("citizenGeo"); img=d.get("image","")
    ei=emotional_intensity_scale(comment)
    fb={"cleanliness":cl,"safety":sf,"service_quality":sq,"mood":mood,"mood_score":ms,"emotionalIntensity":ei,"sentimentLabel":sentiment_label(ei)}
    sensor={"bluetoothDensity":float(d.get("bluetoothDensity",0)),"vibration":float(d.get("vibration",0)),"temperatureDrift":float(d.get("temperatureDrift",0)),"wifiFluctuation":float(d.get("wifiFluctuation",0))}
    fusion=dual_source_truth_engine({"cleanliness":cl,"safety":sf,"service_quality":sq,"mood_score":ms,"emotional_intensity":ei},sensor)
    pred=predictive_civic_stress_map(loc,ei,fusion["fusionScore"])
    dept=ai_select_department(cat,comment); sev=issue_severity(fusion["fusionScore"],ei)
    lat,lon=sample_coordinates_from_location(loc)
    if cg and "lat" in cg and "lon" in cg: lat,lon=cg["lat"],cg["lon"]
    issue={"id":next_issue_id,"category":cat,"location":loc,"comment":comment,"feedback":fb,"sensor":sensor,"fusion":fusion,"prediction":pred,"department":dept,"severity":sev,"status":"Open","createdAt":now_iso(),"lat":lat,"lon":lon,"image":img,"resolution":None}
    issue["accountability"]=auto_escalation(issue); issue["slaPredictiveAlert"]=sla_predictive_alert(issue)
    issues.append(issue); next_issue_id+=1
    add_public_log(issue["id"],"System","Issue Registered",f"Assigned to {dept}")
    if issue["accountability"]["autoAssigned"]: add_public_log(issue["id"],"System","Auto Escalated","; ".join(issue["accountability"]["reasons"]))
    return jsonify({"message":"Issue submitted","issue":issue})

@app.route("/api/dashboard")
@login_required
def dashboard():
    oi=[i for i in issues if i["status"]!="Resolved"]
    return jsonify({"stats":{"openIssues":len(oi),"criticalZones":sum(1 for i in oi if i["prediction"]["predictedZone"]=="Critical"),"slaRisks":sum(1 for i in oi if i["slaPredictiveAlert"]["riskOfBreachWithin72Hours"]),"avgRisk":round(sum(i["prediction"]["predictedStressScore"] for i in oi)/len(oi),1) if oi else 0},"severityCounts":dict(Counter(i["severity"] for i in issues)),"departmentCounts":dict(Counter(i["department"] for i in issues)),"heatPoints":[[i["lat"],i["lon"],max(0.15,min(1.0,i["prediction"]["predictedStressScore"]/100))] for i in issues],"issues":issues})

@app.route("/api/public-log")
def get_public_log(): return jsonify(public_log)

@app.route("/api/resolve", methods=["POST"])
@login_required
def resolve_issue():
    d=request.get_json(force=True)
    issue=next((i for i in issues if i["id"]==int(d.get("issueId",0))),None)
    if not issue: return jsonify({"message":"Issue not found"}),404
    ag=d.get("authorityGeo")
    if not ag or "lat" not in ag: return jsonify({"message":"Geolocation required"}),400
    dist=distance_meters(issue["lat"],issue["lon"],ag["lat"],ag["lon"]); gv=dist<=120.0
    issue["status"]="Resolved" if gv else "Pending Verification"
    issue["resolution"]={"note":d.get("note",""),"proofImage":d.get("proofImage",""),"authorityGeo":ag,"distanceMeters":dist,"geoVerified":gv,"resolvedAt":now_iso()}
    add_public_log(issue["id"],f"Authority ({session.get('authority_user','officer')})","Resolution Submitted",f"Geo verified: {'Yes' if gv else 'No'} · {round(dist,1)}m")
    return jsonify({"message":"Resolution submitted","geoVerified":gv,"distanceMeters":dist,"issue":issue})

# ─── HTML ──────────────────────────────────────────────────────────────────────

LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CitiSense+ AURA — Sign In</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Sora:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#050b18;
  --surface:#0c1628;
  --border:#1a2744;
  --blue:#3b82f6;
  --blue-glow:rgba(59,130,246,0.4);
  --cyan:#06b6d4;
  --text:#e2e8f0;
  --muted:#64748b;
  --danger:#ef4444;
}
body{font-family:'Sora',sans-serif;background:var(--bg);min-height:100vh;display:flex;align-items:center;justify-content:center;overflow:hidden;position:relative;}
.noise{position:fixed;inset:0;opacity:.03;background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='4'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");pointer-events:none;z-index:100;}
.orb{position:fixed;border-radius:50%;filter:blur(80px);pointer-events:none;}
.orb1{width:500px;height:500px;background:radial-gradient(circle,rgba(59,130,246,.12),transparent 70%);top:-100px;left:-100px;}
.orb2{width:400px;height:400px;background:radial-gradient(circle,rgba(6,182,212,.08),transparent 70%);bottom:-80px;right:-80px;}
.grid{position:fixed;inset:0;background-image:linear-gradient(rgba(59,130,246,.04) 1px,transparent 1px),linear-gradient(90deg,rgba(59,130,246,.04) 1px,transparent 1px);background-size:60px 60px;pointer-events:none;}
.wrap{position:relative;z-index:10;width:100%;max-width:440px;padding:24px;}
.logo{text-align:center;margin-bottom:36px;}
.logo-mark{display:inline-flex;align-items:center;gap:10px;margin-bottom:12px;}
.logo-hex{width:48px;height:48px;background:linear-gradient(135deg,var(--blue),var(--cyan));border-radius:14px;display:flex;align-items:center;justify-content:center;box-shadow:0 0 30px var(--blue-glow);font-size:22px;}
.logo-name{font-size:22px;font-weight:800;color:var(--text);letter-spacing:-.5px;}
.logo-name span{color:var(--blue);}
.logo-sub{font-size:12px;color:var(--muted);letter-spacing:.5px;text-transform:uppercase;font-family:'JetBrains Mono',monospace;}
.card{background:rgba(12,22,40,.8);border:1px solid var(--border);border-radius:24px;padding:36px;backdrop-filter:blur(24px);box-shadow:0 40px 80px rgba(0,0,0,.5),inset 0 1px 0 rgba(255,255,255,.04);}
.card-head{margin-bottom:28px;}
.card-head h2{font-size:20px;font-weight:700;color:var(--text);margin-bottom:5px;}
.card-head p{font-size:13px;color:var(--muted);}
.field{margin-bottom:18px;}
.field label{display:block;font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;font-family:'JetBrains Mono',monospace;}
.inp-wrap{position:relative;}
.inp-wrap svg{position:absolute;left:14px;top:50%;transform:translateY(-50%);opacity:.4;pointer-events:none;}
.field input{width:100%;padding:13px 14px 13px 42px;border-radius:12px;border:1px solid var(--border);background:rgba(255,255,255,.03);color:var(--text);font-size:14px;font-family:'Sora',sans-serif;outline:none;transition:border-color .2s,box-shadow .2s,background .2s;}
.field input:focus{border-color:var(--blue);box-shadow:0 0 0 3px rgba(59,130,246,.15);background:rgba(59,130,246,.04);}
.field input::placeholder{color:#334155;}
.btn-login{width:100%;padding:14px;border-radius:12px;border:none;background:linear-gradient(135deg,#1d4ed8,#3b82f6);color:#fff;font-size:14px;font-weight:700;font-family:'Sora',sans-serif;cursor:pointer;margin-top:6px;transition:transform .15s,box-shadow .15s,opacity .15s;box-shadow:0 8px 24px rgba(59,130,246,.35);letter-spacing:.3px;}
.btn-login:hover{transform:translateY(-1px);box-shadow:0 12px 32px rgba(59,130,246,.45);}
.btn-login:active{transform:translateY(0);}
.btn-login:disabled{opacity:.6;cursor:not-allowed;transform:none;}
.err{background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.25);color:#fca5a5;border-radius:10px;padding:11px 14px;font-size:13px;margin-top:12px;display:none;animation:fadeIn .2s;}
.creds{margin-top:20px;padding:14px 16px;background:rgba(59,130,246,.06);border:1px solid rgba(59,130,246,.12);border-radius:12px;}
.creds-title{font-size:10px;font-weight:700;color:var(--blue);text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;font-family:'JetBrains Mono',monospace;}
.cred-row{display:flex;justify-content:space-between;align-items:center;padding:4px 0;}
.cred-user{font-size:12px;font-family:'JetBrains Mono',monospace;color:var(--text);}
.cred-pass{font-size:11px;font-family:'JetBrains Mono',monospace;color:var(--muted);}
.back{display:block;text-align:center;margin-top:18px;font-size:13px;color:var(--muted);text-decoration:none;transition:color .2s;}
.back:hover{color:var(--text);}
.spin{display:inline-block;width:14px;height:14px;border:2px solid rgba(255,255,255,.3);border-top-color:#fff;border-radius:50%;animation:spin .6s linear infinite;vertical-align:middle;margin-right:7px;}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes fadeIn{from{opacity:0;transform:translateY(-4px)}to{opacity:1;transform:none}}
</style>
</head>
<body>
<div class="noise"></div>
<div class="orb orb1"></div>
<div class="orb orb2"></div>
<div class="grid"></div>
<div class="wrap">
  <div class="logo">
    <div class="logo-mark">
      <div class="logo-hex">🛡</div>
      <div class="logo-name">CitiSense<span>+</span> AURA</div>
    </div>
    <div class="logo-sub">Unified Public-Space Intelligence</div>
  </div>
  <div class="card">
    <div class="card-head">
      <h2>Authority Sign In</h2>
      <p>Access the command dashboard with officer credentials</p>
    </div>
    <div class="field">
      <label>Username</label>
      <div class="inp-wrap">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
        <input id="usr" type="text" placeholder="Enter username" autocomplete="username">
      </div>
    </div>
    <div class="field">
      <label>Password</label>
      <div class="inp-wrap">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
        <input id="pwd" type="password" placeholder="Enter password" autocomplete="current-password">
      </div>
    </div>
    <button class="btn-login" id="loginBtn" onclick="doLogin()">Sign In to Authority Portal</button>
    <div class="err" id="errMsg"></div>
    <div class="creds">
      <div class="creds-title">Demo Credentials</div>
      <div class="cred-row"><span class="cred-user">admin</span><span class="cred-pass">admin@123</span></div>
      <div class="cred-row"><span class="cred-user">officer1</span><span class="cred-pass">officer@456</span></div>
      <div class="cred-row"><span class="cred-user">supervisor</span><span class="cred-pass">super@789</span></div>
    </div>
  </div>
  <a href="/" class="back">← Back to Citizen Portal</a>
</div>
<script>
document.getElementById('pwd').addEventListener('keydown',e=>{if(e.key==='Enter')doLogin();});
async function doLogin(){
  const u=document.getElementById('usr').value.trim(),p=document.getElementById('pwd').value.trim();
  const btn=document.getElementById('loginBtn'),err=document.getElementById('errMsg');
  err.style.display='none';
  if(!u||!p){err.textContent='Please enter both fields.';err.style.display='block';return;}
  btn.innerHTML='<span class="spin"></span>Authenticating…';btn.disabled=true;
  const res=await fetch('/api/authority-login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u,password:p})});
  const data=await res.json();
  if(data.success){window.location.href='/';}
  else{err.textContent='Invalid credentials. Please try again.';err.style.display='block';btn.innerHTML='Sign In to Authority Portal';btn.disabled=false;}
}
</script>
</body>
</html>"""

MAIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CitiSense+ AURA</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Sora:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script src="https://unpkg.com/leaflet.heat/dist/leaflet-heat.js"></script>
<script src="https://unpkg.com/html5-qrcode" type="text/javascript"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#04091a;
  --bg2:#070e20;
  --surface:#0a1628;
  --surface2:#0d1c34;
  --border:#152040;
  --border2:#1e2f50;
  --blue:#3b82f6;
  --blue2:#1d4ed8;
  --blue-dim:rgba(59,130,246,.08);
  --cyan:#22d3ee;
  --emerald:#10b981;
  --amber:#f59e0b;
  --rose:#f43f5e;
  --violet:#8b5cf6;
  --text:#e2e8f0;
  --text2:#94a3b8;
  --text3:#475569;
  --mono:'JetBrains Mono',monospace;
  --sans:'Sora',sans-serif;
  --r:14px;
  --r2:20px;
  --r3:24px;
}
html{scroll-behavior:smooth}
body{font-family:var(--sans);background:var(--bg);color:var(--text);min-height:100vh;overflow-x:hidden;}

/* SCROLLBAR */
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:#1e2f50;border-radius:3px}

/* TOPBAR */
.topbar{
  height:60px;background:rgba(4,9,26,.85);backdrop-filter:blur(20px);
  border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between;
  padding:0 24px;position:sticky;top:0;z-index:200;
}
.t-brand{display:flex;align-items:center;gap:10px;}
.t-hex{width:34px;height:34px;background:linear-gradient(135deg,var(--blue2),var(--cyan));border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:16px;box-shadow:0 0 16px rgba(59,130,246,.3);}
.t-name{font-size:15px;font-weight:800;letter-spacing:-.3px;}
.t-name em{color:var(--blue);font-style:normal;}
.t-tag{font-size:10px;color:var(--text3);font-family:var(--mono);text-transform:uppercase;letter-spacing:.6px;margin-top:1px;}
.t-nav{display:flex;align-items:center;gap:6px;}
.tnav-btn{
  height:32px;padding:0 14px;border-radius:8px;border:1px solid transparent;
  font-size:13px;font-weight:600;font-family:var(--sans);cursor:pointer;
  color:var(--text2);background:transparent;transition:.15s;
}
.tnav-btn:hover{background:var(--surface);border-color:var(--border);color:var(--text);}
.tnav-btn.active{background:rgba(59,130,246,.15);border-color:rgba(59,130,246,.3);color:var(--blue);}
.t-user{display:flex;align-items:center;gap:8px;padding:6px 12px 6px 8px;background:var(--surface);border:1px solid var(--border);border-radius:10px;}
.t-avatar{width:26px;height:26px;border-radius:8px;background:linear-gradient(135deg,var(--blue2),var(--violet));display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;}
.t-uname{font-size:13px;font-weight:600;}
.t-logout{background:none;border:none;cursor:pointer;color:var(--text3);font-size:18px;line-height:1;margin-left:2px;transition:color .15s;}
.t-logout:hover{color:var(--rose);}

/* PAGE */
.page{display:none;animation:fadeUp .35s ease both;}
.page.active{display:block;}
@keyframes fadeUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}

/* CONTAINER */
.wrap{max-width:1440px;margin:0 auto;padding:28px 24px;}

/* HERO */
.hero{
  background:linear-gradient(130deg,#070f26 0%,#0d1c3a 50%,#0a1530 100%);
  border:1px solid var(--border);border-radius:var(--r3);
  padding:40px 44px;margin-bottom:28px;position:relative;overflow:hidden;
}
.hero-glow{position:absolute;top:-60px;right:-40px;width:340px;height:340px;
  background:radial-gradient(circle,rgba(59,130,246,.12),transparent 70%);pointer-events:none;}
.hero-glow2{position:absolute;bottom:-80px;left:30%;width:260px;height:260px;
  background:radial-gradient(circle,rgba(34,211,238,.06),transparent 70%);pointer-events:none;}
.hero-badge{
  display:inline-flex;align-items:center;gap:6px;
  background:rgba(59,130,246,.12);border:1px solid rgba(59,130,246,.2);
  border-radius:999px;padding:5px 14px;margin-bottom:18px;
  font-size:11px;font-weight:700;color:var(--blue);font-family:var(--mono);text-transform:uppercase;letter-spacing:.8px;
}
.hero h1{font-size:36px;font-weight:800;letter-spacing:-1px;margin-bottom:12px;line-height:1.1;}
.hero h1 span{background:linear-gradient(90deg,var(--blue),var(--cyan));-webkit-background-clip:text;-webkit-text-fill-color:transparent;}
.hero p{color:var(--text2);font-size:15px;line-height:1.7;max-width:680px;}

/* GRID LAYOUTS */
.grid-2{display:grid;grid-template-columns:1.15fr .85fr;gap:22px;}
.grid-3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;}
.grid-4{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;}

/* CARDS */
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--r2);padding:24px;}
.card+.card{margin-top:0;}
.card-title{font-size:13px;font-weight:700;color:var(--text);margin-bottom:18px;display:flex;align-items:center;gap:8px;}
.card-title .dot{width:6px;height:6px;border-radius:50%;}

/* STAT CARDS */
.stat{
  background:var(--surface);border:1px solid var(--border);border-radius:var(--r2);
  padding:22px;position:relative;overflow:hidden;cursor:default;
  transition:border-color .2s,transform .2s;
}
.stat:hover{border-color:var(--border2);transform:translateY(-1px);}
.stat-glow{position:absolute;top:-20px;right:-20px;width:80px;height:80px;border-radius:50%;opacity:.35;filter:blur(20px);}
.stat-label{font-size:11px;font-weight:600;color:var(--text3);text-transform:uppercase;letter-spacing:.8px;margin-bottom:10px;font-family:var(--mono);}
.stat-num{font-size:40px;font-weight:800;letter-spacing:-2px;line-height:1;}
.stat-sub{font-size:11px;color:var(--text3);margin-top:6px;}
.s-blue .stat-glow{background:var(--blue);}
.s-blue .stat-num{color:var(--blue);}
.s-rose .stat-glow{background:var(--rose);}
.s-rose .stat-num{color:var(--rose);}
.s-amber .stat-glow{background:var(--amber);}
.s-amber .stat-num{color:var(--amber);}
.s-em .stat-glow{background:var(--emerald);}
.s-em .stat-num{color:var(--emerald);}

/* TAGS / BADGES */
.badge{display:inline-flex;align-items:center;gap:4px;border-radius:6px;padding:3px 8px;font-size:11px;font-weight:700;font-family:var(--mono);text-transform:uppercase;letter-spacing:.4px;}
.b-blue{background:rgba(59,130,246,.12);color:#60a5fa;border:1px solid rgba(59,130,246,.2);}
.b-rose{background:rgba(244,63,94,.12);color:#fb7185;border:1px solid rgba(244,63,94,.2);}
.b-amber{background:rgba(245,158,11,.12);color:#fbbf24;border:1px solid rgba(245,158,11,.2);}
.b-em{background:rgba(16,185,129,.12);color:#34d399;border:1px solid rgba(16,185,129,.2);}
.b-violet{background:rgba(139,92,246,.12);color:#a78bfa;border:1px solid rgba(139,92,246,.2);}
.b-gray{background:rgba(71,85,105,.2);color:#94a3b8;border:1px solid rgba(71,85,105,.25);}

/* FORM */
.form-section{margin-bottom:20px;}
.form-section-title{font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;letter-spacing:1px;font-family:var(--mono);margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid var(--border);}
.fg{margin-bottom:14px;}
.fg label{display:block;font-size:11px;font-weight:600;color:var(--text3);text-transform:uppercase;letter-spacing:.7px;margin-bottom:6px;font-family:var(--mono);}
.fg input,.fg select,.fg textarea{
  width:100%;padding:10px 14px;border-radius:10px;
  border:1px solid var(--border);background:var(--bg2);
  color:var(--text);font-size:13.5px;font-family:var(--sans);
  outline:none;transition:border-color .2s,box-shadow .2s;
}
.fg input:focus,.fg select:focus,.fg textarea:focus{border-color:rgba(59,130,246,.5);box-shadow:0 0 0 3px rgba(59,130,246,.1);}
.fg input::placeholder,.fg textarea::placeholder{color:var(--text3);}
.fg textarea{min-height:88px;resize:vertical;line-height:1.6;}
.fg select option{background:#0d1c34;}
.row-2{display:grid;grid-template-columns:1fr 1fr;gap:14px;}
details summary{font-size:12px;font-weight:600;color:var(--text2);cursor:pointer;padding:8px 0;list-style:none;display:flex;align-items:center;gap:6px;}
details summary::-webkit-details-marker{display:none;}
details summary::before{content:'▸';transition:transform .2s;font-size:10px;color:var(--text3);}
details[open] summary::before{transform:rotate(90deg);}

/* BUTTONS */
.btn{display:inline-flex;align-items:center;justify-content:center;gap:7px;border:none;border-radius:10px;padding:10px 18px;font-size:13px;font-weight:700;font-family:var(--sans);cursor:pointer;transition:.15s;letter-spacing:.2px;}
.btn:hover{transform:translateY(-1px);}
.btn:active{transform:none;}
.btn-primary{background:linear-gradient(135deg,var(--blue2),var(--blue));color:#fff;box-shadow:0 4px 16px rgba(59,130,246,.3);}
.btn-primary:hover{box-shadow:0 8px 24px rgba(59,130,246,.4);}
.btn-ghost{background:transparent;color:var(--text2);border:1px solid var(--border);}
.btn-ghost:hover{background:var(--surface2);color:var(--text);}
.btn-success{background:linear-gradient(135deg,#059669,var(--emerald));color:#fff;box-shadow:0 4px 16px rgba(16,185,129,.3);}
.btn-success:hover{box-shadow:0 8px 24px rgba(16,185,129,.4);}
.btn-sm{padding:7px 12px;font-size:12px;border-radius:8px;}
.btn-full{width:100%;}

/* CAMERA PANEL */
.cam-panel{background:var(--bg2);border:1px solid var(--border);border-radius:14px;padding:16px;margin-top:14px;}
.cam-title{font-size:12px;font-weight:700;color:var(--text2);margin-bottom:12px;font-family:var(--mono);text-transform:uppercase;letter-spacing:.6px;}
video{width:100%;max-width:300px;border-radius:10px;background:#020817;display:block;}
img.preview{width:100%;max-width:300px;border-radius:10px;margin-top:10px;display:block;}
.cam-btns{display:flex;gap:8px;margin-top:10px;}
.geo-text{font-size:12px;color:var(--text3);padding:8px 0;font-family:var(--mono);}

/* QR BOX */
.qr-box{background:var(--bg2);border:1px dashed var(--border2);border-radius:12px;padding:12px;margin-bottom:16px;}
.qr-hint{font-size:11px;color:var(--text3);margin-top:8px;font-family:var(--mono);}

/* RESULT CARD */
.result-card{background:var(--bg2);border:1px solid var(--border);border-radius:16px;padding:20px;margin-top:18px;animation:fadeUp .3s ease;}
.result-title{font-size:15px;font-weight:800;margin-bottom:14px;display:flex;align-items:center;gap:8px;}
.result-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px;}
.rg-item{background:var(--surface2);border:1px solid var(--border);border-radius:10px;padding:12px;}
.rg-label{font-size:10px;color:var(--text3);text-transform:uppercase;letter-spacing:.6px;font-family:var(--mono);margin-bottom:5px;}
.rg-val{font-size:24px;font-weight:800;letter-spacing:-1px;line-height:1;}
.rg-sub{font-size:10px;color:var(--text3);margin-top:3px;font-family:var(--mono);}
.rg-blue .rg-val{color:var(--blue);}
.rg-rose .rg-val{color:var(--rose);}
.rg-cyan .rg-val{color:var(--cyan);}
.rg-amber .rg-val{color:var(--amber);}
.tags-row{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px;}

/* ISSUE LIST */
.issue-item{
  background:var(--surface);border:1px solid var(--border);border-radius:14px;
  padding:16px 18px;margin-bottom:10px;transition:border-color .2s;cursor:default;
}
.issue-item:hover{border-color:var(--border2);}
.ii-head{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;margin-bottom:10px;}
.ii-id{font-size:11px;font-family:var(--mono);color:var(--text3);margin-bottom:2px;}
.ii-title{font-size:14px;font-weight:700;}
.ii-loc{font-size:11px;color:var(--text3);margin-top:2px;font-family:var(--mono);}
.ii-body{font-size:13px;color:var(--text2);line-height:1.6;margin-bottom:10px;}
.ii-chips{display:flex;flex-wrap:wrap;gap:6px;padding-top:10px;border-top:1px solid var(--border);}
.chip{background:var(--surface2);border:1px solid var(--border);border-radius:7px;padding:4px 9px;font-size:11px;color:var(--text3);font-family:var(--mono);}
.chip b{color:var(--text2);}
.proof-box{background:rgba(16,185,129,.06);border:1px solid rgba(16,185,129,.2);border-radius:10px;padding:12px 14px;margin-top:10px;font-size:12px;color:#34d399;font-family:var(--mono);}
.escalated-box{background:rgba(244,63,94,.06);border:1px solid rgba(244,63,94,.15);border-radius:10px;padding:8px 12px;margin-top:8px;font-size:11px;color:#fb7185;font-family:var(--mono);}

/* LOG */
.log-list{max-height:260px;overflow-y:auto;display:flex;flex-direction:column;gap:8px;}
.log-item{background:var(--bg2);border-left:2px solid var(--blue);padding:10px 12px;border-radius:0 10px 10px 0;}
.log-item.escalated{border-left-color:var(--rose);}
.log-item.resolved{border-left-color:var(--emerald);}
.li-action{font-size:12px;font-weight:700;color:var(--text);}
.li-meta{font-size:10px;color:var(--text3);margin-top:2px;font-family:var(--mono);}
.li-note{font-size:11px;color:var(--text2);margin-top:4px;}

/* HEATMAP */
#heatmap{height:320px;border-radius:14px;overflow:hidden;border:1px solid var(--border);}

/* TRIGGER BOX */
.trigger-list{display:flex;flex-direction:column;gap:10px;}
.trigger-row{display:flex;align-items:flex-start;gap:12px;padding:12px;background:var(--bg2);border:1px solid var(--border);border-radius:12px;}
.tr-num{min-width:28px;height:28px;border-radius:8px;background:rgba(59,130,246,.15);color:var(--blue);font-size:11px;font-weight:800;display:flex;align-items:center;justify-content:center;font-family:var(--mono);}
.tr-body .tr-title{font-size:13px;font-weight:700;color:var(--text);margin-bottom:2px;}
.tr-body .tr-desc{font-size:12px;color:var(--text3);}

/* LANDING */
.role-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:24px;}
.role-card{
  background:var(--surface);border:1px solid var(--border);border-radius:var(--r3);
  padding:32px;position:relative;overflow:hidden;transition:border-color .25s,transform .25s;cursor:pointer;
}
.role-card:hover{border-color:var(--border2);transform:translateY(-2px);}
.role-card::after{content:'';position:absolute;inset:0;border-radius:inherit;opacity:0;transition:opacity .3s;}
.role-card.citizen::after{background:radial-gradient(circle at top right,rgba(34,211,238,.05),transparent 60%);}
.role-card.authority::after{background:radial-gradient(circle at top right,rgba(139,92,246,.05),transparent 60%);}
.role-card:hover::after{opacity:1;}
.rc-icon{width:52px;height:52px;border-radius:14px;display:flex;align-items:center;justify-content:center;font-size:24px;margin-bottom:20px;}
.citizen .rc-icon{background:rgba(34,211,238,.1);border:1px solid rgba(34,211,238,.15);}
.authority .rc-icon{background:rgba(139,92,246,.1);border:1px solid rgba(139,92,246,.15);}
.rc-title{font-size:20px;font-weight:800;margin-bottom:10px;letter-spacing:-.3px;}
.rc-desc{font-size:13.5px;color:var(--text2);line-height:1.7;margin-bottom:22px;}
.rc-arrow{display:inline-flex;align-items:center;gap:6px;font-size:13px;font-weight:700;color:var(--blue);transition:gap .2s;}
.role-card:hover .rc-arrow{gap:10px;}

/* DIVIDER */
.divider{height:1px;background:var(--border);margin:20px 0;}

/* SCROLLABLE AREAS */
.issue-scroll{max-height:600px;overflow-y:auto;padding-right:4px;}

/* RESPONSIVE */
@media(max-width:1100px){
  .grid-2,.role-grid{grid-template-columns:1fr;}
  .grid-4{grid-template-columns:1fr 1fr;}
}
@media(max-width:640px){
  .grid-4,.row-2,.result-grid{grid-template-columns:1fr;}
}
</style>
</head>
<body>

<!-- TOPBAR -->
<header class="topbar">
  <div class="t-brand">
    <div class="t-hex">🌐</div>
    <div>
      <div class="t-name">CitiSense<em>+</em> AURA</div>
      <div class="t-tag">Unified Public-Space Intelligence</div>
    </div>
  </div>
  <nav class="t-nav" id="tNav">
    <button class="tnav-btn active" onclick="goHome(this)">Home</button>
    <button class="tnav-btn" onclick="openCitizen(this)">Citizen</button>
    <button class="tnav-btn" id="authBtn" onclick="handleAuthorityNav(this)">Authority</button>
  </nav>
</header>

<!-- ─── LANDING ─── -->
<div id="pgLanding" class="page active">
  <div class="wrap">
    <div class="hero">
      <div class="hero-glow"></div><div class="hero-glow2"></div>
      <div class="hero-badge">◆ Smart Civic Intelligence System</div>
      <h1>Real-Time Anomaly Detection<br>for <span>Safer Public Spaces</span></h1>
      <p>CitiSense+ AURA fuses citizen micro-feedback with ambient sensor signals, AI validation, predictive stress mapping, autonomous escalation, and geofenced proof-of-resolution — in one command-center platform.</p>
    </div>
    <div class="role-grid">
      <div class="role-card citizen" onclick="openCitizen()">
        <div class="rc-icon">📱</div>
        <div class="rc-title">Citizen Portal</div>
        <div class="rc-desc">Submit QR-based feedback with ratings, mood tracking, camera evidence, and ambient sensor data. Your input is fused with real-world signals to validate genuine issues automatically.</div>
        <div class="rc-arrow">Enter Citizen Portal <span>→</span></div>
      </div>
      <div class="role-card authority" onclick="handleAuthorityNav()">
        <div class="rc-icon">🛡</div>
        <div class="rc-title">Authority Portal</div>
        <div class="rc-desc">Review live issues, predictive heatmaps, SLA breach alerts, AI-assigned departments, and public accountability logs. Submit geo-fenced proof of resolution with officer authentication.</div>
        <div class="rc-arrow">Enter Authority Portal <span>→</span></div>
      </div>
    </div>
  </div>
</div>

<!-- ─── CITIZEN ─── -->
<div id="pgCitizen" class="page">
  <div class="wrap">
    <div class="hero" style="padding:28px 36px;margin-bottom:22px;">
      <div class="hero-glow"></div>
      <div class="hero-badge">◆ Citizen Portal</div>
      <h1 style="font-size:26px;">Smart <span>QR Micro-Feedback</span></h1>
      <p style="font-size:14px;margin-top:6px;">Capture ambient sensor data alongside your complaint to enable dual-source anomaly validation.</p>
    </div>
    <div class="grid-2">
      <!-- LEFT: FORM -->
      <div style="display:flex;flex-direction:column;gap:18px;">
        <div class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:18px;">
            <div class="card-title"><div class="dot" style="background:var(--cyan);box-shadow:0 0 6px var(--cyan);"></div>Submit Issue Report</div>
            <button class="btn btn-ghost btn-sm" onclick="prefillDemo()">⚡ Demo Data</button>
          </div>

          <div class="qr-box">
            <div id="qr-reader" style="width:100%;max-width:280px;"></div>
            <div class="qr-hint">// Scan location QR or type manually below</div>
          </div>

          <div class="form-section">
            <div class="form-section-title">Location & Category</div>
            <div class="row-2">
              <div class="fg"><label>Location / QR Code</label><input id="location" placeholder="e.g. canteen, library"></div>
              <div class="fg"><label>Category</label>
                <select id="category">
                  <option>Cleanliness</option><option>Safety</option><option>Infrastructure</option>
                  <option>Utilities</option><option>Service Quality</option><option>General</option>
                </select>
              </div>
            </div>
            <div class="fg"><label>Description</label><textarea id="comment" placeholder="Describe the issue in detail…"></textarea></div>
          </div>

          <div class="form-section">
            <div class="form-section-title">Ratings & Mood</div>
            <div class="row-2">
              <div class="fg"><label>Mood</label>
                <select id="mood"><option>Calm</option><option>Concerned</option><option>Frustrated</option><option>Angry</option><option>Scared</option></select>
              </div>
              <div class="fg"><label>Cleanliness (1–5)</label><input id="cleanliness" type="number" min="1" max="5" value="3"></div>
              <div class="fg"><label>Safety (1–5)</label><input id="safety" type="number" min="1" max="5" value="3"></div>
              <div class="fg"><label>Service Quality (1–5)</label><input id="serviceQuality" type="number" min="1" max="5" value="3"></div>
            </div>
          </div>

          <details>
            <summary>⚙ Ambient Sensor Snapshot</summary>
            <div class="row-2" style="margin-top:12px;">
              <div class="fg"><label>Bluetooth Density</label><input id="bluetoothDensity" type="number" value="4"></div>
              <div class="fg"><label>Vibration Level</label><input id="vibration" type="number" value="2"></div>
              <div class="fg"><label>Temperature Drift</label><input id="temperatureDrift" type="number" value="1"></div>
              <div class="fg"><label>Wi-Fi Fluctuation</label><input id="wifiFluctuation" type="number" value="2"></div>
            </div>
          </details>
        </div>

        <div class="card">
          <div class="card-title"><div class="dot" style="background:var(--violet);box-shadow:0 0 6px var(--violet);"></div>Evidence & Location</div>
          <div class="row-2">
            <div class="cam-panel">
              <div class="cam-title">// Camera Evidence</div>
              <video id="citizenVideo" autoplay playsinline></video>
              <div class="cam-btns">
                <button class="btn btn-ghost btn-sm" onclick="startCitizenCamera()">▶ Start</button>
                <button class="btn btn-ghost btn-sm" onclick="captureCitizenImage()">⊙ Capture</button>
              </div>
              <img id="citizenPreview" class="preview hidden" alt="Preview">
            </div>
            <div class="cam-panel">
              <div class="cam-title">// GPS Location</div>
              <div class="geo-text" id="geoCitizenText">// Not captured yet</div>
              <button class="btn btn-ghost btn-sm" onclick="captureCitizenGeo()" style="margin-top:8px;">◎ Capture GPS</button>
              <div style="margin-top:12px;font-size:11px;color:var(--text3);line-height:1.6;">GPS enables geo-aware civic stress mapping and location clustering algorithms.</div>
            </div>
          </div>
          <div style="margin-top:16px;">
            <button class="btn btn-success btn-full" onclick="submitIssue()">→ Submit Smart Issue Report</button>
          </div>
          <div id="citizenResult"></div>
        </div>
      </div>

      <!-- RIGHT -->
      <div style="display:flex;flex-direction:column;gap:18px;">
        <div class="card">
          <div class="card-title"><div class="dot" style="background:var(--blue);box-shadow:0 0 6px var(--blue);"></div>What Your Submission Triggers</div>
          <div class="trigger-list">
            <div class="trigger-row"><div class="tr-num">01</div><div class="tr-body"><div class="tr-title">Emotional Intensity Scaling</div><div class="tr-desc">NLP scans comment for urgency signals, caps usage, and emotional keywords — outputs 1–10 score.</div></div></div>
            <div class="trigger-row"><div class="tr-num">02</div><div class="tr-body"><div class="tr-title">Dual-Source Truth Engine</div><div class="tr-desc">Human perception fused with BLE, vibration, temp and Wi-Fi signals → validated anomaly score.</div></div></div>
            <div class="trigger-row"><div class="tr-num">03</div><div class="tr-body"><div class="tr-title">Predictive Civic Stress Mapping</div><div class="tr-desc">Historical clusters and current score predict if location is a rising or critical stress zone.</div></div></div>
            <div class="trigger-row"><div class="tr-num">04</div><div class="tr-body"><div class="tr-title">AI Department Assignment</div><div class="tr-desc">Keyword-driven AI routes the issue to the right department with an SLA timeline set automatically.</div></div></div>
            <div class="trigger-row"><div class="tr-num">05</div><div class="tr-body"><div class="tr-title">Autonomous Escalation</div><div class="tr-desc">Validated or repeated issues auto-escalate into the public accountability log instantly.</div></div></div>
          </div>
        </div>

        <div class="card">
          <div class="card-title"><div class="dot" style="background:var(--emerald);box-shadow:0 0 6px var(--emerald);"></div>Public Accountability Log</div>
          <div id="publicLogCitizen" class="log-list"><div style="color:var(--text3);font-size:12px;font-family:var(--mono);">// No actions recorded yet</div></div>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- ─── AUTHORITY ─── -->
<div id="pgAuthority" class="page">
  <div class="wrap">
    <div class="hero" style="padding:28px 36px;margin-bottom:22px;background:linear-gradient(130deg,#0c0a1e 0%,#16103a 50%,#0c0a1e 100%);">
      <div class="hero-glow" style="background:radial-gradient(circle,rgba(139,92,246,.15),transparent 70%);"></div>
      <div style="display:flex;justify-content:space-between;align-items:center;position:relative;">
        <div>
          <div class="hero-badge" style="background:rgba(139,92,246,.12);border-color:rgba(139,92,246,.2);color:var(--violet);">◆ Authority Command Center</div>
          <h1 style="font-size:26px;margin-top:4px;">Multi-Layer <span style="background:linear-gradient(90deg,var(--violet),var(--blue));-webkit-background-clip:text;-webkit-text-fill-color:transparent;">Civic Health</span> Dashboard</h1>
        </div>
        <button class="btn btn-ghost btn-sm" onclick="refreshAuthority()">↻ Refresh</button>
      </div>
    </div>

    <!-- STATS -->
    <div class="grid-4" style="margin-bottom:22px;">
      <div class="stat s-blue"><div class="stat-glow"></div><div class="stat-label">Open Issues</div><div class="stat-num" id="statOpen">0</div><div class="stat-sub">Active reports</div></div>
      <div class="stat s-rose"><div class="stat-glow"></div><div class="stat-label">Critical Zones</div><div class="stat-num" id="statCritical">0</div><div class="stat-sub">Stress: Critical</div></div>
      <div class="stat s-amber"><div class="stat-glow"></div><div class="stat-label">SLA at Risk</div><div class="stat-num" id="statSla">0</div><div class="stat-sub">Breach within 72h</div></div>
      <div class="stat s-em"><div class="stat-glow"></div><div class="stat-label">Avg Stress Score</div><div class="stat-num" id="statRisk">0</div><div class="stat-sub">Across open issues</div></div>
    </div>

    <div class="grid-2">
      <!-- LEFT COLUMN -->
      <div style="display:flex;flex-direction:column;gap:18px;">
        <div class="card">
          <div class="card-title"><div class="dot" style="background:var(--blue);box-shadow:0 0 6px var(--blue);"></div>Severity Distribution</div>
          <canvas id="severityChart" height="110"></canvas>
        </div>
        <div class="card">
          <div class="card-title"><div class="dot" style="background:var(--violet);box-shadow:0 0 6px var(--violet);"></div>Department Load</div>
          <canvas id="departmentChart" height="110"></canvas>
        </div>
        <div class="card">
          <div class="card-title"><div class="dot" style="background:var(--rose);box-shadow:0 0 6px var(--rose);"></div>Predictive Civic Stress Heatmap</div>
          <div id="heatmap"></div>
        </div>
        <div class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
            <div class="card-title" style="margin-bottom:0;"><div class="dot" style="background:var(--amber);box-shadow:0 0 6px var(--amber);"></div>Active Issue Queue</div>
            <span class="badge b-blue" id="issueCount">0 issues</span>
          </div>
          <div id="issueList" class="issue-scroll"><div style="color:var(--text3);font-size:12px;font-family:var(--mono);">// No issues yet</div></div>
        </div>
      </div>

      <!-- RIGHT COLUMN -->
      <div style="display:flex;flex-direction:column;gap:18px;">
        <div class="card">
          <div class="card-title"><div class="dot" style="background:var(--emerald);box-shadow:0 0 6px var(--emerald);"></div>Submit Proof-of-Resolution</div>
          <div class="form-section">
            <div class="form-section-title">Issue Identification</div>
            <div class="fg"><label>Issue ID</label><input id="resolveIssueId" type="number" placeholder="Enter issue ID to resolve"></div>
            <div class="fg"><label>Resolution Note</label><textarea id="resolutionNote" placeholder="Describe the action taken…"></textarea></div>
          </div>
          <div class="cam-panel">
            <div class="cam-title">// Proof Photo</div>
            <video id="authorityVideo" autoplay playsinline></video>
            <div class="cam-btns">
              <button class="btn btn-ghost btn-sm" onclick="startAuthorityCamera()">▶ Start</button>
              <button class="btn btn-ghost btn-sm" onclick="captureAuthorityImage()">⊙ Capture</button>
            </div>
            <img id="authorityPreview" class="preview hidden" alt="Proof">
          </div>
          <div class="cam-panel" style="margin-top:12px;">
            <div class="cam-title">// Officer Geolocation (Geo-Fenced)</div>
            <div class="geo-text" id="geoAuthorityText">// Location not captured</div>
            <button class="btn btn-ghost btn-sm" onclick="captureAuthorityGeo()" style="margin-top:8px;">◎ Capture Location</button>
          </div>
          <button class="btn btn-success btn-full" onclick="resolveIssue()" style="margin-top:16px;">✓ Submit Geo-Fenced Proof of Resolution</button>
          <div id="resolutionResult"></div>
        </div>

        <div class="card">
          <div class="card-title"><div class="dot" style="background:var(--cyan);box-shadow:0 0 6px var(--cyan);"></div>Public Accountability Log</div>
          <div id="publicLogAuthority" class="log-list"><div style="color:var(--text3);font-size:12px;font-family:var(--mono);">// No actions recorded yet</div></div>
        </div>
      </div>
    </div>
  </div>
</div>

<script>
let citizenImage='',authorityImage='',citizenGeo=null,authorityGeo=null;
let heatMapRef=null,mapRef=null,sevChart=null,deptChart=null,qrScanner=null,currentUser='';

(async()=>{
  const s=await fetch('/api/authority-status').then(r=>r.json());
  if(s.loggedIn){currentUser=s.username;buildUserBadge(s.username);}
})();

function buildUserBadge(u){
  const old=document.getElementById('userBadge');if(old)old.remove();
  const el=document.createElement('div');el.id='userBadge';el.className='t-user';
  el.innerHTML=`<div class="t-avatar">${u.slice(0,2).toUpperCase()}</div><span class="t-uname">${u}</span><button class="t-logout" onclick="doLogout()" title="Sign out">×</button>`;
  document.getElementById('tNav').appendChild(el);
}

async function doLogout(){
  await fetch('/api/authority-logout',{method:'POST'});
  currentUser='';const el=document.getElementById('userBadge');if(el)el.remove();goHome();
}

function setActivePage(id){
  document.querySelectorAll('.page').forEach(p=>{p.classList.remove('active');});
  document.getElementById(id).classList.add('active');
}
function setActiveNav(btn){
  document.querySelectorAll('.tnav-btn').forEach(b=>b.classList.remove('active'));
  if(btn)btn.classList.add('active');
}

function goHome(btn){setActivePage('pgLanding');setActiveNav(btn||document.querySelectorAll('.tnav-btn')[0]);stopQrScanner();}
function openCitizen(btn){setActivePage('pgCitizen');setActiveNav(btn||document.querySelectorAll('.tnav-btn')[1]);renderPublicLog('publicLogCitizen');startQrScanner();}

async function handleAuthorityNav(btn){
  const s=await fetch('/api/authority-status').then(r=>r.json());
  if(s.loggedIn){currentUser=s.username;buildUserBadge(s.username);openAuthority(btn);}
  else{window.location.href='/authority-login';}
}

async function openAuthority(btn){
  setActivePage('pgAuthority');setActiveNav(btn||document.querySelectorAll('.tnav-btn')[2]);stopQrScanner();
  await refreshAuthority();
}

function prefillDemo(){
  document.getElementById('location').value='canteen';
  document.getElementById('category').value='Cleanliness';
  document.getElementById('comment').value='Very bad garbage smell, unsafe crowding near canteen, urgent attention needed!';
  document.getElementById('mood').value='Frustrated';
  document.getElementById('cleanliness').value=1;document.getElementById('safety').value=2;
  document.getElementById('serviceQuality').value=2;document.getElementById('bluetoothDensity').value=8;
  document.getElementById('vibration').value=5;document.getElementById('temperatureDrift').value=4;
  document.getElementById('wifiFluctuation').value=7;
}

async function startCitizenCamera(){const s=await navigator.mediaDevices.getUserMedia({video:true});document.getElementById('citizenVideo').srcObject=s;}
function captureCitizenImage(){const v=document.getElementById('citizenVideo'),c=document.createElement('canvas');c.width=v.videoWidth||320;c.height=v.videoHeight||240;c.getContext('2d').drawImage(v,0,0);citizenImage=c.toDataURL('image/png');const img=document.getElementById('citizenPreview');img.src=citizenImage;img.classList.remove('hidden');}
async function captureCitizenGeo(){navigator.geolocation.getCurrentPosition(p=>{citizenGeo={lat:p.coords.latitude,lon:p.coords.longitude};document.getElementById('geoCitizenText').textContent=`// ${citizenGeo.lat.toFixed(5)}, ${citizenGeo.lon.toFixed(5)}`;},()=>{document.getElementById('geoCitizenText').textContent='// Permission denied — using mapped coords';});}
function moodToScore(m){return{'Calm':8,'Concerned':6,'Frustrated':4,'Angry':2,'Scared':1}[m]||5;}

async function submitIssue(){
  const payload={location:document.getElementById('location').value,category:document.getElementById('category').value,comment:document.getElementById('comment').value,mood:document.getElementById('mood').value,cleanliness:+document.getElementById('cleanliness').value,safety:+document.getElementById('safety').value,serviceQuality:+document.getElementById('serviceQuality').value,bluetoothDensity:+document.getElementById('bluetoothDensity').value,vibration:+document.getElementById('vibration').value,temperatureDrift:+document.getElementById('temperatureDrift').value,wifiFluctuation:+document.getElementById('wifiFluctuation').value,moodScore:moodToScore(document.getElementById('mood').value),image:citizenImage,citizenGeo};
  const res=await fetch('/api/issues',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const data=await res.json();const i=data.issue;
  const zoneClass=i.prediction.predictedZone==='Critical'?'b-rose':i.prediction.predictedZone==='Warning'?'b-amber':'b-em';
  const sevClass=i.severity==='Critical'?'b-rose':i.severity==='High'?'b-amber':i.severity==='Medium'?'b-violet':'b-em';
  document.getElementById('citizenResult').innerHTML=`
    <div class="result-card">
      <div class="result-title">✓ Issue Submitted — <span style="color:var(--cyan);font-family:var(--mono);">#${i.id}</span></div>
      <div class="tags-row">
        <span class="badge ${zoneClass}">${i.prediction.predictedZone} Zone</span>
        <span class="badge b-blue">${i.department}</span>
        <span class="badge ${sevClass}">${i.severity}</span>
        ${i.accountability.autoAssigned?'<span class="badge b-rose">Auto Escalated</span>':''}
      </div>
      <div class="result-grid">
        <div class="rg-item rg-blue"><div class="rg-label">Emotional Intensity</div><div class="rg-val">${i.feedback.emotionalIntensity}<small style="font-size:14px;">/10</small></div><div class="rg-sub">${i.feedback.sentimentLabel}</div></div>
        <div class="rg-item rg-cyan"><div class="rg-label">Fusion Score</div><div class="rg-val">${i.fusion.fusionScore}</div><div class="rg-sub">Conf: ${i.fusion.confidence}</div></div>
        <div class="rg-item rg-rose"><div class="rg-label">Stress Score</div><div class="rg-val">${i.prediction.predictedStressScore}</div><div class="rg-sub">Predicted</div></div>
        <div class="rg-item rg-amber"><div class="rg-label">SLA Risk</div><div class="rg-val" style="font-size:16px;">${i.slaPredictiveAlert.riskOfBreachWithin72Hours?'⚠ Risk':'✓ OK'}</div><div class="rg-sub">${i.slaPredictiveAlert.slaHours}h window</div></div>
      </div>
    </div>`;
  renderPublicLog('publicLogCitizen');
}

function renderPublicLog(id){
  fetch('/api/public-log').then(r=>r.json()).then(data=>{
    const el=document.getElementById(id);if(!el)return;
    el.innerHTML=data.length?data.slice().reverse().map(log=>`
      <div class="log-item ${log.action==='Auto Escalated'?'escalated':log.action.includes('Resolution')?'resolved':''}">
        <div class="li-action">Issue #${log.issueId} — ${log.action}</div>
        <div class="li-meta">${log.actor} · ${log.time}</div>
        <div class="li-note">${log.notes}</div>
      </div>`).join(''):'<div style="color:var(--text3);font-size:12px;font-family:var(--mono);">// No actions yet</div>';
  });
}

function startQrScanner(){
  if(!window.Html5QrcodeScanner)return;
  const r=document.getElementById('qr-reader');if(!r||r.dataset.started==='1')return;
  qrScanner=new Html5QrcodeScanner('qr-reader',{fps:10,qrbox:200},false);
  qrScanner.render(t=>{document.getElementById('location').value=t;},()=>{});
  r.dataset.started='1';
}
function stopQrScanner(){try{const r=document.getElementById('qr-reader');if(r&&r.dataset.started==='1'){r.innerHTML='';r.dataset.started='0';}}catch(e){}}

async function refreshAuthority(){
  const res=await fetch('/api/dashboard');
  if(res.status===401){window.location.href='/authority-login';return;}
  const data=await res.json();
  document.getElementById('statOpen').textContent=data.stats.openIssues;
  document.getElementById('statCritical').textContent=data.stats.criticalZones;
  document.getElementById('statSla').textContent=data.stats.slaRisks;
  document.getElementById('statRisk').textContent=data.stats.avgRisk;
  renderIssueList(data.issues);renderCharts(data);renderHeatmap(data.heatPoints);renderPublicLog('publicLogAuthority');
}

function renderIssueList(items){
  document.getElementById('issueCount').textContent=items.length+' issues';
  const host=document.getElementById('issueList');
  if(!items.length){host.innerHTML='<div style="color:var(--text3);font-size:12px;font-family:var(--mono);">// No issues yet</div>';return;}
  host.innerHTML=items.map(i=>{
    const sc=i.status==='Resolved'?'b-em':i.severity==='Critical'?'b-rose':i.severity==='High'?'b-amber':'b-blue';
    return`<div class="issue-item">
      <div class="ii-head">
        <div>
          <div class="ii-id">// Issue #${i.id} · ${i.createdAt}</div>
          <div class="ii-title">${i.category} — ${i.location}</div>
          <div class="ii-loc">Dept: ${i.department}</div>
        </div>
        <div style="display:flex;flex-direction:column;gap:5px;align-items:flex-end;">
          <span class="badge ${sc}">${i.status}</span>
          <span class="badge b-gray">${i.severity}</span>
        </div>
      </div>
      <div class="ii-body">${i.comment}</div>
      <div class="ii-chips">
        <div class="chip">intensity <b>${i.feedback.emotionalIntensity}/10</b></div>
        <div class="chip">fusion <b>${i.fusion.fusionScore}</b></div>
        <div class="chip">zone <b>${i.prediction.predictedZone}</b></div>
        <div class="chip">SLA <b>${i.slaPredictiveAlert.riskOfBreachWithin72Hours?'⚠ Risk':'✓ OK'}</b></div>
        ${i.accountability.autoAssigned?`<div class="chip" style="color:#fb7185;">🚨 Escalated</div>`:''}
      </div>
      ${i.resolution?`<div class="proof-box">✓ RESOLVED · Geo: ${i.resolution.geoVerified?'Verified':'Unverified'} · ${i.resolution.distanceMeters.toFixed(1)}m · ${i.resolution.note}</div>`:''}
      ${i.accountability.autoAssigned&&!i.resolution?`<div class="escalated-box">! Auto-escalated: ${i.accountability.reasons.join(' · ')}</div>`:''}
    </div>`;
  }).join('');
}

function renderCharts(data){
  const palette=['#3b82f6','#f43f5e','#f59e0b','#10b981','#8b5cf6','#22d3ee'];
  if(sevChart)sevChart.destroy();
  if(deptChart)deptChart.destroy();
  const chartDefaults={responsive:true,plugins:{legend:{display:false}},scales:{x:{grid:{color:'rgba(255,255,255,.04)'},ticks:{color:'#475569'}},y:{grid:{color:'rgba(255,255,255,.04)'},ticks:{color:'#475569'}}}};
  sevChart=new Chart(document.getElementById('severityChart'),{type:'bar',data:{labels:Object.keys(data.severityCounts),datasets:[{data:Object.values(data.severityCounts),backgroundColor:['#10b981','#f59e0b','#f97316','#f43f5e'],borderRadius:8,borderSkipped:false}]},options:{...chartDefaults,plugins:{legend:{display:false}}}});
  deptChart=new Chart(document.getElementById('departmentChart'),{type:'doughnut',data:{labels:Object.keys(data.departmentCounts),datasets:[{data:Object.values(data.departmentCounts),backgroundColor:palette,borderWidth:0,hoverOffset:6}]},options:{responsive:true,plugins:{legend:{position:'right',labels:{color:'#64748b',boxWidth:10,padding:12}}}}});
}

function renderHeatmap(points){
  if(!mapRef){
    mapRef=L.map('heatmap').setView([17.4442,78.3778],17);
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',{maxZoom:19,attribution:'© CartoDB'}).addTo(mapRef);
  }
  if(heatMapRef)mapRef.removeLayer(heatMapRef);
  heatMapRef=L.heatLayer(points.length?points:[[17.4442,78.3778,0.2]],{radius:28,blur:18,maxZoom:18,gradient:{0.4:'#3b82f6',0.65:'#f59e0b',1.0:'#f43f5e'}}).addTo(mapRef);
}

async function startAuthorityCamera(){const s=await navigator.mediaDevices.getUserMedia({video:true});document.getElementById('authorityVideo').srcObject=s;}
function captureAuthorityImage(){const v=document.getElementById('authorityVideo'),c=document.createElement('canvas');c.width=v.videoWidth||320;c.height=v.videoHeight||240;c.getContext('2d').drawImage(v,0,0);authorityImage=c.toDataURL('image/png');const img=document.getElementById('authorityPreview');img.src=authorityImage;img.classList.remove('hidden');}
async function captureAuthorityGeo(){navigator.geolocation.getCurrentPosition(p=>{authorityGeo={lat:p.coords.latitude,lon:p.coords.longitude};document.getElementById('geoAuthorityText').textContent=`// ${authorityGeo.lat.toFixed(5)}, ${authorityGeo.lon.toFixed(5)}`;},()=>{document.getElementById('geoAuthorityText').textContent='// Permission denied';});}

async function resolveIssue(){
  const res=await fetch('/api/resolve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({issueId:+document.getElementById('resolveIssueId').value,note:document.getElementById('resolutionNote').value,proofImage:authorityImage,authorityGeo})});
  if(res.status===401){window.location.href='/authority-login';return;}
  const data=await res.json();
  document.getElementById('resolutionResult').innerHTML=`
    <div style="margin-top:14px;" class="${data.geoVerified?'proof-box':'escalated-box'}">
      ${data.message} · Geo: ${data.geoVerified?'✓ Verified':'✗ Failed'} · Distance: ${data.distanceMeters?.toFixed(1)}m
    </div>`;
  await refreshAuthority();
}
</script>
</body>
</html>"""

if __name__=="__main__":
    app.run(debug=True)
