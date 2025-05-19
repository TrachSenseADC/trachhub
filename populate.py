import requests
import random
from datetime import datetime, timedelta, timezone

BASE_URL = "http://ad54-129-2-89-234.ngrok-free.app/api/events"  # change if needed

anomalies = [
    "breath.exe crashed",
    "snorezilla returns",
    "ghost breathing detected",
    "oxygen went AFK",
    "raspi panic attack",
    "air took a smoke break",
    "somehow louder than silence",
]

notes = [
    "Camera saw nothing unusual",
    "Breathing paused during sleep",
    "Device picked up random noise",
    "Operator confirmed no issue",
    "Filter might be loose",
    "Maybe the wind sneezed",
]

cleaning_notes = [
    "Cleaned with alcohol wipe",
    "Removed dust buildup",
    "Filter rinsed and dried",
    "Quick wipe, looked fine",
    "Cleaned again just in case",
]

def random_timestamp(within_days=30):
    now = datetime.now(timezone.utc)
    delta = timedelta(days=random.randint(0, within_days), hours=random.randint(0, 23), minutes=random.randint(0, 59))
    return (now - delta).isoformat()

def post_anomaly():
    start_dt = datetime.fromisoformat(random_timestamp(30))
    duration_minutes = random.randint(1, 15)
    end_dt = start_dt + timedelta(minutes=duration_minutes)

    duration = (end_dt - start_dt).total_seconds()
    compute_severity = lambda _, d: (
        "high" if d > 30 else "medium" if d > 10 else "low"
    )
    severity = compute_severity(None, duration)

    data = {
        "title": random.choice(anomalies),
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat(),
        "note": random.choice(notes),
        "duration": duration,
        "severity": severity
    }

    r = requests.post(f"{BASE_URL}/anomaly", json=data)
    try:
        print("Anomaly:", r.status_code, r.json())
    except Exception:
        print("Anomaly (non-JSON):", r.status_code, r.text)

def post_note():
    data = {
        "title": random.choice(["quick thought", "auto log", "manual check"]),
        "description": random.choice(notes),
        "timestamp": random_timestamp(30)
    }
    r = requests.post(f"{BASE_URL}/note", json=data)
    print("Note:", r.status_code, r.json())

def post_cleaning():
    data = {
        "note": random.choice(cleaning_notes),
        "timestamp": random_timestamp(30)
    }
    r = requests.post(f"{BASE_URL}/cleaning", json=data)
    print("Cleaning:", r.status_code, r.json())

def populate(n=10):
    for _ in range(n):
        post_anomaly()
        post_note()
        post_cleaning()

if __name__ == "__main__":
    populate(n=20)