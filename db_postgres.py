"""
Postgres database layer using SQLAlchemy.
Replaces db.py (SQLite) with Neon Postgres.
"""
import os
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

import secrets
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Date,
    DateTime,
    Boolean,
    ForeignKey,
    Index,
    UniqueConstraint,
    text,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from sqlalchemy.pool import QueuePool

Base = declarative_base()


# SQLAlchemy Models
class Department(Base):
    __tablename__ = "departments"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)


class TeamMember(Base):
    __tablename__ = "team_members"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    team_member_id = Column(String, nullable=False)  # Manuel ID (string/int)
    team_member = Column(String, nullable=False)  # İsim
    
    department = relationship("Department", backref="team_members")
    
    __table_args__ = (
        UniqueConstraint("department_id", "team_member_id", name="uq_dept_member_id"),
    )


class Shift(Base):
    __tablename__ = "shifts"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    department_id = Column(Integer, nullable=False)  # Denormalized for performance
    team_member_id = Column(Integer, ForeignKey("team_members.id"), nullable=False)
    date = Column(Date, nullable=False)
    work_type = Column(String, nullable=False)
    food_payment = Column(String, nullable=False)
    shift_start = Column(DateTime, nullable=True)
    shift_end = Column(DateTime, nullable=True)
    overtime_start = Column(DateTime, nullable=True)
    overtime_end = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), onupdate=text("CURRENT_TIMESTAMP"))
    
    team_member = relationship("TeamMember", backref="shifts")
    
    __table_args__ = (
        Index("idx_shifts_dept_member_date", "department_id", "team_member_id", "date"),
    )


class AccessLink(Base):
    __tablename__ = "access_links"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    token = Column(String, nullable=False, unique=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    role = Column(String, nullable=False)  # 'admin' or 'viewer'
    label = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    
    department = relationship("Department", backref="access_links")


# Engine and Session
_engine = None
_SessionLocal = None


import os
import streamlit as st

def get_database_url() -> str:
    """Get DATABASE_URL from environment variable or Streamlit secrets.
    
    Returns:
        str: Database URL
        
    Raises:
        ValueError: If URL is not found or is invalid (contains placeholders)
    """
    url = None
    
    # 1) env
    url = os.getenv("DATABASE_URL")
    
    # 2) streamlit secrets (lokalde de çalışır)
    if not url:
        try:
            if "DATABASE_URL" in st.secrets:
                url = st.secrets["DATABASE_URL"]
        except Exception:
            pass
    
    if not url:
        raise ValueError(
            "DATABASE_URL not found. Set it in:\n"
            "  - Environment variable: export DATABASE_URL='...'\n"
            "  - Or .streamlit/secrets.toml file: DATABASE_URL = '...'"
        )
    
    # Validate URL - check for placeholder values
    if "..." in url or "xxx" in url.lower() or "ep-..." in url:
        raise ValueError(
            "DATABASE_URL contains placeholder values (..., xxx, ep-...).\n"
            "Please update .streamlit/secrets.toml with your actual Neon Postgres URL.\n"
            "Format: postgresql+psycopg://user:password@ep-xxx-xxx.region.aws.neon.tech/dbname?sslmode=require"
        )
    
    # Basic validation - should contain @ and // for connection string
    if "@" not in url or "://" not in url:
        raise ValueError(
            f"Invalid DATABASE_URL format. Expected: postgresql+psycopg://user:password@host/dbname\n"
            f"Got: {url[:50]}..."
        )
    
    return url

def get_engine():
    """Get or create SQLAlchemy engine."""
    global _engine
    if _engine is None:
        database_url = get_database_url()
        
        # Ensure postgresql:// URL uses psycopg driver
        if database_url.startswith("postgresql://"):
            database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        elif not database_url.startswith("postgresql+psycopg://"):
            # If it's already postgresql+psycopg://, keep it
            if not database_url.startswith("postgresql+psycopg2://"):
                database_url = f"postgresql+psycopg://{database_url.split('://', 1)[1]}"
        
        _engine = create_engine(
            database_url,
            poolclass=QueuePool,
            pool_pre_ping=True,
            pool_size=5,  # Increased for better concurrency
            max_overflow=10,  # Increased for burst traffic
            pool_recycle=3600,  # Recycle connections after 1 hour
            connect_args={
                "connect_timeout": 10,  # 10 second connection timeout
            },
            echo=False,  # Set to True for SQL debugging
        )
    return _engine


def get_session_local():
    """Get or create session factory."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autocommit=False, autoflush=False)
    return _SessionLocal


@contextmanager
def get_session():
    """Context manager for database session."""
    SessionLocal = get_session_local()
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db():
    """Create all tables if they don't exist."""
    Base.metadata.create_all(bind=get_engine())


# Helper: Convert SQLAlchemy row to dict
def row_to_dict(row):
    """Convert SQLAlchemy row to dict."""
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


# Department CRUD
def create_department(name: str) -> int:
    with get_session() as session:
        dept = Department(name=name)
        session.add(dept)
        session.flush()
        dept_id = dept.id
        return dept_id


def list_departments() -> List[Dict[str, Any]]:
    with get_session() as session:
        depts = session.query(Department).order_by(Department.name).all()
        return [{"id": d.id, "name": d.name} for d in depts]


def delete_department(department_id: int) -> None:
    with get_session() as session:
        dept = session.query(Department).filter(Department.id == department_id).first()
        if dept:
            session.delete(dept)


# Team Member CRUD
def create_team_member(team_member_id: int, team_member: str, department_id: int) -> int:
    with get_session() as session:
        member = TeamMember(
            team_member_id=str(team_member_id),
            team_member=team_member,
            department_id=department_id,
        )
        session.add(member)
        session.flush()
        return member.id


def list_team_members(department_id: Optional[int] = None) -> List[Dict[str, Any]]:
    with get_session() as session:
        query = session.query(
            TeamMember.id,
            TeamMember.team_member_id,
            TeamMember.team_member,
            TeamMember.department_id,
            Department.name.label("department_name"),
        ).join(Department, TeamMember.department_id == Department.id)
        
        if department_id is not None:
            query = query.filter(TeamMember.department_id == department_id)
        
        results = query.order_by(Department.name, TeamMember.team_member).all()
        return [
            {
                "id": r.id,
                "team_member_id": int(r.team_member_id) if r.team_member_id.isdigit() else r.team_member_id,
                "team_member": r.team_member,
                "department_id": r.department_id,
                "department_name": r.department_name,
            }
            for r in results
        ]


def update_team_member(id_: int, team_member_id: int, team_member: str, department_id: int) -> None:
    with get_session() as session:
        member = session.query(TeamMember).filter(TeamMember.id == id_).first()
        if member:
            member.team_member_id = str(team_member_id)
            member.team_member = team_member
            member.department_id = department_id


def delete_team_member(id_: int) -> None:
    with get_session() as session:
        member = session.query(TeamMember).filter(TeamMember.id == id_).first()
        if member:
            session.delete(member)


def get_team_member_by_id(member_id: int) -> Optional[Dict[str, Any]]:
    with get_session() as session:
        result = (
            session.query(
                TeamMember.id,
                TeamMember.team_member_id,
                TeamMember.team_member,
                TeamMember.department_id,
                Department.name.label("department_name"),
            )
            .join(Department, TeamMember.department_id == Department.id)
            .filter(TeamMember.id == member_id)
            .first()
        )
        if result:
            return {
                "id": result.id,
                "team_member_id": int(result.team_member_id) if result.team_member_id.isdigit() else result.team_member_id,
                "team_member": result.team_member,
                "department_id": result.department_id,
                "department_name": result.department_name,
            }
        return None


# Shift CRUD
def list_shift_entries_for_member_and_date(team_member_db_id: int, date: str) -> List[Dict[str, Any]]:
    with get_session() as session:
        # Postgres DATE column expects a date object (not a YYYY-MM-DD string)
        date_obj = datetime.strptime(date, "%Y-%m-%d").date() if isinstance(date, str) else date
        shifts = (
            session.query(Shift)
            .filter(Shift.team_member_id == team_member_db_id)
            .filter(Shift.date == date_obj)
            .order_by(Shift.shift_start.is_(None), Shift.shift_start)
            .all()
        )
        return [
            {
                "id": s.id,
                "date": s.date.isoformat() if s.date else None,
                "team_member_id": s.team_member_id,
                "work_type": s.work_type,
                "food_payment": s.food_payment,
                "shift_start": s.shift_start.strftime("%Y-%m-%d %H:%M") if s.shift_start else None,
                "shift_end": s.shift_end.strftime("%Y-%m-%d %H:%M") if s.shift_end else None,
                "overtime_start": s.overtime_start.strftime("%Y-%m-%d %H:%M") if s.overtime_start else None,
                "overtime_end": s.overtime_end.strftime("%Y-%m-%d %H:%M") if s.overtime_end else None,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in shifts
        ]


def create_shift_entry(data: Dict[str, Any]) -> int:
    with get_session() as session:
        # Parse datetime strings
        shift_start = None
        shift_end = None
        overtime_start = None
        overtime_end = None
        
        if data.get("shift_start"):
            shift_start = datetime.strptime(data["shift_start"], "%Y-%m-%d %H:%M")
        if data.get("shift_end"):
            shift_end = datetime.strptime(data["shift_end"], "%Y-%m-%d %H:%M")
        if data.get("overtime_start"):
            overtime_start = datetime.strptime(data["overtime_start"], "%Y-%m-%d %H:%M")
        if data.get("overtime_end"):
            overtime_end = datetime.strptime(data["overtime_end"], "%Y-%m-%d %H:%M")
        
        # Get department_id from team_member
        member = session.query(TeamMember).filter(TeamMember.id == data["team_member_id"]).first()
        if not member:
            raise ValueError(f"Team member {data['team_member_id']} not found")
        
        shift = Shift(
            department_id=member.department_id,
            team_member_id=data["team_member_id"],
            date=datetime.strptime(data["date"], "%Y-%m-%d").date(),
            work_type=data["work_type"],
            food_payment=data["food_payment"],
            shift_start=shift_start,
            shift_end=shift_end,
            overtime_start=overtime_start,
            overtime_end=overtime_end,
        )
        session.add(shift)
        session.flush()
        return shift.id


def update_shift_entry(entry_id: int, data: Dict[str, Any]) -> None:
    with get_session() as session:
        shift = session.query(Shift).filter(Shift.id == entry_id).first()
        if not shift:
            raise ValueError(f"Shift entry {entry_id} not found")
        
        # Parse datetime strings
        if data.get("shift_start"):
            shift.shift_start = datetime.strptime(data["shift_start"], "%Y-%m-%d %H:%M")
        elif "shift_start" in data and data["shift_start"] is None:
            shift.shift_start = None
            
        if data.get("shift_end"):
            shift.shift_end = datetime.strptime(data["shift_end"], "%Y-%m-%d %H:%M")
        elif "shift_end" in data and data["shift_end"] is None:
            shift.shift_end = None
            
        if data.get("overtime_start"):
            shift.overtime_start = datetime.strptime(data["overtime_start"], "%Y-%m-%d %H:%M")
        elif "overtime_start" in data and data["overtime_start"] is None:
            shift.overtime_start = None
            
        if data.get("overtime_end"):
            shift.overtime_end = datetime.strptime(data["overtime_end"], "%Y-%m-%d %H:%M")
        elif "overtime_end" in data and data["overtime_end"] is None:
            shift.overtime_end = None
        
        shift.date = datetime.strptime(data["date"], "%Y-%m-%d").date()
        shift.work_type = data["work_type"]
        shift.food_payment = data["food_payment"]
        
        # Update department_id if team_member_id changed
        if data.get("team_member_id") and data["team_member_id"] != shift.team_member_id:
            member = session.query(TeamMember).filter(TeamMember.id == data["team_member_id"]).first()
            if member:
                shift.team_member_id = data["team_member_id"]
                shift.department_id = member.department_id


def delete_shift_entry(entry_id: int) -> None:
    with get_session() as session:
        shift = session.query(Shift).filter(Shift.id == entry_id).first()
        if shift:
            session.delete(shift)


def delete_shifts_for_member_and_date(team_member_id: int, date: str) -> int:
    """Delete all shifts for a member on a specific date. Returns count deleted."""
    with get_session() as session:
        count = (
            session.query(Shift)
            .filter(Shift.team_member_id == team_member_id)
            .filter(Shift.date == datetime.strptime(date, "%Y-%m-%d").date())
            .delete()
        )
        return count


def list_shift_entries_for_department_and_range(
    department_id: Optional[int],
    start_date: str,
    end_date: str,
) -> List[Dict[str, Any]]:
    with get_session() as session:
        query = (
            session.query(
                Shift.id,
                Shift.date,
                TeamMember.team_member_id,
                TeamMember.team_member,
                Shift.work_type,
                Shift.food_payment,
                Shift.shift_start,
                Shift.shift_end,
                Shift.overtime_start,
                Shift.overtime_end,
                Shift.department_id,
            )
            .join(TeamMember, Shift.team_member_id == TeamMember.id)
            .filter(Shift.date >= datetime.strptime(start_date, "%Y-%m-%d").date())
            .filter(Shift.date <= datetime.strptime(end_date, "%Y-%m-%d").date())
        )
        
        if department_id is not None:
            query = query.filter(Shift.department_id == department_id)
        
        results = query.order_by(Shift.date, TeamMember.team_member).all()
        return [
            {
                "id": r.id,
                "date": r.date.isoformat() if r.date else None,
                "team_member_id": int(r.team_member_id) if r.team_member_id.isdigit() else r.team_member_id,
                "team_member": r.team_member,
                "work_type": r.work_type,
                "food_payment": r.food_payment,
                "shift_start": r.shift_start.strftime("%Y-%m-%d %H:%M") if r.shift_start else None,
                "shift_end": r.shift_end.strftime("%Y-%m-%d %H:%M") if r.shift_end else None,
                "overtime_start": r.overtime_start.strftime("%Y-%m-%d %H:%M") if r.overtime_start else None,
                "overtime_end": r.overtime_end.strftime("%Y-%m-%d %H:%M") if r.overtime_end else None,
                "department_id": r.department_id,
            }
            for r in results
        ]


def list_distinct_work_types_for_department(department_id: int) -> List[str]:
    with get_session() as session:
        results = (
            session.query(Shift.work_type)
            .join(TeamMember, Shift.team_member_id == TeamMember.id)
            .filter(TeamMember.department_id == department_id)
            .distinct()
            .order_by(Shift.work_type)
            .all()
        )
        return [r[0] for r in results if r[0]]


# Access Links CRUD
def _generate_access_token() -> str:
    """Generate a secure random token (48+ characters)."""
    return secrets.token_urlsafe(36)  # ~48 chars


def get_access_link_by_token(token: str) -> Optional[Dict[str, Any]]:
    with get_session() as session:
        link = session.query(AccessLink).filter(AccessLink.token == token).first()
        if link:
            return {
                "id": link.id,
                "token": link.token,
                "department_id": link.department_id,
                "role": link.role,
                "label": link.label,
                "created_at": link.created_at.isoformat() if link.created_at else None,
            }
        return None


def get_access_link_by_department_and_role(department_id: int, role: str) -> Optional[Dict[str, Any]]:
    with get_session() as session:
        link = (
            session.query(AccessLink)
            .filter(AccessLink.department_id == department_id)
            .filter(AccessLink.role == role)
            .first()
        )
        if link:
            return {
                "id": link.id,
                "token": link.token,
                "department_id": link.department_id,
                "role": link.role,
                "label": link.label,
                "created_at": link.created_at.isoformat() if link.created_at else None,
            }
        return None


def create_access_link(department_id: int, role: str, label: Optional[str] = None) -> Dict[str, Any]:
    """Create a new access link. Returns error if one already exists."""
    with get_session() as session:
        # Check if link already exists
        existing = (
            session.query(AccessLink)
            .filter(AccessLink.department_id == department_id)
            .filter(AccessLink.role == role)
            .first()
        )
        if existing:
            raise ValueError(f"Access link for department {department_id} with role {role} already exists")
        
        token = _generate_access_token()
        link = AccessLink(
            token=token,
            department_id=department_id,
            role=role,
            label=label,
        )
        session.add(link)
        session.flush()
        return {
            "id": link.id,
            "token": link.token,
            "department_id": link.department_id,
            "role": link.role,
            "label": link.label,
            "created_at": link.created_at.isoformat() if link.created_at else None,
        }


def count_access_links() -> int:
    """Return total number of access links."""
    with get_session() as session:
        return int(session.query(AccessLink).count())

