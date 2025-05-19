from sqlalchemy import Column, String, DateTime, Text, Float
from sqlalchemy.orm import declarative_base
import uuid
from datetime import datetime, timezone

Base = declarative_base()

def generate_uuid():
    return str(uuid.uuid4())

class Anomaly(Base):
    __tablename__ = "anomalies"
    uuid = Column(String(36), primary_key=True, default=generate_uuid)
    title = Column(String(100), nullable=False)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime)
    note = Column(Text)
    duration = Column(Float)           # duration in seconds
    severity = Column(String(10))

    def to_dict(self):
        return {
            "uuid": self.uuid,
            "title": self.title,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "note": self.note,
            "duration": self.duration, 
            "severity": self.severity
        }

class Note(Base):
    __tablename__ = "notes"
    uid = Column(String(36), primary_key=True, default=generate_uuid)
    title = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "uid": self.uid,
            "title": self.title,
            "description": self.description,
            "timestamp": self.timestamp.isoformat()
        }
    

class Cleaning(Base):
    __tablename__ = "cleanings"
    uid = Column(String(36), primary_key=True, default=generate_uuid)
    note = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.now(timezone.utc))

    def to_dict(self): 
        return {
            "uid": self.uid,
            "note": self.note,
            "timestamp": self.timestamp.isoformat()
        }
