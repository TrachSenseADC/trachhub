import requests
import random
from datetime import datetime, timedelta, timezone

BASE_URL = "http://127.0.0.1:5000/api/events"  # change if needed

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
    start = random_timestamp(30)
    end = (datetime.fromisoformat(start) + timedelta(minutes=random.randint(1, 15))).isoformat()
    data = {
        "title": random.choice(anomalies),
        "start_time": start,
        "end_time": end,
        "note": random.choice(notes)
    }
    r = requests.post(f"{BASE_URL}/anomaly", json=data)
    print("Anomaly:", r.status_code, r.json())

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
