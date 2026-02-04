from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date as date_cls, time as time_cls, timedelta
from typing import Any, Dict, List, Optional, Tuple

from db_postgres import (
    list_shift_entries_for_member_and_date,
    list_shift_entries_for_department_and_range,
)


# Yeni work_type enum degerleri (saat bilgisiz)
WORK_TYPES = [
    "Office",
    "Remote",
    "Report",
    "Annual Leave",
    "OFF",
]

FOOD_PAYMENT_VALUES = ["YES", "NO"]

DATETIME_FORMAT = "%Y-%m-%d %H:%M"
DATE_FORMAT = "%Y-%m-%d"


@dataclass
class ValidationResult:
    valid: bool
    errors: List[str]


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.strptime(value, DATETIME_FORMAT)


def compose_datetime_str(day: date_cls, t: Optional[time_cls]) -> Optional[str]:
    """Combine date and time to our canonical string format or return None."""
    if t is None:
        return None
    dt = datetime.combine(day, t)
    return dt.strftime(DATETIME_FORMAT)


def parse_time_interval_text(text: str) -> Optional[Tuple[time_cls, time_cls]]:
    """
    Kullanıcının girdiği "9-18", "09:30-18:15", "9:00-18:00" gibi stringleri
    basitçe parse edip (start_time, end_time) döndürür.
    Geçersiz formatta None döner.
    """
    if not text:
        return None

    raw = text.strip()
    if "-" not in raw:
        return None

    left, right = raw.split("-", 1)
    left = left.strip().replace(".", ":")
    right = right.strip().replace(".", ":")

    def _norm(part: str) -> Optional[time_cls]:
        if not part:
            return None
        if ":" not in part:
            part = f"{part}:00"
        try:
            dt = datetime.strptime(part, "%H:%M")
            return dt.time()
        except ValueError:
            return None

    start_t = _norm(left)
    end_t = _norm(right)
    if not start_t or not end_t:
        return None
    return start_t, end_t


def validate_shift_payload(payload: Dict[str, Any]) -> ValidationResult:
    """
    Validate a single shift segment according to the rules:
      - shift_start < shift_end (if both)
      - overtime_start < overtime_end (if both)
      - overtime_start >= shift_end (if both)
      - work_type OFF / Annual Leave: shift_start/end may be empty (allowed)
    Overlap check is handled separately.
    """
    errors: List[str] = []

    work_type = payload.get("work_type")
    if work_type not in WORK_TYPES:
        errors.append("Geçersiz work_type.")

    food_payment = payload.get("food_payment")
    if food_payment not in FOOD_PAYMENT_VALUES:
        errors.append("Geçersiz food_payment (YES/NO olmalı).")

    shift_start = payload.get("shift_start")
    shift_end = payload.get("shift_end")
    overtime_start = payload.get("overtime_start")
    overtime_end = payload.get("overtime_end")

    # Shift time validation
    if shift_start and shift_end:
        try:
            s = _parse_dt(shift_start)
            e = _parse_dt(shift_end)
            if s >= e:
                errors.append("shift_start, shift_end'den küçük olmalı.")
        except ValueError:
            errors.append("shift_start/end tarih formatı hatalı.")
    elif work_type not in ("OFF", "Annual Leave", "Report"):
        # OFF, Annual Leave ve Report için saat zorunlu değil
        # Diğer work type'lar için saat doldurulmalı
        if work_type in WORK_TYPES:
            errors.append("Bu work_type için shift_start ve shift_end doldurulmalı.")

    # Overtime validation
    if overtime_start and overtime_end:
        try:
            os_ = _parse_dt(overtime_start)
            oe_ = _parse_dt(overtime_end)
            if os_ >= oe_:
                errors.append("overtime_start, overtime_end'den küçük olmalı.")

            if shift_end:
                se = _parse_dt(shift_end)
                if os_ < se:
                    errors.append(
                        "overtime_start, shift_end'den küçük olamaz "
                        "(fazla mesai vardiya sonrasında başlamalı)."
                    )
        except ValueError:
            errors.append("overtime_start/end tarih formatı hatalı.")
    elif overtime_start or overtime_end:
        errors.append("overtime_start ve overtime_end birlikte doldurulmalı.")

    return ValidationResult(valid=not errors, errors=errors)


def check_overlap_for_member_date(
    member_db_id: int,
    date_str: str,
    new_shift_start: Optional[str],
    new_shift_end: Optional[str],
    *,
    exclude_entry_id: Optional[int] = None,
) -> ValidationResult:
    """
    Check overlap for the given member and date using shift_start/shift_end only.
    If any of these is None, skip overlap check (per requirements).
    """
    if not new_shift_start or not new_shift_end:
        # Requirements: if hours are empty, do not perform overlap check
        return ValidationResult(True, [])

    try:
        new_start = _parse_dt(new_shift_start)
        new_end = _parse_dt(new_shift_end)
    except ValueError:
        # datetime parsing error is handled elsewhere
        return ValidationResult(True, [])

    existing = list_shift_entries_for_member_and_date(member_db_id, date_str)

    for row in existing:
        if exclude_entry_id is not None and row["id"] == exclude_entry_id:
            continue

        es = row["shift_start"]
        ee = row["shift_end"]
        if not es or not ee:
            continue

        es_dt = _parse_dt(es)
        ee_dt = _parse_dt(ee)

        # Overlap if not (new_end <= es or new_start >= ee)
        if not (new_end <= es_dt or new_start >= ee_dt):
            return ValidationResult(
                False,
                [
                    "Bu personel için aynı gün vardiya saatleri çakışıyor. "
                    "Lütfen saatleri kontrol edin."
                ],
            )

    return ValidationResult(True, [])


def build_export_rows(
    department_id: Optional[int],
    start_date: date_cls,
    end_date: date_cls,
) -> List[Dict[str, Any]]:
    """
    Prepare rows for CSV export with the exact required columns and formats.
    """
    rows = list_shift_entries_for_department_and_range(
        department_id=department_id,
        start_date=start_date.strftime(DATE_FORMAT),
        end_date=end_date.strftime(DATE_FORMAT),
    )

    export_rows: List[Dict[str, Any]] = []
    for r in rows:
        export_rows.append(
            {
                "date": r["date"],
                "team_member_id": r["team_member_id"],
                "team_member": r["team_member"],
                "work_type": r["work_type"],
                "food_payment": r["food_payment"],
                "shift_start": r["shift_start"] or "",
                "shift_end": r["shift_end"] or "",
                "overtime_start": r["overtime_start"] or "",
                "overtime_end": r["overtime_end"] or "",
            }
        )

    return export_rows


EXPORT_COLUMNS = [
    "date",
    "team_member_id",
    "team_member",
    "work_type",
    "food_payment",
    "shift_start",
    "shift_end",
    "overtime_start",
    "overtime_end",
]


def fmt_date(value: str) -> str:
    """YYYY-MM-DD -> M/D/YYYY (no leading zeros)."""
    if not value:
        return ""
    try:
        d = datetime.strptime(value, DATE_FORMAT).date()
        return f"{d.month}/{d.day}/{d.year}"
    except Exception:
        return value


def fmt_dt(value: str) -> str:
    """YYYY-MM-DD HH:MM -> M/D/YYYY H:MM (no leading zeros for month/day/hour)."""
    if not value:
        return ""
    try:
        dt = datetime.strptime(value, DATETIME_FORMAT)
        return f"{dt.month}/{dt.day}/{dt.year} {dt.hour}:{dt.minute:02d}"
    except Exception:
        return value


def export_csv_rows(
    *,
    department_id: int,
    start_date: date_cls,
    end_date: date_cls,
    team_member_ids: Optional[List[int]] = None,
    work_types: Optional[List[str]] = None,
    food_payment: str = "ALL",
) -> List[Dict[str, Any]]:
    """
    Export rows with fixed columns and order.
    Filters:
      - team_member_ids: external team_member_id values (NOT internal db id)
      - work_types: list of work_type strings
      - food_payment: ALL/YES/NO
    Uppercase:
      - team_member, work_type, food_payment
    """
    rows = list_shift_entries_for_department_and_range(
        department_id=department_id,
        start_date=start_date.strftime(DATE_FORMAT),
        end_date=end_date.strftime(DATE_FORMAT),
    )

    # Normalize filter inputs
    team_member_ids_set = set(team_member_ids or [])
    work_types_set = set([wt for wt in (work_types or []) if wt])
    food_payment_norm = (food_payment or "ALL").upper()

    export_rows: List[Dict[str, Any]] = []
    for r in rows:
        # team_member_manual_id kullan (kullanıcının girdiği manuel ID)
        tm_manual_id = r.get("team_member_manual_id") or r.get("team_member_id")
        # Eğer string ise int'e çevir
        if isinstance(tm_manual_id, str) and tm_manual_id.isdigit():
            tm_id = int(tm_manual_id)
        elif isinstance(tm_manual_id, (int, float)):
            tm_id = int(tm_manual_id)
        else:
            tm_id = tm_manual_id  # Fallback
        
        wt = (r["work_type"] or "").strip()
        fp = (r["food_payment"] or "").strip()

        if team_member_ids_set and tm_id not in team_member_ids_set:
            continue
        if work_types_set and wt not in work_types_set:
            continue
        if food_payment_norm in ("YES", "NO") and fp.upper() != food_payment_norm:
            continue

        record = {
            "date": fmt_date(r["date"]),
            "team_member_id": tm_id,  # Manuel ID (kullanıcının girdiği)
            "team_member": (r["team_member"] or "").upper(),
            "work_type": wt.upper(),
            "food_payment": fp.upper(),
            "shift_start": fmt_dt(r["shift_start"]) if r["shift_start"] else "",
            "shift_end": fmt_dt(r["shift_end"]) if r["shift_end"] else "",
            "overtime_start": fmt_dt(r["overtime_start"]) if r["overtime_start"] else "",
            "overtime_end": fmt_dt(r["overtime_end"]) if r["overtime_end"] else "",
        }

        # Guarantee fixed column order
        export_rows.append({k: record.get(k, "") for k in EXPORT_COLUMNS})

    return export_rows


def week_range_for_date(d: date_cls) -> Tuple[date_cls, date_cls]:
    """
    Helper: given a date, return Monday-Sunday range that contains it.
    """
    weekday = d.weekday()  # Monday=0
    start = d - timedelta(days=weekday)
    end = start + timedelta(days=6)
    return start, end


