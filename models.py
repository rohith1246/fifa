import datetime
import logging
from typing import Dict, Any
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from database import Base, engine, SessionLocal

logger = logging.getLogger(__name__)


class User(Base):
    """
    SQLAlchemy database model representing a system user (Fan or Operations Staff).
    """

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(200), nullable=True)
    role = Column(String(50), nullable=False, default="fan")  # "fan" or "operations"
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    chats = relationship("ChatLog", back_populates="user", cascade="all, delete-orphan")

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the User model fields into a Python dictionary."""
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "created_at": self.created_at.isoformat(),
        }


class StadiumGate(Base):
    """
    SQLAlchemy database model representing a stadium gate's real-time telemetry.
    """

    __tablename__ = "stadium_gates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    capacity = Column(Integer, nullable=False, default=10000)
    queue_time = Column(
        Integer, nullable=False, default=10
    )  # Estimated wait time in minutes
    staff_count = Column(Integer, nullable=False, default=5)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    allocations = relationship(
        "StaffAllocation", back_populates="gate", cascade="all, delete-orphan"
    )

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the StadiumGate model fields into a Python dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "capacity": self.capacity,
            "queue_time": self.queue_time,
            "staff_count": self.staff_count,
            "created_at": self.created_at.isoformat(),
        }


class StaffAllocation(Base):
    """
    SQLAlchemy database model representing a staff re-allocation event.
    """

    __tablename__ = "staff_allocations"

    id = Column(Integer, primary_key=True, index=True)
    gate_id = Column(
        Integer,
        ForeignKey("stadium_gates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_gate = Column(String(100), nullable=False)
    quantity = Column(Integer, nullable=False)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    gate = relationship("StadiumGate", back_populates="allocations")

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the StaffAllocation model fields into a Python dictionary."""
        return {
            "id": self.id,
            "gate_id": self.gate_id,
            "from_gate": self.from_gate,
            "quantity": self.quantity,
            "reason": self.reason,
            "created_at": self.created_at.isoformat(),
        }


class Incident(Base):
    """
    SQLAlchemy database model representing reported stadium incidents.
    """

    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    category = Column(
        String(100), nullable=False
    )  # "medical", "security", "facilities"
    severity = Column(
        String(50), nullable=False, default="Low"
    )  # "Low", "Medium", "High"
    status = Column(
        String(50), nullable=False, default="Pending"
    )  # "Pending", "Dispatched", "Resolved"
    dispatch_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the Incident model fields into a Python dictionary."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "severity": self.severity,
            "status": self.status,
            "dispatch_notes": self.dispatch_notes,
            "created_at": self.created_at.isoformat(),
        }


class ChatLog(Base):
    """
    SQLAlchemy database model representing fan chatbot conversation history.
    """

    __tablename__ = "chat_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sender = Column(String(50), nullable=False, default="user")  # "user" or "assistant"
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="chats")

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the ChatLog model fields into a Python dictionary."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "sender": self.sender,
            "message": self.message,
            "created_at": self.created_at.isoformat(),
        }


def init_db() -> None:
    """
    Initializes the database schemas and executes baseline migrations.
    """
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        # Populate default gates if none exist to pre-configure World Cup operations simulation
        if db.query(StadiumGate).count() == 0:
            default_gates = [
                StadiumGate(
                    name="Gate A (East Concourse)",
                    capacity=15000,
                    queue_time=15,
                    staff_count=8,
                ),
                StadiumGate(
                    name="Gate B (South Concourse)",
                    capacity=20000,
                    queue_time=35,
                    staff_count=12,
                ),
                StadiumGate(
                    name="Gate C (West Concourse)",
                    capacity=12000,
                    queue_time=8,
                    staff_count=6,
                ),
                StadiumGate(
                    name="Gate D (VIP / North Concourse)",
                    capacity=5000,
                    queue_time=5,
                    staff_count=4,
                ),
            ]
            db.add_all(default_gates)
            db.commit()
            logger.info("Baseline World Cup stadium gates initialized.")
    except Exception as e:
        logger.error(f"Error during baseline seed initialization: {e}")
        db.rollback()
    finally:
        db.close()
