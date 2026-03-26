from flask import Flask, request, jsonify, render_template_string, render_template, redirect, url_for, session
import math
import random
import datetime
from collections import Counter

app = Flask(__name__)
app.secret_key = "secret123"

# Authority credentials
USERNAME = "admin"
PASSWORD = "admin123"

# =========================
# IN-MEMORY DATA
# =========================
issues = []
public_log = []
next_issue_id = 1

DEPARTMENT_SLA_HOURS = {
    "Sanitation": 48,
    "Safety": 24,
    "Infrastructure": 72,
    "Utilities": 48,
    "Campus Services": 36,
    "General Administration": 60
}

DEPARTMENT_STAFF = {
    "Sanitation": 4,
    "Safety": 3,
    "Infrastructure": 3,
    "Utilities": 2,
    "Campus Services": 2,
    "General Administration": 2
}


# =========================
# AI / LOGIC HELPERS
# =========================
def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def parse_dt(s):
    return datetime.datetime.fromisoformat(s)


def hours_since(created_at):
    return (datetime.datetime.now() - parse_dt(created_at)).total_seconds() / 3600.0


def normalize_score(value, min_v, max_v):
    if max_v == min_v:
        return 0
    value = max(min_v, min(max_v, value))
    return (value - min_v) / (max_v - min_v)


def emotional_intensity_scale(text):
    """
    Automated Language-Based Emotional Intensity Scaling
    Returns 1-10 score.
    """
    if not text:
        return 1

    text_l = text.lower()

    strong_urgent = [
        "danger", "emergency", "urgent", "unsafe", "attack", "panic",
        "collapse", "critical", "help", "immediately", "severe"
    ]
    negative = [
        "bad", "dirty", "smell", "broken", "waste", "garbage", "leak",
        "unsafe", "fear", "dark", "crowded", "angry", "frustrated",
        "terrible", "awful", "failed", "damage", "crack", "noise"
    ]
    mild = ["okay", "average", "normal", "fine", "decent"]

    exclam = text.count("!")
    caps_words = sum(1 for w in text.split() if len(w) > 2 and w.isupper())

    score = 1
    score += sum(2 for w in strong_urgent if w in text_l)
    score += sum(1 for w in negative if w in text_l)
    score -= sum(1 for w in mild if w in text_l)
    score += min(2, exclam)
    score += min(2, caps_words)

    score = max(1, min(10, score))
    return score


def sentiment_label(score):
    if score >= 8:
        return "Highly Distressed"
    if score >= 6:
        return "Negative"
    if score >= 4:
        return "Concerned"
    return "Stable"


def ai_select_department(category, comment):
    """
    Departmental AI Select
    """
    category = (category or "").lower()
    comment_l = (comment or "").lower()

    if any(x in category or x in comment_l for x in ["garbage", "waste", "cleanliness", "smell"]):
        return "Sanitation"
    if any(x in category or x in comment_l for x in ["unsafe", "security", "fight", "harassment", "dark"]):
        return "Safety"
    if any(x in category or x in comment_l for x in ["road", "crack", "surface", "pothole", "bench", "structure", "vibration"]):
        return "Infrastructure"
    if any(x in category or x in comment_l for x in ["water", "leak", "electricity", "light", "temperature", "utility"]):
        return "Utilities"
    if any(x in category or x in comment_l for x in ["service", "queue", "canteen", "campus"]):
        return "Campus Services"
    return "General Administration"


def dual_source_truth_engine(feedback, sensor):
    """
    Dual-Source Truth Engine
    Fuses human feedback + ambient micro-signals.
    """
    rating_clean = feedback.get("cleanliness", 3)
    rating_safe = feedback.get("safety", 3)
    rating_service = feedback.get("service_quality", 3)
    mood_score = feedback.get("mood_score", 5)
    emotional_intensity = feedback.get("emotional_intensity", 5)

    ble_density = sensor.get("bluetoothDensity", 0)
    vibration = sensor.get("vibration", 0)
    temperature_drift = sensor.get("temperatureDrift", 0)
    wifi_fluctuation = sensor.get("wifiFluctuation", 0)

    human_anomaly = (
        (5 - rating_clean) * 10 +
        (5 - rating_safe) * 10 +
        (5 - rating_service) * 8 +
        emotional_intensity * 5 +
        (10 - mood_score) * 3
    )

    sensor_anomaly = (
        ble_density * 3 +
        vibration * 8 +
        temperature_drift * 6 +
        wifi_fluctuation * 5
    )

    fusion_score = round(min(100, (human_anomaly * 0.55) + (sensor_anomaly * 0.45)), 2)

    if human_anomaly > 35 and sensor_anomaly > 35:
        confidence = "High"
        validated = True
    elif human_anomaly > 25 or sensor_anomaly > 25:
        confidence = "Medium"
        validated = True
    else:
        confidence = "Low"
        validated = False

    hidden_issue_flag = sensor_anomaly > 45 and human_anomaly < 20
    likely_false_report = human_anomaly > 40 and sensor_anomaly < 10

    return {
        "humanAnomalyScore": round(human_anomaly, 2),
        "sensorAnomalyScore": round(sensor_anomaly, 2),
        "fusionScore": fusion_score,
        "validated": validated,
        "confidence": confidence,
        "hiddenIssueFlag": hidden_issue_flag,
        "likelyFalseReport": likely_false_report
    }


def predictive_civic_stress_map(location, emotional_intensity, fusion_score):
    """
    Predictive Civic Stress Mapping
    Simple predictive model based on historical issues around the same location.
    """
    same_loc = [i for i in issues if i["location"].strip().lower() == location.strip().lower()]
    hist_count = len(same_loc)
    unresolved_count = sum(1 for i in same_loc if i["status"] != "Resolved")

    avg_hist_score = 0
    if same_loc:
        avg_hist_score = sum(i["fusion"]["fusionScore"] for i in same_loc) / len(same_loc)

    predicted_stress = round(min(100,
        fusion_score * 0.55 +
        emotional_intensity * 4 +
        hist_count * 5 +
        unresolved_count * 8 +
        avg_hist_score * 0.2
    ), 2)

    if predicted_stress >= 80:
        zone = "Critical"
    elif predicted_stress >= 50:
        zone = "Warning"
    else:
        zone = "Normal"

    return {
        "predictedStressScore": predicted_stress,
        "predictedZone": zone,
        "historicalIssueCount": hist_count,
        "unresolvedNearbyCount": unresolved_count
    }


def issue_severity(fusion_score, emotional_intensity):
    s = fusion_score * 0.7 + emotional_intensity * 4
    if s >= 70:
        return "Critical"
    if s >= 45:
        return "High"
    if s >= 25:
        return "Medium"
    return "Low"


def auto_escalation(issue):
    """
    Autonomous Issue Escalation & Accountability Tracker
    """
    escalation_reason = []

    if issue["fusion"]["validated"]:
        escalation_reason.append("Sensor-verified or cross-validated anomaly")

    same_loc_unresolved = sum(
        1 for i in issues
        if i["location"].strip().lower() == issue["location"].strip().lower()
        and i["status"] != "Resolved"
    )
    if same_loc_unresolved >= 2:
        escalation_reason.append("Repeated issue in same location")

    if issue["severity"] in ["Critical", "High"]:
        escalation_reason.append("High severity")

    auto_assigned = len(escalation_reason) > 0

    return {
        "autoAssigned": auto_assigned,
        "reasons": escalation_reason,
        "slaHours": DEPARTMENT_SLA_HOURS.get(issue["department"], 48)
    }


def sla_predictive_alert(issue):
    """
    Departmental SLA Predictive Alert
    Predict likely breach 72 hours before expected breach.
    """
    created_hours = hours_since(issue["createdAt"])
    sla_hours = issue["accountability"]["slaHours"]

    dept = issue["department"]
    open_in_dept = [
        i for i in issues
        if i["department"] == dept and i["status"] != "Resolved"
    ]

    workload_factor = len(open_in_dept) / max(1, DEPARTMENT_STAFF.get(dept, 2))
    severity_factor = {"Low": 0.8, "Medium": 1.0, "High": 1.25, "Critical": 1.5}[issue["severity"]]

    estimated_resolution_hours = round(18 * severity_factor * max(1, workload_factor), 2)
    projected_total = created_hours + estimated_resolution_hours
    risk_of_breach = projected_total >= max(0, sla_hours - 72)

    return {
        "department": dept,
        "currentOpenLoad": len(open_in_dept),
        "availableStaff": DEPARTMENT_STAFF.get(dept, 2),
        "estimatedResolutionHoursFromNow": estimated_resolution_hours,
        "slaHours": sla_hours,
        "riskOfBreachWithin72Hours": risk_of_breach
    }


def add_public_log(issue_id, actor, action, notes):
    public_log.append({
        "issueId": issue_id,
        "actor": actor,
        "action": action,
        "notes": notes,
        "time": now_iso()
    })


def sample_coordinates_from_location(location):
    """
    Fallback location-to-coordinates mapper for demo.
    """
    base = {
        "main gate": (17.4435, 78.3772),
        "canteen": (17.4440, 78.3780),
        "library": (17.4446, 78.3777),
        "hostel": (17.4450, 78.3789),
        "parking": (17.4431, 78.3791),
        "block a": (17.4441, 78.3768),
        "block b": (17.4447, 78.3763)
    }
    key = (location or "").strip().lower()
    if key in base:
        return base[key]
    # random campus-ish coords
    return (
        round(17.443 + random.random() * 0.003, 6),
        round(78.376 + random.random() * 0.004, 6)
    )


def distance_meters(lat1, lon1, lat2, lon2):
    """
    Rough geo distance.
    """
    r = 6371000
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)

    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


# =========================
# SINGLE PAGE UI
# =========================
@app.route("/")
def index():
    return render_template_string("""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>CitiSense+ AURA</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />

  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <script src="https://unpkg.com/leaflet.heat/dist/leaflet-heat.js"></script>
  <script src="https://unpkg.com/html5-qrcode" type="text/javascript"></script>

  <style>
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, Arial, sans-serif;
      background: linear-gradient(135deg, #eef4ff, #f7fbff);
      color: #18202b;
    }
    .topbar {
      background: #0d1b3d;
      color: white;
      padding: 18px 26px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      box-shadow: 0 8px 20px rgba(0,0,0,0.14);
    }
    .brand {
      font-size: 24px;
      font-weight: 800;
      letter-spacing: 0.3px;
    }
    .brand small {
      display: block;
      font-size: 12px;
      opacity: 0.8;
      font-weight: 500;
      margin-top: 2px;
    }
    .container {
      max-width: 1400px;
      margin: 0 auto;
      padding: 24px;
    }
    .hero {
      background: linear-gradient(135deg, #16326f, #224ea8);
      color: white;
      border-radius: 24px;
      padding: 34px;
      box-shadow: 0 20px 50px rgba(34,78,168,0.22);
      margin-bottom: 24px;
    }
    .hero h1 {
      margin: 0 0 10px 0;
      font-size: 36px;
    }
    .hero p {
      margin: 0;
      max-width: 900px;
      line-height: 1.6;
      opacity: 0.95;
    }
    .role-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(280px, 1fr));
      gap: 22px;
      margin-top: 26px;
    }
    .role-card, .card {
      background: white;
      border-radius: 22px;
      padding: 22px;
      box-shadow: 0 10px 30px rgba(18, 45, 89, 0.08);
    }
    .role-card h2, .card h2, .card h3 {
      margin-top: 0;
      color: #143067;
    }
    .muted {
      color: #5e6b7d;
      font-size: 14px;
      line-height: 1.6;
    }
    .btn {
      border: none;
      border-radius: 14px;
      padding: 12px 18px;
      font-size: 14px;
      font-weight: 700;
      cursor: pointer;
      transition: 0.2s;
    }
    .btn:hover { transform: translateY(-1px); }
    .btn-primary {
      background: #1d4ed8;
      color: white;
    }
    .btn-secondary {
      background: #e9efff;
      color: #12306b;
    }
    .btn-danger {
      background: #dc2626;
      color: white;
    }
    .btn-success {
      background: #15803d;
      color: white;
    }
    .hidden { display: none; }
    .layout {
      display: grid;
      grid-template-columns: 1.1fr 0.9fr;
      gap: 22px;
      margin-top: 18px;
    }
    .two-col {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 14px;
    }
    label {
      display: block;
      font-size: 13px;
      margin: 10px 0 6px;
      color: #334155;
      font-weight: 600;
    }
    input, select, textarea {
      width: 100%;
      padding: 11px 12px;
      border-radius: 14px;
      border: 1px solid #d3deef;
      font-size: 14px;
      background: #fbfdff;
      outline: none;
    }
    textarea {
      min-height: 96px;
      resize: vertical;
    }
    .stat-row {
      display: grid;
      grid-template-columns: repeat(4, minmax(120px, 1fr));
      gap: 14px;
      margin-bottom: 16px;
    }
    .stat {
      background: linear-gradient(180deg, #f8fbff, #edf4ff);
      border-radius: 18px;
      padding: 16px;
      border: 1px solid #d8e6ff;
    }
    .stat .big {
      font-size: 28px;
      font-weight: 800;
      color: #133570;
    }
    .tag {
      display: inline-block;
      border-radius: 999px;
      padding: 6px 10px;
      font-size: 12px;
      font-weight: 700;
      margin-right: 6px;
      margin-top: 6px;
    }
    .tag-red { background: #fee2e2; color: #991b1b; }
    .tag-yellow { background: #fef3c7; color: #92400e; }
    .tag-green { background: #dcfce7; color: #166534; }
    .tag-blue { background: #dbeafe; color: #1d4ed8; }
    .issue-card {
      border: 1px solid #d7e5ff;
      border-radius: 18px;
      padding: 16px;
      margin-bottom: 14px;
      background: linear-gradient(180deg, #ffffff, #f8fbff);
    }
    .issue-head {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: start;
    }
    .small {
      font-size: 12px;
      color: #64748b;
    }
    .video-wrap, .qr-wrap {
      margin-top: 10px;
      padding: 10px;
      border-radius: 16px;
      background: #f8fbff;
      border: 1px solid #e0e9fb;
    }
    video, img.preview {
      width: 100%;
      max-width: 280px;
      border-radius: 16px;
      background: #111827;
    }
    #heatmap {
      height: 360px;
      width: 100%;
      border-radius: 18px;
      overflow: hidden;
      margin-top: 10px;
    }
    .accountability-log {
      max-height: 300px;
      overflow: auto;
      padding-right: 6px;
    }
    .log-item {
      border-left: 4px solid #1d4ed8;
      background: #f8fbff;
      padding: 10px 12px;
      border-radius: 0 12px 12px 0;
      margin-bottom: 10px;
    }
    .section-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-bottom: 10px;
    }
    .actions {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 12px;
    }
    .proof-box {
      background: #f9fbff;
      border: 1px dashed #bfd3ff;
      padding: 12px;
      border-radius: 16px;
      margin-top: 10px;
    }
    @media (max-width: 980px) {
      .layout, .role-grid, .two-col, .stat-row {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <div class="topbar">
    <div class="brand">
      CitiSense+ AURA
      <small>Unified Public-Space Intelligence Platform</small>
    </div>
    <div style="display:flex; gap:10px;">
    <button class="btn btn-secondary" onclick="goHome()">Home</button>
    <button class="btn btn-danger" onclick="logout()">Logout</button>
  </div>
</div>

  <div class="container">
    <div id="landing">
      <div class="hero">
        <h1>Top-Grade Civic Intelligence Project</h1>
        <p>
          CitiSense+ AURA combines citizen micro-feedback, ambient micro-signals,
          dual-source anomaly validation, predictive civic stress mapping, AI-based department assignment,
          autonomous escalation, SLA predictive alerts, proof-of-resolution verification,
          and a multi-layer governance dashboard in one unified system.
        </p>
      </div>

      <div class="role-grid">
        <div class="role-card">
          <h2>Citizen / Complaint Submitter</h2>
          <p class="muted">
            Submit QR-based feedback, ratings, comment, mood, camera proof, and sensor snapshot.
            The system fuses your perception with ambient signals to validate anomalies and detect hidden issues.
          </p>
          <button class="btn btn-primary" onclick="openCitizen()">Enter Citizen Portal</button>
        </div>

        <div class="role-card">
          <h2>Authority / Resolution Officer</h2>
          <p class="muted">
            Review live issues, predictive alerts, civic stress zones, heatmap layers, AI assignment,
            public accountability logs, and submit proof-of-resolution using geofenced verification.
          </p>
          <button class="btn btn-primary" onclick="openLogin()">Enter Authority Portal</button>
        </div>
      </div>
    </div>

    <div id="citizenView" class="hidden">
      <div class="hero">
        <h1>Citizen Portal</h1>
        <p>Submit smart QR micro-feedback with ratings, mood, comment, sensor snapshot, and image evidence.</p>
      </div>

      <div class="layout">
        <div>
          <div class="card">
            <div class="section-head">
              <h2>Smart QR Micro-Feedback + Sensor Snapshot Capture</h2>
              <span class="tag tag-blue">Citizen UI</span>
            </div>

            <div class="two-col">
              <div>
                <label>QR / Location Code Scan</label>
                <div class="qr-wrap">
                  <div id="qr-reader" style="width:100%; max-width:320px;"></div>
                  <div class="small">Or enter manually if scanning is not available.</div>
                </div>

                <label>Resolved Location / QR Value</label>
                <input id="location" placeholder="e.g. canteen / library / main gate" />

                <label>Issue Category</label>
                <select id="category">
                  <option>Cleanliness</option>
                  <option>Safety</option>
                  <option>Infrastructure</option>
                  <option>Utilities</option>
                  <option>Service Quality</option>
                  <option>General</option>
                </select>

                <label>Comment</label>
                <textarea id="comment" placeholder="Describe the problem clearly"></textarea>

                <label>Mood</label>
                <select id="mood">
                  <option>Calm</option>
                  <option>Concerned</option>
                  <option>Frustrated</option>
                  <option>Angry</option>
                  <option>Scared</option>
                </select>
              </div>

              <div>
                <label>Cleanliness Rating (1-5)</label>
                <input id="cleanliness" type="number" min="1" max="5" value="3" />

                <label>Safety Rating (1-5)</label>
                <input id="safety" type="number" min="1" max="5" value="3" />

                <label>Service Quality Rating (1-5)</label>
                <input id="serviceQuality" type="number" min="1" max="5" value="3" />

                <label>Bluetooth Device Density</label>
                <input id="bluetoothDensity" type="number" value="4" />

                <label>Vibration Level</label>
                <input id="vibration" type="number" value="2" />

                <label>Temperature Drift</label>
                <input id="temperatureDrift" type="number" value="1" />

                <label>Wi-Fi Fluctuation</label>
                <input id="wifiFluctuation" type="number" value="2" />
              </div>
            </div>

            <div class="two-col" style="margin-top:10px;">
              <div class="video-wrap">
                <h3>Camera Evidence</h3>
                <video id="citizenVideo" autoplay playsinline></video>
                <div class="actions">
                  <button class="btn btn-secondary" onclick="startCitizenCamera()">Start Camera</button>
                  <button class="btn btn-primary" onclick="captureCitizenImage()">Capture Image</button>
                </div>
                <img id="citizenPreview" class="preview hidden" alt="Captured preview" />
              </div>

              <div class="video-wrap">
                <h3>Citizen Geolocation</h3>
                <div class="small" id="geoCitizenText">Location not captured yet.</div>
                <div class="actions">
                  <button class="btn btn-secondary" onclick="captureCitizenGeo()">Capture My Location</button>
                </div>
                <div class="proof-box">
                  This supports geo-aware civic stress mapping and issue clustering.
                </div>
              </div>
            </div>

            <div class="actions">
              <button class="btn btn-success" onclick="submitIssue()">Submit Smart Issue</button>
              <button class="btn btn-secondary" onclick="prefillDemo()">Load Demo Data</button>
            </div>

            <div id="citizenResult" style="margin-top:16px;"></div>
          </div>
        </div>

        <div>
          <div class="card">
            <h2>What this submission triggers</h2>
            <div class="muted">
              <p><b>1.</b> Automated language-based emotional intensity scaling (1-10)</p>
              <p><b>2.</b> Dual-Source Truth Engine validates citizen perception with sensor signals</p>
              <p><b>3.</b> Predictive civic stress scoring forecasts emerging stress zones</p>
              <p><b>4.</b> AI selects department and SLA timeline</p>
              <p><b>5.</b> If repeated or validated, the issue is auto-escalated into public accountability flow</p>
            </div>
          </div>

          <div class="card">
            <h2>Recent Public Accountability Log</h2>
            <div id="publicLogCitizen" class="accountability-log"></div>
          </div>
        </div>
      </div>
    </div>

    <div id="authorityView" class="hidden">
      <div class="hero">
        <h1>Authority Portal</h1>
        <p>Resolve issues, monitor civic stress, review predictive alerts, and upload proof-of-resolution with geofenced verification.</p>
      </div>

      <div class="stat-row">
        <div class="stat"><div class="small">Open Issues</div><div class="big" id="statOpen">0</div></div>
        <div class="stat"><div class="small">Critical Zones</div><div class="big" id="statCritical">0</div></div>
        <div class="stat"><div class="small">Likely SLA Breaches</div><div class="big" id="statSla">0</div></div>
        <div class="stat"><div class="small">Avg Satisfaction Risk</div><div class="big" id="statRisk">0</div></div>
      </div>

      <div class="layout">
        <div>
          <div class="card">
            <div class="section-head">
              <h2>Multi-Layer Civic Health Dashboard</h2>
              <div class="actions">
                <button class="btn btn-secondary" onclick="refreshAuthority()">Refresh</button>
              </div>
            </div>

            <canvas id="severityChart" height="110"></canvas>
            <canvas id="departmentChart" height="110" style="margin-top:18px;"></canvas>

            <h3 style="margin-top:20px;">Predictive Civic Stress Heat Map</h3>
            <div id="heatmap"></div>
          </div>

          <div class="card" style="margin-top:18px;">
            <h2>Autonomous Issue Escalation & Accountability Tracker</h2>
            <div id="issueList"></div>
          </div>
        </div>

        <div>
          <div class="card">
            <h2>Proof-of-Resolution Geo-Fenced Verification</h2>

            <label>Issue ID</label>
            <input id="resolveIssueId" type="number" placeholder="Enter issue id" />

            <label>Resolution Note</label>
            <textarea id="resolutionNote" placeholder="Explain what action was taken"></textarea>

            <div class="video-wrap">
              <h3>Authority Camera Proof</h3>
              <video id="authorityVideo" autoplay playsinline></video>
              <div class="actions">
                <button class="btn btn-secondary" onclick="startAuthorityCamera()">Start Camera</button>
                <button class="btn btn-primary" onclick="captureAuthorityImage()">Capture Proof</button>
              </div>
              <img id="authorityPreview" class="preview hidden" alt="Resolution proof" />
            </div>

            <div class="video-wrap">
              <h3>Authority Geolocation</h3>
              <div class="small" id="geoAuthorityText">Location not captured yet.</div>
              <div class="actions">
                <button class="btn btn-secondary" onclick="captureAuthorityGeo()">Capture Officer Location</button>
              </div>
            </div>

            <div class="actions">
              <button class="btn btn-success" onclick="resolveIssue()">Submit Proof-of-Resolution</button>
            </div>

            <div id="resolutionResult" style="margin-top:14px;"></div>
          </div>

          <div class="card" style="margin-top:18px;">
            <h2>Public Accountability Log</h2>
            <div id="publicLogAuthority" class="accountability-log"></div>
          </div>
        </div>
      </div>
    </div>
  </div>

<div id="loginView" class="hidden">
  <div class="hero">
    <h1>Authority Login</h1>
    <p>Login to access dashboard</p>
  </div>

  <div class="card" style="max-width:400px;margin:auto;">
    <label>Username</label>
    <input id="loginUsername" placeholder="Enter username">

    <label>Password</label>
    <input id="loginPassword" type="password" placeholder="Enter password">

    <div class="actions">
      <button class="btn btn-primary" onclick="login()">Login</button>
    </div>

    <div id="loginResult" style="margin-top:10px;"></div>
  </div>
</div>

  <script>

    let citizenImage = "";
    let authorityImage = "";
    let citizenGeo = null;
    let authorityGeo = null;
    let heatMapRef = null;
    let mapRef = null;
    let severityChartRef = null;
    let departmentChartRef = null;
    let qrScanner = null;

   function openLogin() {
    document.getElementById("landing").classList.add("hidden");
    document.getElementById("citizenView").classList.add("hidden");
    document.getElementById("authorityView").classList.add("hidden");
    document.getElementById("loginView").classList.remove("hidden");
  }

  async function login() {
   const username = document.getElementById("loginUsername").value;
   const password = document.getElementById("loginPassword").value;

   const res = await fetch("/login", {
  method: "POST",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify({username, password}),
  credentials: "same-origin"
});
   const data = await res.json();

   if (res.status === 200) {
     document.getElementById("loginResult").innerHTML =
       "<span style='color:green'>Login successful</span>";
     openAuthority();
   } else {
     document.getElementById("loginResult").innerHTML =
       "<span style='color:red'>Invalid credentials</span>";
   }
 }
async function logout() {
  await fetch("/logout", {
    credentials: "same-origin"
  });
  location.reload(); // go back to home page
}
    function goHome() {
      document.getElementById("landing").classList.remove("hidden");
      document.getElementById("citizenView").classList.add("hidden");
      document.getElementById("authorityView").classList.add("hidden");
      stopQrScanner();
    }

    function openCitizen() {
      document.getElementById("landing").classList.add("hidden");
      document.getElementById("citizenView").classList.remove("hidden");
      document.getElementById("authorityView").classList.add("hidden");
      renderPublicLog("publicLogCitizen");
      startQrScanner();
    }

     async function openAuthority() {
  const res = await fetch("/api/dashboard", {
    credentials: "same-origin"
  });

  if (res.status === 401) {
    alert("Please login first");
    openLogin();
    return;
  }

  document.getElementById("landing").classList.add("hidden");
  document.getElementById("citizenView").classList.add("hidden");
  document.getElementById("authorityView").classList.remove("hidden");

  await refreshAuthority();
}

    function prefillDemo() {
      document.getElementById("location").value = "canteen";
      document.getElementById("category").value = "Cleanliness";
      document.getElementById("comment").value = "Very bad garbage smell, unsafe crowding near canteen, urgent attention needed!";
      document.getElementById("mood").value = "Frustrated";
      document.getElementById("cleanliness").value = 1;
      document.getElementById("safety").value = 2;
      document.getElementById("serviceQuality").value = 2;
      document.getElementById("bluetoothDensity").value = 8;
      document.getElementById("vibration").value = 5;
      document.getElementById("temperatureDrift").value = 4;
      document.getElementById("wifiFluctuation").value = 7;
    }

    async function startCitizenCamera() {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true });
      document.getElementById("citizenVideo").srcObject = stream;
    }

    function captureCitizenImage() {
      const video = document.getElementById("citizenVideo");
      const canvas = document.createElement("canvas");
      canvas.width = video.videoWidth || 320;
      canvas.height = video.videoHeight || 240;
      const ctx = canvas.getContext("2d");
      ctx.drawImage(video, 0, 0);
      citizenImage = canvas.toDataURL("image/png");
      const img = document.getElementById("citizenPreview");
      img.src = citizenImage;
      img.classList.remove("hidden");
    }

    async function captureCitizenGeo() {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          citizenGeo = {
            lat: pos.coords.latitude,
            lon: pos.coords.longitude
          };
          document.getElementById("geoCitizenText").innerText =
            `Captured: ${citizenGeo.lat.toFixed(5)}, ${citizenGeo.lon.toFixed(5)}`;
        },
        () => {
          document.getElementById("geoCitizenText").innerText =
            "Permission denied. The system will use mapped campus coordinates.";
        }
      );
    }

    function moodToScore(mood) {
      const map = {
        "Calm": 8,
        "Concerned": 6,
        "Frustrated": 4,
        "Angry": 2,
        "Scared": 1
      };
      return map[mood] || 5;
    }

    async function submitIssue() {
      const payload = {
        location: document.getElementById("location").value,
        category: document.getElementById("category").value,
        comment: document.getElementById("comment").value,
        mood: document.getElementById("mood").value,
        cleanliness: Number(document.getElementById("cleanliness").value),
        safety: Number(document.getElementById("safety").value),
        serviceQuality: Number(document.getElementById("serviceQuality").value),
        bluetoothDensity: Number(document.getElementById("bluetoothDensity").value),
        vibration: Number(document.getElementById("vibration").value),
        temperatureDrift: Number(document.getElementById("temperatureDrift").value),
        wifiFluctuation: Number(document.getElementById("wifiFluctuation").value),
        moodScore: moodToScore(document.getElementById("mood").value),
        image: citizenImage,
        citizenGeo: citizenGeo
      };

      const res = await fetch("/api/issues", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload)
      });

      const data = await res.json();

      document.getElementById("citizenResult").innerHTML = `
        <div class="issue-card">
          <div class="issue-head">
            <div>
              <h3>Issue Submitted Successfully</h3>
              <div class="small">Issue ID: ${data.issue.id}</div>
            </div>
            <div>
              <span class="tag ${data.issue.prediction.predictedZone === "Critical" ? "tag-red" : data.issue.prediction.predictedZone === "Warning" ? "tag-yellow" : "tag-green"}">${data.issue.prediction.predictedZone}</span>
              <span class="tag tag-blue">${data.issue.department}</span>
            </div>
          </div>
          <p><b>Emotional Intensity:</b> ${data.issue.feedback.emotionalIntensity}/10 (${data.issue.feedback.sentimentLabel})</p>
          <p><b>Dual-Source Fusion Score:</b> ${data.issue.fusion.fusionScore}</p>
          <p><b>Validated:</b> ${data.issue.fusion.validated ? "Yes" : "No"} | <b>Confidence:</b> ${data.issue.fusion.confidence}</p>
          <p><b>Predicted Stress Score:</b> ${data.issue.prediction.predictedStressScore}</p>
          <p><b>Auto Escalated:</b> ${data.issue.accountability.autoAssigned ? "Yes" : "No"}</p>
          <p><b>SLA Alert Risk:</b> ${data.issue.slaPredictiveAlert.riskOfBreachWithin72Hours ? "Likely" : "Not Likely"}</p>
        </div>
      `;
      renderPublicLog("publicLogCitizen");
    }

    function renderPublicLog(targetId) {
      fetch("/api/public-log")
        .then(r => r.json())
        .then(data => {
          const el = document.getElementById(targetId);
          if (!el) return;
          el.innerHTML = data.length ? data.slice().reverse().map(log => `
            <div class="log-item">
              <div><b>Issue #${log.issueId}</b> — ${log.action}</div>
              <div class="small">${log.actor} • ${log.time}</div>
              <div>${log.notes}</div>
            </div>
          `).join("") : "<div class='muted'>No public actions yet.</div>";
        });
    }

    function startQrScanner() {
      if (!window.Html5QrcodeScanner) return;
      const region = document.getElementById("qr-reader");
      if (!region || region.dataset.started === "1") return;

      qrScanner = new Html5QrcodeScanner("qr-reader", { fps: 10, qrbox: 220 }, false);
      qrScanner.render(
        (decodedText) => {
          document.getElementById("location").value = decodedText;
        },
        () => {}
      );
      region.dataset.started = "1";
    }

    function stopQrScanner() {
      try {
        const region = document.getElementById("qr-reader");
        if (region && region.dataset.started === "1") {
          region.innerHTML = "";
          region.dataset.started = "0";
        }
      } catch (e) {}
    }

    async function refreshAuthority() {
      const res = await fetch("/api/dashboard", { credentials: "same-origin" })
      const data = await res.json();

      document.getElementById("statOpen").innerText = data.stats.openIssues;
      document.getElementById("statCritical").innerText = data.stats.criticalZones;
      document.getElementById("statSla").innerText = data.stats.slaRisks;
      document.getElementById("statRisk").innerText = data.stats.avgRisk;

      renderIssueList(data.issues);
      renderCharts(data);
      renderHeatmap(data.heatPoints);
      renderPublicLog("publicLogAuthority");
    }

    function renderIssueList(items) {
      const host = document.getElementById("issueList");
      host.innerHTML = items.length ? items.map(i => `
        <div class="issue-card">
          <div class="issue-head">
            <div>
              <h3>#${i.id} — ${i.category}</h3>
              <div class="small">${i.location} • Created: ${i.createdAt}</div>
            </div>
            <div>
              <span class="tag ${i.status === "Resolved" ? "tag-green" : i.severity === "Critical" ? "tag-red" : i.severity === "High" ? "tag-yellow" : "tag-blue"}">${i.status}</span>
              <span class="tag tag-blue">${i.department}</span>
            </div>
          </div>

          <p><b>Comment:</b> ${i.comment}</p>
          <p><b>Emotional Intensity:</b> ${i.feedback.emotionalIntensity}/10</p>
          <p><b>Dual Source Fusion:</b> ${i.fusion.fusionScore} | <b>Validated:</b> ${i.fusion.validated ? "Yes" : "No"}</p>
          <p><b>Predicted Zone:</b> ${i.prediction.predictedZone} | <b>Stress Score:</b> ${i.prediction.predictedStressScore}</p>
          <p><b>Severity:</b> ${i.severity}</p>
          <p><b>Escalation:</b> ${i.accountability.autoAssigned ? i.accountability.reasons.join(", ") : "Not escalated"}</p>
          <p><b>SLA Predictive Alert:</b> ${i.slaPredictiveAlert.riskOfBreachWithin72Hours ? "Risk within 72 hours" : "Stable"} | Open load: ${i.slaPredictiveAlert.currentOpenLoad}</p>

          ${i.resolution ? `
            <div class="proof-box">
              <b>Proof-of-Resolution:</b><br>
              Verified: ${i.resolution.geoVerified ? "Yes" : "No"}<br>
              Distance from issue: ${i.resolution.distanceMeters.toFixed(1)} m<br>
              Note: ${i.resolution.note}
            </div>
          ` : ""}
        </div>
      `).join("") : "<div class='muted'>No issues available.</div>";
    }

    function renderCharts(data) {
      const sevCtx = document.getElementById("severityChart");
      const depCtx = document.getElementById("departmentChart");

      if (severityChartRef) severityChartRef.destroy();
      if (departmentChartRef) departmentChartRef.destroy();

      severityChartRef = new Chart(sevCtx, {
        type: "bar",
        data: {
          labels: Object.keys(data.severityCounts),
          datasets: [{
            label: "Severity Distribution",
            data: Object.values(data.severityCounts)
          }]
        },
        options: { responsive: true, plugins: { legend: { display: false } } }
      });

      departmentChartRef = new Chart(depCtx, {
        type: "doughnut",
        data: {
          labels: Object.keys(data.departmentCounts),
          datasets: [{
            label: "Department Load",
            data: Object.values(data.departmentCounts)
          }]
        },
        options: { responsive: true }
      });
    }

    function renderHeatmap(points) {
      if (!mapRef) {
        mapRef = L.map('heatmap').setView([17.4442, 78.3778], 17);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
          maxZoom: 19,
          attribution: '&copy; OpenStreetMap'
        }).addTo(mapRef);
      }

      if (heatMapRef) {
        mapRef.removeLayer(heatMapRef);
      }

      heatMapRef = L.heatLayer(points.length ? points : [[17.4442, 78.3778, 0.2]], {
        radius: 28,
        blur: 18,
        maxZoom: 18
      }).addTo(mapRef);
    }

    async function startAuthorityCamera() {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true });
      document.getElementById("authorityVideo").srcObject = stream;
    }

    function captureAuthorityImage() {
      const video = document.getElementById("authorityVideo");
      const canvas = document.createElement("canvas");
      canvas.width = video.videoWidth || 320;
      canvas.height = video.videoHeight || 240;
      const ctx = canvas.getContext("2d");
      ctx.drawImage(video, 0, 0);
      authorityImage = canvas.toDataURL("image/png");
      const img = document.getElementById("authorityPreview");
      img.src = authorityImage;
      img.classList.remove("hidden");
    }

    async function captureAuthorityGeo() {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          authorityGeo = {
            lat: pos.coords.latitude,
            lon: pos.coords.longitude
          };
          document.getElementById("geoAuthorityText").innerText =
            `Captured: ${authorityGeo.lat.toFixed(5)}, ${authorityGeo.lon.toFixed(5)}`;
        },
        () => {
          document.getElementById("geoAuthorityText").innerText =
            "Permission denied. Resolution verification may fail without live geo.";
        }
      );
    }

    async function resolveIssue() {
      const payload = {
        issueId: Number(document.getElementById("resolveIssueId").value),
        note: document.getElementById("resolutionNote").value,
        proofImage: authorityImage,
        authorityGeo: authorityGeo
      };

        const res = await fetch("/api/resolve", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify(payload),   // ← comma needed
          credentials: "same-origin"
        });
      const data = await res.json();
      document.getElementById("resolutionResult").innerHTML = `
        <div class="issue-card">
          <h3>${data.message}</h3>
          ${data.geoVerified !== undefined ? `<p><b>Geo Verified:</b> ${data.geoVerified ? "Yes" : "No"}</p>` : ""}
          ${data.distanceMeters !== undefined ? `<p><b>Distance:</b> ${data.distanceMeters.toFixed(1)} m</p>` : ""}
        </div>
      `;
      await refreshAuthority();
    }
  </script>
</body>
</html>
    """)


# =========================
# APIs
# =========================
@app.route("/api/issues", methods=["POST"])
def create_issue():
    global next_issue_id

    data = request.get_json(force=True)

    location = data.get("location", "").strip()
    category = data.get("category", "General").strip()
    comment = data.get("comment", "").strip()
    mood = data.get("mood", "Concerned")
    cleanliness = int(data.get("cleanliness", 3))
    safety = int(data.get("safety", 3))
    service_quality = int(data.get("serviceQuality", 3))
    mood_score = int(data.get("moodScore", 5))

    bluetooth_density = float(data.get("bluetoothDensity", 0))
    vibration = float(data.get("vibration", 0))
    temperature_drift = float(data.get("temperatureDrift", 0))
    wifi_fluctuation = float(data.get("wifiFluctuation", 0))

    citizen_geo = data.get("citizenGeo")
    image = data.get("image", "")

    emotional_intensity = emotional_intensity_scale(comment)

    feedback = {
        "cleanliness": cleanliness,
        "safety": safety,
        "service_quality": service_quality,
        "mood": mood,
        "mood_score": mood_score,
        "emotionalIntensity": emotional_intensity,
        "sentimentLabel": sentiment_label(emotional_intensity)
    }

    sensor = {
        "bluetoothDensity": bluetooth_density,
        "vibration": vibration,
        "temperatureDrift": temperature_drift,
        "wifiFluctuation": wifi_fluctuation
    }

    fusion = dual_source_truth_engine(
        {
            "cleanliness": cleanliness,
            "safety": safety,
            "service_quality": service_quality,
            "mood_score": mood_score,
            "emotional_intensity": emotional_intensity
        },
        sensor
    )

    prediction = predictive_civic_stress_map(location, emotional_intensity, fusion["fusionScore"])
    department = ai_select_department(category, comment)
    severity = issue_severity(fusion["fusionScore"], emotional_intensity)

    lat, lon = sample_coordinates_from_location(location)
    if citizen_geo and "lat" in citizen_geo and "lon" in citizen_geo:
        lat, lon = citizen_geo["lat"], citizen_geo["lon"]

    issue = {
        "id": next_issue_id,
        "category": category,
        "location": location,
        "comment": comment,
        "feedback": feedback,
        "sensor": sensor,
        "fusion": fusion,
        "prediction": prediction,
        "department": department,
        "severity": severity,
        "status": "Open",
        "createdAt": now_iso(),
        "lat": lat,
        "lon": lon,
        "image": image,
        "resolution": None
    }

    issue["accountability"] = auto_escalation(issue)
    issue["slaPredictiveAlert"] = sla_predictive_alert(issue)

    issues.append(issue)
    next_issue_id += 1

    add_public_log(
        issue["id"],
        "System",
        "Issue Registered",
        f"Issue created for {issue['location']} and assigned to {issue['department']}."
    )

    if issue["accountability"]["autoAssigned"]:
        add_public_log(
            issue["id"],
            "System",
            "Auto Escalated",
            "; ".join(issue["accountability"]["reasons"])
        )

    return jsonify({
        "message": "Issue submitted successfully",
        "issue": issue
    })


@app.route("/api/dashboard", methods=["GET"])
def dashboard():
    if not session.get('authority_logged_in'):
        return jsonify({"error": "Unauthorized"}), 401

    open_issues = [i for i in issues if i["status"] != "Resolved"]
    critical_zones = sum(1 for i in open_issues if i["prediction"]["predictedZone"] == "Critical")
    sla_risks = sum(1 for i in open_issues if i["slaPredictiveAlert"]["riskOfBreachWithin72Hours"])

    avg_risk = 0
    if open_issues:
        avg_risk = round(sum(i["prediction"]["predictedStressScore"] for i in open_issues) / len(open_issues), 1)

    severity_counts = Counter(i["severity"] for i in issues)
    department_counts = Counter(i["department"] for i in issues)

    heat_points = [
        [i["lat"], i["lon"], max(0.15, min(1.0, i["prediction"]["predictedStressScore"] / 100.0))]
        for i in issues
    ]

    return jsonify({
        "stats": {
            "openIssues": len(open_issues),
            "criticalZones": critical_zones,
            "slaRisks": sla_risks,
            "avgRisk": avg_risk
        },
        "severityCounts": dict(severity_counts),
        "departmentCounts": dict(department_counts),
        "heatPoints": heat_points,
        "issues": issues
    })


@app.route("/api/public-log", methods=["GET"])
def get_public_log():
    return jsonify(public_log)


@app.route("/api/resolve", methods=["POST"])
def resolve_issue():
    if not session.get('authority_logged_in'):
     return jsonify({"error": "Unauthorized"}), 401
  
    data = request.get_json(force=True)

    issue_id = int(data.get("issueId", 0))
    note = data.get("note", "").strip()
    proof_image = data.get("proofImage", "")
    authority_geo = data.get("authorityGeo")

    issue = next((i for i in issues if i["id"] == issue_id), None)
    if not issue:
        return jsonify({"message": "Issue not found"}), 404

    if not authority_geo or "lat" not in authority_geo or "lon" not in authority_geo:
        return jsonify({"message": "Authority geolocation is required for proof-of-resolution"}), 400

    dist = distance_meters(
        issue["lat"], issue["lon"],
        authority_geo["lat"], authority_geo["lon"]
    )

    geo_verified = dist <= 120.0

    issue["status"] = "Resolved" if geo_verified else "Resolution Pending Verification"

    issue["resolution"] = {
        "note": note,
        "proofImage": proof_image,
        "authorityGeo": authority_geo,
        "distanceMeters": dist,
        "geoVerified": geo_verified,
        "resolvedAt": now_iso()
    }		

    add_public_log(
        issue["id"],
        "Authority",
        "Proof of Resolution Submitted",
        f"Geo verified: {'Yes' if geo_verified else 'No'}; Distance: {round(dist, 1)} m."
    )

    return jsonify({
        "message": "Resolution submitted",
        "geoVerified": geo_verified,
        "distanceMeters": dist,
        "issue": issue
    })

# =========================
# RUN
# =========================


# =========================
# AUTH ROUTES
# =========================

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")

    if username == USERNAME and password == PASSWORD:
        session['authority_logged_in'] = True
        return jsonify({"message": "Login successful"})
    else:
        return jsonify({"message": "Invalid credentials"}), 401


@app.route("/logout")
def logout():
    session.pop('authority_logged_in', None)
    return redirect("/")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)




