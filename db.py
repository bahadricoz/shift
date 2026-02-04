import os
import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

import secrets


DB_FILENAME = "shifts.db"
DB_PATH = os.path.join(os.path.dirname(__file__), DB_FILENAME)


def get_connection() -> sqlite3.Connection:
    """Return a SQLite connection with row factory configured."""
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_cursor():
    conn = get_connection()
    try:
        cur = conn.cursor()
        yield cur
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Create tables if they do not exist (simple migration-safe init)."""
    with get_cursor() as cur:
        # Departments
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS departments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            );
            """
        )

        # Team members
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS team_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_member_id INTEGER NOT NULL UNIQUE,
                team_member TEXT NOT NULL,
                department_id INTEGER NOT NULL,
                FOREIGN KEY (department_id) REFERENCES departments(id)
            );
            """
        )

        # Shift entries
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS shift_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                team_member_id INTEGER NOT NULL,
                work_type TEXT NOT NULL,
                food_payment TEXT NOT NULL,
                shift_start TEXT,
                shift_end TEXT,
                overtime_start TEXT,
                overtime_end TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (team_member_id) REFERENCES team_members(id)
            );
            """
        )

        # Share links for public read-only views
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS share_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT NOT NULL UNIQUE,
                scope_type TEXT NOT NULL, -- 'person' or 'department'
                scope_id INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )

        # Basit migration: eski work_type degerlerini yeni enumlara donustur
        # 9-18 Office, 9-18 Remote, 12-21 Remote -> Office / Remote
        cur.execute(
            "UPDATE shift_entries SET work_type = 'Office' WHERE work_type LIKE '%Office%';"
        )
        cur.execute(
            "UPDATE shift_entries SET work_type = 'Remote' WHERE work_type LIKE '%Remote%';"
        )


# Department CRUD


def create_department(name: str) -> int:
    with get_cursor() as cur:
        cur.execute("INSERT INTO departments (name) VALUES (?);", (name,))
        return cur.lastrowid


def list_departments() -> List[sqlite3.Row]:
    with get_cursor() as cur:
        cur.execute("SELECT id, name FROM departments ORDER BY name;")
        return cur.fetchall()


def delete_department(department_id: int) -> None:
    with get_cursor() as cur:
        # Optionally, you could enforce foreign key checks and prevent delete
        cur.execute("DELETE FROM departments WHERE id = ?;", (department_id,))


# Team member CRUD


def create_team_member(
    team_member_id: int, team_member: str, department_id: int
) -> int:
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO team_members (team_member_id, team_member, department_id)
            VALUES (?, ?, ?);
            """,
            (team_member_id, team_member, department_id),
        )
        return cur.lastrowid


def list_team_members(department_id: Optional[int] = None) -> List[sqlite3.Row]:
    with get_cursor() as cur:
        if department_id is None:
            cur.execute(
                """
                SELECT tm.id, tm.team_member_id, tm.team_member, tm.department_id,
                       d.name as department_name
                FROM team_members tm
                JOIN departments d ON tm.department_id = d.id
                ORDER BY d.name, tm.team_member;
                """
            )
        else:
            cur.execute(
                """
                SELECT tm.id, tm.team_member_id, tm.team_member, tm.department_id,
                       d.name as department_name
                FROM team_members tm
                JOIN departments d ON tm.department_id = d.id
                WHERE tm.department_id = ?
                ORDER BY tm.team_member;
                """,
                (department_id,),
            )
        return cur.fetchall()


def update_team_member(
    id_: int, team_member_id: int, team_member: str, department_id: int
) -> None:
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE team_members
            SET team_member_id = ?, team_member = ?, department_id = ?
            WHERE id = ?;
            """,
            (team_member_id, team_member, department_id, id_),
        )


def delete_team_member(id_: int) -> None:
    with get_cursor() as cur:
        cur.execute("DELETE FROM team_members WHERE id = ?;", (id_,))


# Shift entries CRUD / queries


def list_shift_entries_for_member_and_date(
    team_member_db_id: int, date: str
) -> List[sqlite3.Row]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM shift_entries
            WHERE team_member_id = ? AND date = ?
            ORDER BY shift_start IS NULL, shift_start;
            """,
            (team_member_db_id, date),
        )
        return cur.fetchall()


def create_shift_entry(data: Dict[str, Any]) -> int:
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO shift_entries (
                date,
                team_member_id,
                work_type,
                food_payment,
                shift_start,
                shift_end,
                overtime_start,
                overtime_end
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                data["date"],
                data["team_member_id"],
                data["work_type"],
                data["food_payment"],
                data.get("shift_start"),
                data.get("shift_end"),
                data.get("overtime_start"),
                data.get("overtime_end"),
            ),
        )
        return cur.lastrowid


def update_shift_entry(entry_id: int, data: Dict[str, Any]) -> None:
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE shift_entries
            SET date = ?,
                team_member_id = ?,
                work_type = ?,
                food_payment = ?,
                shift_start = ?,
                shift_end = ?,
                overtime_start = ?,
                overtime_end = ?
            WHERE id = ?;
            """,
            (
                data["date"],
                data["team_member_id"],
                data["work_type"],
                data["food_payment"],
                data.get("shift_start"),
                data.get("shift_end"),
                data.get("overtime_start"),
                data.get("overtime_end"),
                entry_id,
            ),
        )


def delete_shift_entry(entry_id: int) -> None:
    with get_cursor() as cur:
        cur.execute("DELETE FROM shift_entries WHERE id = ?;", (entry_id,))


def list_shift_entries_for_department_and_range(
    department_id: Optional[int],
    start_date: str,
    end_date: str,
) -> List[sqlite3.Row]:
    """
    Join shift_entries with team_members and departments
    for export between [start_date, end_date].
    """
    params: List[Any] = [start_date, end_date]
    where_dept = ""
    if department_id is not None:
        where_dept = "AND tm.department_id = ?"
        params.append(department_id)

    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT
                se.id,
                se.date,
                tm.team_member_id,
                tm.team_member,
                se.work_type,
                se.food_payment,
                se.shift_start,
                se.shift_end,
                se.overtime_start,
                se.overtime_end,
                tm.department_id
            FROM shift_entries se
            JOIN team_members tm ON se.team_member_id = tm.id
            WHERE se.date >= ? AND se.date <= ?
            {where_dept}
            ORDER BY se.date, tm.team_member;
            """,
            params,
        )
        return cur.fetchall()


def list_shift_entries_for_member_and_month(
    team_member_db_id: int,
    year: int,
    month: int,
) -> List[sqlite3.Row]:
    """Fetch all entries for a member and month, useful for planning grid."""
    month_str = f"{month:02d}"
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM shift_entries
            WHERE team_member_id = ?
              AND substr(date, 1, 4) = ?
              AND substr(date, 6, 2) = ?
            ORDER BY date, shift_start IS NULL, shift_start;
            """,
            (team_member_db_id, str(year), month_str),
        )
        return cur.fetchall()


def list_shift_entries_for_member_and_week(
    team_member_db_id: int,
    start_date: str,
    end_date: str,
) -> List[sqlite3.Row]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM shift_entries
            WHERE team_member_id = ?
              AND date >= ? AND date <= ?
            ORDER BY date, shift_start IS NULL, shift_start;
            """,
            (team_member_db_id, start_date, end_date),
        )
        return cur.fetchall()


def list_distinct_work_types_for_department(department_id: int) -> List[str]:
    """Return distinct work_type values used in a department (for export filters)."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT se.work_type AS work_type
            FROM shift_entries se
            JOIN team_members tm ON se.team_member_id = tm.id
            WHERE tm.department_id = ?
            ORDER BY se.work_type;
            """,
            (department_id,),
        )
        return [r["work_type"] for r in cur.fetchall() if r["work_type"]]


# Share links


def _generate_share_token() -> str:
    # URL-safe, reasonably short ve tahmin edilmesi zor bir token
    return secrets.token_urlsafe(16)


def get_share_link(scope_type: str, scope_id: int) -> Optional[sqlite3.Row]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, token, scope_type, scope_id, created_at
            FROM share_links
            WHERE scope_type = ? AND scope_id = ?
            LIMIT 1;
            """,
            (scope_type, scope_id),
        )
        row = cur.fetchone()
        return row


def create_share_link(scope_type: str, scope_id: int) -> sqlite3.Row:
    token = _generate_share_token()
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO share_links (token, scope_type, scope_id)
            VALUES (?, ?, ?);
            """,
            (token, scope_type, scope_id),
        )
        link_id = cur.lastrowid
        cur.execute(
            """
            SELECT id, token, scope_type, scope_id, created_at
            FROM share_links
            WHERE id = ?;
            """,
            (link_id,),
        )
        return cur.fetchone()


def get_or_create_share_link(scope_type: str, scope_id: int) -> sqlite3.Row:
    existing = get_share_link(scope_type, scope_id)
    if existing is not None:
        return existing
    return create_share_link(scope_type, scope_id)


def get_share_link_by_token(token: str) -> Optional[sqlite3.Row]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, token, scope_type, scope_id, created_at
            FROM share_links
            WHERE token = ?
            LIMIT 1;
            """,
            (token,),
        )
        return cur.fetchone()


def get_team_member_by_id(member_id: int) -> Optional[sqlite3.Row]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT tm.id,
                   tm.team_member_id,
                   tm.team_member,
                   tm.department_id,
                   d.name as department_name
            FROM team_members tm
            JOIN departments d ON tm.department_id = d.id
            WHERE tm.id = ?;
            """,
            (member_id,),
        )
        return cur.fetchone()


