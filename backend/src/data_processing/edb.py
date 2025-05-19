# backend/src/db.py

from sqlalchemy import create_engine
from backend.src.models.events import Base  # adjust import based on how you run the app

engine = create_engine("sqlite:///events.db", echo=False)
Base.metadata.create_all(engine)
