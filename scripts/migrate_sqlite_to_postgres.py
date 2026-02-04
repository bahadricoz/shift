"""
Migration script: SQLite -> Postgres (Neon)
Mevcut SQLite veritabanındaki tüm verileri Postgres'e taşır.
"""
import os
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Load environment variables
load_dotenv()

# Import Postgres models
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db_postgres import (
    Base,
    Department,
    TeamMember,
    Shift,
    AccessLink,
    get_engine,
)


def get_sqlite_connection():
    """SQLite bağlantısı."""
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "shifts.db")
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"SQLite database not found: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def migrate_departments(sqlite_conn, pg_session):
    """Departments tablosunu migrate et."""
    print("Migrating departments...")
    sqlite_cur = sqlite_conn.cursor()
    sqlite_cur.execute("SELECT id, name FROM departments ORDER BY id")
    rows = sqlite_cur.fetchall()
    
    migrated = 0
    skipped = 0
    errors = []
    
    for row in rows:
        try:
            # Check if exists
            existing = pg_session.query(Department).filter(Department.id == row["id"]).first()
            if existing:
                print(f"  Skipping department {row['id']} ({row['name']}) - already exists")
                skipped += 1
                continue
            
            dept = Department(id=row["id"], name=row["name"])
            pg_session.add(dept)
            migrated += 1
        except Exception as e:
            errors.append(f"Department {row['id']}: {e}")
    
    pg_session.commit()
    print(f"  ✅ Migrated: {migrated}, Skipped: {skipped}, Errors: {len(errors)}")
    if errors:
        for err in errors[:5]:
            print(f"    - {err}")
    return migrated, skipped, len(errors)


def migrate_team_members(sqlite_conn, pg_session):
    """Team members tablosunu migrate et."""
    print("Migrating team members...")
    sqlite_cur = sqlite_conn.cursor()
    sqlite_cur.execute("""
        SELECT id, team_member_id, team_member, department_id
        FROM team_members
        ORDER BY id
    """)
    rows = sqlite_cur.fetchall()
    
    migrated = 0
    skipped = 0
    errors = []
    
    for row in rows:
        try:
            # Check if exists
            existing = pg_session.query(TeamMember).filter(TeamMember.id == row["id"]).first()
            if existing:
                print(f"  Skipping team member {row['id']} ({row['team_member']}) - already exists")
                skipped += 1
                continue
            
            member = TeamMember(
                id=row["id"],
                department_id=row["department_id"],
                team_member_id=str(row["team_member_id"]),
                team_member=row["team_member"],
            )
            pg_session.add(member)
            migrated += 1
        except Exception as e:
            errors.append(f"Team member {row['id']}: {e}")
    
    pg_session.commit()
    print(f"  ✅ Migrated: {migrated}, Skipped: {skipped}, Errors: {len(errors)}")
    if errors:
        for err in errors[:5]:
            print(f"    - {err}")
    return migrated, skipped, len(errors)


def migrate_shifts(sqlite_conn, pg_session):
    """Shift entries tablosunu migrate et."""
    print("Migrating shift entries...")
    sqlite_cur = sqlite_conn.cursor()
    sqlite_cur.execute("""
        SELECT 
            se.id,
            se.date,
            se.team_member_id,
            se.work_type,
            se.food_payment,
            se.shift_start,
            se.shift_end,
            se.overtime_start,
            se.overtime_end,
            se.created_at,
            tm.department_id
        FROM shift_entries se
        JOIN team_members tm ON se.team_member_id = tm.id
        ORDER BY se.id
    """)
    rows = sqlite_cur.fetchall()
    
    migrated = 0
    skipped = 0
    errors = []
    
    for row in rows:
        try:
            # Check if exists
            existing = pg_session.query(Shift).filter(Shift.id == row["id"]).first()
            if existing:
                skipped += 1
                continue
            
            # Parse dates
            date_obj = datetime.strptime(row["date"], "%Y-%m-%d").date() if row["date"] else None
            shift_start = datetime.strptime(row["shift_start"], "%Y-%m-%d %H:%M") if row.get("shift_start") else None
            shift_end = datetime.strptime(row["shift_end"], "%Y-%m-%d %H:%M") if row.get("shift_end") else None
            overtime_start = datetime.strptime(row["overtime_start"], "%Y-%m-%d %H:%M") if row.get("overtime_start") else None
            overtime_end = datetime.strptime(row["overtime_end"], "%Y-%m-%d %H:%M") if row.get("overtime_end") else None
            created_at = datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S") if row.get("created_at") else datetime.now()
            
            shift = Shift(
                id=row["id"],
                department_id=row["department_id"],
                team_member_id=row["team_member_id"],
                date=date_obj,
                work_type=row["work_type"],
                food_payment=row["food_payment"],
                shift_start=shift_start,
                shift_end=shift_end,
                overtime_start=overtime_start,
                overtime_end=overtime_end,
                created_at=created_at,
                updated_at=created_at,
            )
            pg_session.add(shift)
            migrated += 1
        except Exception as e:
            errors.append(f"Shift {row['id']}: {e}")
    
    pg_session.commit()
    print(f"  ✅ Migrated: {migrated}, Skipped: {skipped}, Errors: {len(errors)}")
    if errors:
        for err in errors[:5]:
            print(f"    - {err}")
    return migrated, skipped, len(errors)


def main():
    """Ana migration fonksiyonu."""
    print("=" * 60)
    print("SQLite -> Postgres Migration")
    print("=" * 60)
    
    # Check DATABASE_URL
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("❌ ERROR: DATABASE_URL environment variable not set")
        print("   Set it in .env file or export it:")
        print("   export DATABASE_URL='postgresql+psycopg://user:pass@host/dbname'")
        return
    
    print(f"✅ DATABASE_URL found")
    print(f"   Target: {database_url.split('@')[-1] if '@' in database_url else '***'}")
    
    # Initialize Postgres
    print("\n📦 Initializing Postgres database...")
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    pg_session = SessionLocal()
    
    # Connect to SQLite
    print("\n📦 Connecting to SQLite database...")
    sqlite_conn = get_sqlite_connection()
    print("✅ Connected")
    
    try:
        # Migrate tables
        print("\n" + "=" * 60)
        print("Starting migration...")
        print("=" * 60)
        
        dept_stats = migrate_departments(sqlite_conn, pg_session)
        member_stats = migrate_team_members(sqlite_conn, pg_session)
        shift_stats = migrate_shifts(sqlite_conn, pg_session)
        
        # Summary
        print("\n" + "=" * 60)
        print("Migration Summary")
        print("=" * 60)
        print(f"Departments:  {dept_stats[0]} migrated, {dept_stats[1]} skipped, {dept_stats[2]} errors")
        print(f"Team Members: {member_stats[0]} migrated, {member_stats[1]} skipped, {member_stats[2]} errors")
        print(f"Shifts:        {shift_stats[0]} migrated, {shift_stats[1]} skipped, {shift_stats[2]} errors")
        print("\n✅ Migration completed!")
        
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        pg_session.rollback()
    finally:
        sqlite_conn.close()
        pg_session.close()


if __name__ == "__main__":
    main()


