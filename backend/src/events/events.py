from flask import Blueprint, request, jsonify
from sqlalchemy.orm import Session
from backend.src.data_processing.edb import engine
from backend.src.models.events import Anomaly, Note, Cleaning
from datetime import datetime, timedelta, timezone

events_bp = Blueprint("events", __name__)

@events_bp.route("/api/events/anomaly", methods=["POST"])
def create_anomaly():
    data = request.json
    with Session(engine) as session:
        anomaly = Anomaly(
            title=data["title"],
            start_time=data["start_time"],
            end_time=data.get("end_time"),
            note=data.get("note")
        )
        session.add(anomaly)
        session.commit()
        return jsonify({"status": "success", "uuid": anomaly.uuid}), 201

@events_bp.route("/api/events/note", methods=["POST"])
def create_note():
    data = request.json
    with Session(engine) as session:
        note = Note(
            title=data["title"],
            description=data["description"],
            timestamp=data.get("timestamp")
        )
        session.add(note)
        session.commit()
        return jsonify({"status": "success", "uid": note.uid}), 201

@events_bp.route("/api/events/cleaning", methods=["POST"])
def create_cleaning():
    data = request.json
    with Session(engine) as session:
        cleaning = Cleaning(
            note=data["note"],
            timestamp=data.get("timestamp")
        )
        session.add(cleaning)
        session.commit()
        return jsonify({"status": "success", "uid": cleaning.uid}), 201
    
@events_bp.route("/api/events/recent/24h", methods=["GET"])
def get_events_last_24h():
    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(hours=24)

    with Session(engine) as session:
        anomalies = session.query(Anomaly).filter(Anomaly.start_time >= yesterday).all()
        notes = session.query(Note).filter(Note.timestamp >= yesterday).all()
        cleanings = session.query(Cleaning).filter(Cleaning.timestamp >= yesterday).all()

        return jsonify({
            "anomalies": [a.to_dict() for a in anomalies],
            "notes": [n.to_dict() for n in notes],
            "cleanings": [c.to_dict() for c in cleanings],
        })

@events_bp.route("/api/events/recent/month", methods=["GET"])
def get_events_this_month():
    now = datetime.now(timezone.utc)
    start_of_month = datetime(now.year, now.month, 1)

    with Session(engine) as session:
        anomalies = session.query(Anomaly).filter(Anomaly.start_time >= start_of_month).all()
        notes = session.query(Note).filter(Note.timestamp >= start_of_month).all()
        cleanings = session.query(Cleaning).filter(Cleaning.timestamp >= start_of_month).all()

        return jsonify({
        "anomalies": [a.to_dict() for a in anomalies],
        "notes": [n.to_dict() for n in notes],
        "cleanings": [c.to_dict() for c in cleanings],
    })
