import calendar
import os
from datetime import date, datetime, time
from typing import Optional, Dict, Any, List

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

# Load environment variables (for local development)
load_dotenv()

# Use Postgres database layer
import db_postgres as db
from db_postgres import (
    init_db,
    list_departments,
    create_department,
    delete_department,
    list_team_members,
    create_team_member,
    update_team_member,
    delete_team_member,
    list_shift_entries_for_member_and_date,
    create_shift_entry,
    update_shift_entry,
    delete_shift_entry,
    delete_shifts_for_member_and_date,
    get_team_member_by_id,
    list_distinct_work_types_for_department,
    list_shift_entries_for_department_and_range,
    get_access_link_by_token,
    get_access_link_by_department_and_role,
    create_access_link,
    count_access_links,
)
from services import (
    WORK_TYPES,
    FOOD_PAYMENT_VALUES,
    compose_datetime_str,
    validate_shift_payload,
    check_overlap_for_member_date,
    build_export_rows,
    week_range_for_date,
    parse_time_interval_text,
    export_csv_rows,
    EXPORT_COLUMNS,
)
# Note: init_db() is called in main() after Streamlit is initialized
# so that st.secrets is available


def _get_app_base_url() -> Optional[str]:
    """
    Optional base URL for building full share links.
    - Prefer Streamlit secrets APP_BASE_URL, fallback to env APP_BASE_URL.
    Example: https://your-app.streamlit.app
    """
    try:
        base = st.secrets.get("APP_BASE_URL") if hasattr(st, "secrets") else None
    except Exception:
        base = None
    if not base:
        base = os.getenv("APP_BASE_URL")
    if not base:
        return None
    return str(base).rstrip("/")


def _build_access_url(token: str) -> str:
    base = _get_app_base_url()
    if base:
        return f"{base}/?token={token}"
    return f"?token={token}"


def _get_global_admin_token_secret() -> Optional[str]:
    """Read GLOBAL_ADMIN_TOKEN from Streamlit secrets or env (optional)."""
    try:
        tok = st.secrets.get("GLOBAL_ADMIN_TOKEN") if hasattr(st, "secrets") else None
    except Exception:
        tok = None
    if not tok:
        tok = os.getenv("GLOBAL_ADMIN_TOKEN")
    if not tok:
        return None
    return str(tok)


def _resolve_token_access() -> Dict[str, Any]:
    """
    Resolve token-based access from URL query params.
    Returns: {
        "has_access": bool,
        "token": str or None,
        "department_id": int or None,
        "role": "admin" | "viewer" | None,
        "error": str or None
    }
    """
    try:
        token = st.query_params.get("token", "")
    except Exception:
        return {"has_access": False, "token": None, "department_id": None, "role": None, "error": "Query params error"}
    
    if not token:
        return {"has_access": False, "token": None, "department_id": None, "role": None, "error": "Token required"}
    
    link = get_access_link_by_token(token)
    if not link:
        return {"has_access": False, "token": token, "department_id": None, "role": None, "error": "Invalid token"}
    
    return {
        "has_access": True,
        "token": token,
        "department_id": link["department_id"],
        "role": link["role"],
        "error": None,
    }


def render_access_denied(error_msg: str):
    """Show access denied screen."""
    st.set_page_config(page_title="Access Denied", layout="centered")
    _inject_global_css()
    st.error(f"❌ Erişim Reddedildi: {error_msg}")

    # Bootstrap: if no token yet AND no access links exist, allow creating the first admin/viewer links.
    try:
        no_links_yet = count_access_links() == 0
    except Exception:
        no_links_yet = False

    if error_msg == "Token required" and no_links_yet:
        st.info("İlk kurulum: Henüz hiç erişim linki yok. Buradan ilk Admin/Viewer linklerini oluşturabilirsiniz.")
        st.markdown("### İlk kurulum (Bootstrap)")

        dept_name = st.text_input("Departman adı", value="Genel", key="bootstrap_dept_name")
        col_a, col_b = st.columns(2)
        with col_a:
            create_btn = st.button("🔧 Kurulumu Başlat (Linkleri Oluştur)", type="primary", key="bootstrap_create_links")
        with col_b:
            st.caption("Bu işlem 1 kere yapılır. Sonrasında her giriş token ile olur.")

        if create_btn:
            try:
                # 1) ensure department exists
                departments = list_departments()
                existing = next((d for d in departments if d["name"].strip().lower() == dept_name.strip().lower()), None)
                if existing:
                    dept_id = existing["id"]
                else:
                    dept_id = create_department(dept_name.strip())

                # 2) create admin + viewer links (static)
                admin_link = get_access_link_by_department_and_role(dept_id, "admin") or create_access_link(
                    dept_id, "admin", "Bootstrap admin"
                )
                viewer_link = get_access_link_by_department_and_role(dept_id, "viewer") or create_access_link(
                    dept_id, "viewer", "Bootstrap viewer"
                )

                st.success("✅ Linkler oluşturuldu. Aşağıdan kopyalayıp kullanabilirsiniz.")
                st.markdown(f"### Departman: **{dept_name.strip()}**")

                st.markdown("### 👑 Admin (Lider) Linki — Vardiya düzenleme")
                st.code(_build_access_url(admin_link["token"]), language="text")
                st.caption("Bu link ile vardiya ekleyebilir/düzenleyebilir/silebilirsiniz.")

                st.markdown("### 👁️ Viewer (Ekip) Linki — Sadece görüntüleme")
                st.code(_build_access_url(viewer_link["token"]), language="text")
                st.caption("Bu link ile sadece vardiya görüntülenir (read-only).")

                if not _get_app_base_url():
                    st.info(
                        "Tam link (https://...) göstermek için `APP_BASE_URL` ayarlayın. "
                        "Streamlit Cloud'da Secrets'a, lokalde `.streamlit/secrets.toml` içine ekleyebilirsiniz."
                    )
                st.stop()
            except Exception as e:
                st.error(f"Kurulum hatası: {e}")
                st.stop()

        st.stop()

    # Recovery / setup mode: if links already exist but user has no token
    if error_msg == "Token required" and not no_links_yet:
        st.info("Bu uygulama token ile açılır. Daha önce link üretildiği için bootstrap ekranı otomatik açılmıyor.")
        st.markdown("### Kurulum / Kurtarma")

        secret_setup_token = _get_global_admin_token_secret()
        if not secret_setup_token:
            st.warning(
                "`GLOBAL_ADMIN_TOKEN` tanımlı değil. Linkleri geri almak için Streamlit Cloud > Settings > Secrets içine "
                "`GLOBAL_ADMIN_TOKEN = \"...\"` ekleyin (rastgele uzun bir değer), sonra bu sayfayı yenileyin."
            )
            st.stop()

        entered = st.text_input("Kurulum anahtarı (GLOBAL_ADMIN_TOKEN)", type="password", key="setup_token_entered")
        if entered and entered != secret_setup_token:
            st.error("Kurulum anahtarı yanlış.")
            st.stop()
        if not entered:
            st.caption("Kurulum anahtarını girince mevcut departman linklerini görebilirsiniz.")
            st.stop()

        # Authorized setup panel
        departments = list_departments()
        if not departments:
            st.error("Hiç departman yok. Önce bir departman oluşturmanız gerekir.")
            dept_name = st.text_input("Departman adı", value="Genel", key="setup_create_dept_name")
            if st.button("Departman oluştur", type="primary", key="setup_create_dept_btn"):
                dept_id = create_department(dept_name.strip())
                st.success("Departman oluşturuldu. Sayfayı yenileyin.")
            st.stop()

        dept_options = {d["name"]: d["id"] for d in departments}
        dept_name = st.selectbox("Departman seç", options=list(dept_options.keys()), key="setup_pick_dept")
        dept_id = dept_options[dept_name]

        st.markdown("#### Linkleri Göster / Oluştur")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("👑 Admin linki göster/oluştur", type="primary", key="setup_admin_show"):
                admin_link = get_access_link_by_department_and_role(dept_id, "admin") or create_access_link(
                    dept_id, "admin", f"{dept_name} | Admin"
                )
                st.code(_build_access_url(admin_link["token"]), language="text")
        with col2:
            if st.button("👁️ Viewer linki göster/oluştur", key="setup_viewer_show"):
                viewer_link = get_access_link_by_department_and_role(dept_id, "viewer") or create_access_link(
                    dept_id, "viewer", f"{dept_name} | Viewer"
                )
                st.code(_build_access_url(viewer_link["token"]), language="text")

        st.caption("Not: Bu ekran sadece GLOBAL_ADMIN_TOKEN bilen kişiler için.")
        st.stop()

    st.info("Geçerli bir erişim linki ile giriş yapmanız gerekiyor.")
    st.stop()


def _inject_global_css() -> None:
    """Minimal, modern görünüm için global CSS."""
    st.markdown(
        """
        <style>
        .main {
            max-width: 1200px;
            margin: 0 auto;
            padding-top: 0.5rem;
        }
        h1, h2, h3 {
            margin-top: 0.2rem;
            margin-bottom: 0.6rem;
        }
        .shift-cell-btn > button {
            width: 100%;
            min-width: 40px;
            padding: 0.4rem 0.5rem;
            border-radius: 999px;
            font-size: 0.75rem;
            font-weight: 500;
            line-height: 1.2;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            border-width: 1px;
            border-style: solid;
        }
        .shift-empty-btn > button {
            border-style: dashed;
            color: #999999;
            background-color: #f5f5f5;
        }
        .work-type-office > button {
            background-color: #3b82f6;
            color: white;
            border-color: #2563eb;
        }
        .work-type-remote > button {
            background-color: #10b981;
            color: white;
            border-color: #059669;
        }
        .work-type-report > button {
            background-color: #8b5cf6;
            color: white;
            border-color: #7c3aed;
        }
        .work-type-leave > button {
            background-color: #f59e0b;
            color: white;
            border-color: #d97706;
        }
        .work-type-off > button {
            background-color: #6b7280;
            color: white;
            border-color: #4b5563;
        }
        .work-type-custom > button {
            background-color: #ec4899;
            color: white;
            border-color: #db2777;
        }
        .work-type-empty > button {
            background-color: #f5f5f5;
            color: #999999;
            border-color: #e5e5e5;
        }
        .grid-header-cell {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            min-height: 50px;
            padding: 0.3rem 0.2rem;
            text-align: center;
            line-height: 1.2;
        }
        .weekend-header {
            background-color: #f3f4f6;
            border-radius: 0.3rem;
        }
        /* Tablo görünümü için columns düzenlemesi */
        div[data-testid="column"] {
            border: 1px solid #e5e7eb;
            padding: 0.25rem;
        }
        div[data-testid="column"]:first-child {
            border-left: none;
            background-color: #ffffff;
        }
        /* Planning table styles - HTML table yapısı */
        .planning-table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 1rem;
            font-size: 0.9rem;
        }
        .planning-table th {
            text-align: center;
            padding: 0.5rem;
            border: 1px solid #e5e7eb;
            background: #f9fafb;
            font-weight: 600;
            min-width: 80px;
        }
        .planning-table th:first-child {
            text-align: left;
            padding: 0.75rem;
            position: sticky;
            left: 0;
            z-index: 10;
            background: #f9fafb;
        }
        .planning-table .weekend-header {
            background: #f3f4f6 !important;
        }
        .planning-table td {
            padding: 0;
            border: 1px solid #e5e7eb;
            text-align: center;
            vertical-align: middle;
            min-height: 60px;
            height: 60px;
        }
        .planning-table td:first-child {
            text-align: left;
            padding: 0.75rem;
            position: sticky;
            left: 0;
            z-index: 5;
            background: #fafafa;
            font-weight: 500;
        }
        .planning-table .weekend-cell {
            background: #f9fafb;
        }
        /* Cell link - tıklanabilir hücre */
        .cell-link {
            display: block;
            width: 100%;
            height: 100%;
            padding: 0.5rem;
            text-decoration: none;
            color: inherit;
            min-height: 60px;
            box-sizing: border-box;
        }
        .cell-link:hover {
            background-color: #f8fafc !important;
        }
        .planning-table .weekend-cell .cell-link:hover {
            background-color: #e5e7eb !important;
        }
        /* Badge stilleri */
        .table-badge {
            display: inline-block;
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
            font-size: 0.7rem;
            font-weight: 600;
            margin: 0.1rem 0;
            color: white;
        }
            border: none !important;
            background: transparent !important;
            box-shadow: none !important;
            min-height: 0 !important;
            max-height: 100% !important;
        }
        /* Boş alanları kaldır - tüm child elementler */
        .shift-cell > *:not(.cell-content) {
            margin: 0 !important;
            padding: 0 !important;
        }
        /* Personel adı ve hücrelerin hizalanması - isim hizasında vardiyalar */
        div[data-testid="column"]:first-child {
            display: flex !important;
            align-items: center !important;
            padding: 0.25rem 0.5rem !important;
            vertical-align: middle !important;
            min-height: 92px !important;
            height: 92px !important;
        }
        div[data-testid="column"]:first-child > div {
            margin: 0 !important;
            padding: 0 !important;
            width: 100%;
        }
        /* Hücre kolonlarının hizalanması - isim ile aynı hizada */
        div[data-testid="column"]:not(:first-child) {
            display: flex !important;
            align-items: center !important;
            padding: 0.25rem !important;
            vertical-align: middle !important;
            min-height: 92px !important;
            height: 92px !important;
        }
        div[data-testid="column"]:not(:first-child) > div {
            width: 100% !important;
            margin: 0 !important;
            padding: 0 !important;
        }
        /* Satırlar arası boşluğu azalt */
        div[data-testid="column"] {
            margin-bottom: 0 !important;
            padding-bottom: 0 !important;
        }
        .cell-content {
            display: flex;
            flex-direction: column;
            gap: 0.3rem;
            font-size: 0.75rem;
            line-height: 1.25;
            max-height: 100%;
            overflow: hidden;
        }
        .segment-block {
            display: flex;
            flex-direction: column;
            gap: 0.1rem;
            overflow: hidden;
        }
        .segment-top {
            display: flex;
            align-items: center;
            gap: 0.4rem;
            flex-wrap: wrap;
        }
        .segment-top.plus-sign {
            justify-content: center;
            align-items: center;
            height: 100%;
            width: 100%;
        }
        .plus-sign .type-label {
            font-size: 2rem;
            color: #9ca3af;
            font-weight: 300;
            line-height: 1;
        }
        .chip {
            padding: 0.15rem 0.45rem;
            border-radius: 999px;
            font-weight: 600;
            font-size: 0.68rem;
            white-space: nowrap;
            color: white;
            display: inline-block;
        }
        .time-range {
            font-size: 0.7rem;
            color: #111827;
            white-space: nowrap;
        }
        .type-label {
            font-size: 0.65rem;
            color: #6b7280;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .overtime {
            font-size: 0.62rem;
            color: #dc2626;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .weekend-column {
            background-color: #f9fafb !important;
        }
        .weekend-column > button {
            background-color: #f3f4f6 !important;
            border-color: #e5e7eb !important;
        }
        .work-type-multi > button {
            font-weight: 600;
            position: relative;
        }
        .work-type-multi > button::after {
            content: "●";
            font-size: 0.5rem;
            position: absolute;
            top: 2px;
            right: 4px;
        }
        .badge-readonly {
            background-color: #eef2ff;
            border-radius: 999px;
            padding: 0.15rem 0.5rem;
            display: inline-block;
            font-size: 0.75rem;
            color: #4338ca;
        }
        .readonly-banner {
            background: #fef9c3;
            border-radius: 0.5rem;
            padding: 0.5rem 0.75rem;
            border: 1px solid #fde68a;
            margin-bottom: 0.75rem;
            font-size: 0.9rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# _resolve_public_view removed - replaced by _resolve_token_access


def page_departments_people():
    st.title("Departments / People")

    st.subheader("Departmanlar")
    col1, col2 = st.columns([2, 1])
    with col1:
        new_dept_name = st.text_input("Yeni departman adı", key="new_dept_name")
    with col2:
        if st.button("Yeni departman ekle"):
            if not new_dept_name.strip():
                st.warning("Departman adı boş olamaz.")
            else:
                try:
                    create_department(new_dept_name.strip())
                    st.success("Departman eklendi.")
                    st.rerun()
                except Exception as e:  # pragma: no cover - simple feedback
                    st.error(f"Departman eklenirken hata: {e}")

    departments = list_departments()
    if not departments:
        st.info("Henüz departman yok.")
    else:
        for dept in departments:
            c1, c2 = st.columns([4, 1])
            with c1:
                st.write(f"- {dept['name']}")
            with c2:
                if st.button(
                    "Sil",
                    key=f"del_dept_{dept['id']}",
                    help="Departmanı sil (ilişkili personel varsa hata verebilir).",
                ):
                    try:
                        delete_department(dept["id"])
                        st.success("Departman silindi.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Departman silinirken hata: {e}")

    st.markdown("---")
    st.subheader("Personel Yönetimi")

    if not departments:
        st.info("Önce en az bir departman ekleyin.")
        return

    dept_options = {d["name"]: d["id"] for d in departments}

    with st.form("add_member_form"):
        st.markdown("**Yeni personel ekle**")
        tm_id = st.number_input(
            "team_member_id (int)", min_value=1, step=1, format="%d"
        )
        tm_name = st.text_input("Ad Soyad")
        dept_name = st.selectbox("Departman", list(dept_options.keys()))
        submitted = st.form_submit_button("Ekle")
        if submitted:
            if not tm_name.strip():
                st.warning("Personel adı boş olamaz.")
            else:
                try:
                    create_team_member(
                        team_member_id=int(tm_id),
                        team_member=tm_name.strip(),
                        department_id=dept_options[dept_name],
                    )
                    st.success("Personel eklendi.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Personel eklenirken hata: {e}")

    st.markdown("**Personel listesi**")
    for member in list_team_members():
        with st.expander(
            f"{member['team_member']} (ID: {member['team_member_id']}) - {member['department_name']}"
        ):
            with st.form(f"edit_member_{member['id']}"):
                new_tm_id = st.number_input(
                    "team_member_id",
                    min_value=1,
                    step=1,
                    value=int(member["team_member_id"]),
                    format="%d",
                    key=f"edit_tm_id_{member['id']}",
                )
                new_name = st.text_input(
                    "Ad Soyad",
                    value=member["team_member"],
                    key=f"edit_tm_name_{member['id']}",
                )
                new_dept_name = st.selectbox(
                    "Departman",
                    list(dept_options.keys()),
                    index=list(dept_options.values()).index(member["department_id"]),
                    key=f"edit_tm_dept_{member['id']}",
                )
                c1, c2 = st.columns(2)
                with c1:
                    save = st.form_submit_button("Kaydet")
                with c2:
                    delete_btn = st.form_submit_button("Sil")

                if save:
                    try:
                        update_team_member(
                            id_=member["id"],
                            team_member_id=int(new_tm_id),
                            team_member=new_name.strip(),
                            department_id=dept_options[new_dept_name],
                        )
                        st.success("Personel güncellendi.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Güncelleme hatası: {e}")
                if delete_btn:
                    try:
                        delete_team_member(member["id"])
                        st.success("Personel silindi.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Silme hatası: {e}")


def _shift_segment_controls(
    member_id: int,
    current_date: date,
    *,
    existing: Optional[dict] = None,
    key_prefix: str,
) -> Optional[Dict[str, Any]]:
    """
    Tek bir segment icin form kontrollerini cizer.
    'Kaydet' butonuna basilirsa payload dondurur, aksi halde None.
    """
    date_str = current_date.isoformat()
    default_work_type = existing["work_type"] if existing else WORK_TYPES[0]
    default_food = existing["food_payment"] if existing else "NO"

    # Work type seçimi: dropdown + manuel giriş
    col_wt1, col_wt2 = st.columns([3, 1])
    with col_wt1:
        work_type_choice = st.selectbox(
            "work_type",
            ["(Özel girin)"] + WORK_TYPES,
            index=(WORK_TYPES.index(default_work_type) + 1) if default_work_type in WORK_TYPES else 0,
            key=f"{key_prefix}_work_type_select",
        )
    with col_wt2:
        if work_type_choice == "(Özel girin)":
            work_type = st.text_input(
                "Özel work_type",
                value=default_work_type if default_work_type not in WORK_TYPES else "",
                key=f"{key_prefix}_work_type_custom",
                placeholder="örn: Babalık izni",
            )
            if not work_type.strip():
                st.warning("Lütfen bir work_type girin.")
                return None
            work_type = work_type.strip()
        else:
            work_type = work_type_choice
    wt = work_type
    fp = st.selectbox(
        "food_payment",
        FOOD_PAYMENT_VALUES,
        index=FOOD_PAYMENT_VALUES.index(default_food),
        key=f"{key_prefix}_food_payment",
    )

    # Saat inputlari - session_state'ten oku veya default None
    shift_start_key = f"{key_prefix}_shift_start"
    shift_end_key = f"{key_prefix}_shift_end"
    ot_start_key = f"{key_prefix}_ot_start"
    ot_end_key = f"{key_prefix}_ot_end"
    
    # Session state'ten değerleri oku veya mevcut değerleri kullan
    if shift_start_key not in st.session_state:
        if existing and existing.get("shift_start"):
            st.session_state[shift_start_key] = datetime.strptime(existing["shift_start"], "%Y-%m-%d %H:%M").time()
        else:
            st.session_state[shift_start_key] = None
    
    if shift_end_key not in st.session_state:
        if existing and existing.get("shift_end"):
            st.session_state[shift_end_key] = datetime.strptime(existing["shift_end"], "%Y-%m-%d %H:%M").time()
        else:
            st.session_state[shift_end_key] = None
    
    if ot_start_key not in st.session_state:
        if existing and existing.get("overtime_start"):
            st.session_state[ot_start_key] = datetime.strptime(existing["overtime_start"], "%Y-%m-%d %H:%M").time()
        else:
            st.session_state[ot_start_key] = None
    
    if ot_end_key not in st.session_state:
        if existing and existing.get("overtime_end"):
            st.session_state[ot_end_key] = datetime.strptime(existing["overtime_end"], "%Y-%m-%d %H:%M").time()
        else:
            st.session_state[ot_end_key] = None
    
    # OFF, Annual Leave, Report için saatleri gizle veya opsiyonel yap
    show_times = wt not in ("OFF", "Annual Leave", "Report")
    
    if show_times:
        col_times1, col_times2 = st.columns(2)
        with col_times1:
            shift_start_input = st.time_input(
                "shift_start",
                value=st.session_state[shift_start_key] or time(9, 0),
                key=shift_start_key,
            )
        with col_times2:
            shift_end_input = st.time_input(
                "shift_end",
                value=st.session_state[shift_end_key] or time(18, 0),
                key=shift_end_key,
            )
        # Temizle butonları
        clear_col1, clear_col2 = st.columns(2)
        with clear_col1:
            if st.session_state[shift_start_key] and st.button("✕ Temizle (shift_start)", key=f"{key_prefix}_clear_start"):
                st.session_state[shift_start_key] = None
                st.rerun()
        with clear_col2:
            if st.session_state[shift_end_key] and st.button("✕ Temizle (shift_end)", key=f"{key_prefix}_clear_end"):
                st.session_state[shift_end_key] = None
                st.rerun()
    else:
        # OFF/Annual Leave/Report için saatler opsiyonel, boş bırakılabilir
        col_times1, col_times2 = st.columns(2)
        with col_times1:
            shift_start_input = st.time_input(
                "shift_start (opsiyonel)",
                value=st.session_state[shift_start_key] or time(9, 0),
                key=shift_start_key,
            )
        with col_times2:
            shift_end_input = st.time_input(
                "shift_end (opsiyonel)",
                value=st.session_state[shift_end_key] or time(18, 0),
                key=shift_end_key,
            )
        # Temizle butonları
        clear_col1, clear_col2 = st.columns(2)
        with clear_col1:
            if st.session_state[shift_start_key] and st.button("✕ Temizle (shift_start)", key=f"{key_prefix}_clear_start"):
                st.session_state[shift_start_key] = None
                st.rerun()
        with clear_col2:
            if st.session_state[shift_end_key] and st.button("✕ Temizle (shift_end)", key=f"{key_prefix}_clear_end"):
                st.session_state[shift_end_key] = None
                st.rerun()

    col_ot1, col_ot2 = st.columns(2)
    with col_ot1:
        overtime_start_input = st.time_input(
            "overtime_start (opsiyonel)",
            value=st.session_state[ot_start_key] or time(18, 0),
            key=ot_start_key,
        )
    with col_ot2:
        overtime_end_input = st.time_input(
            "overtime_end (opsiyonel)",
            value=st.session_state[ot_end_key] or time(18, 0),
            key=ot_end_key,
        )
    # Overtime temizle butonları
    clear_ot_col1, clear_ot_col2 = st.columns(2)
    with clear_ot_col1:
        if st.session_state[ot_start_key] and st.button("✕ Temizle (overtime_start)", key=f"{key_prefix}_clear_ot_start"):
            st.session_state[ot_start_key] = None
            st.rerun()
    with clear_ot_col2:
        if st.session_state[ot_end_key] and st.button("✕ Temizle (overtime_end)", key=f"{key_prefix}_clear_ot_end"):
            st.session_state[ot_end_key] = None
            st.rerun()

    # Quick preset ve metin araligi
    if show_times:
        st.caption("Quick presets")
        preset_col1, preset_col2 = st.columns(2)
        with preset_col1:
            if st.button("09:00 - 18:00", key=f"{key_prefix}_preset_9_18"):
                st.session_state[shift_start_key] = time(9, 0)
                st.session_state[shift_end_key] = time(18, 0)
                st.rerun()
        with preset_col2:
            if st.button("12:00 - 21:00", key=f"{key_prefix}_preset_12_21"):
                st.session_state[shift_start_key] = time(12, 0)
                st.session_state[shift_end_key] = time(21, 0)
                st.rerun()

        interval_text = st.text_input(
            "Saat aralığı (örn. 9-18, 09:30-18:15)",
            key=f"{key_prefix}_interval",
        )
        if st.button("Text aralığını uygula", key=f"{key_prefix}_apply_interval"):
            parsed = parse_time_interval_text(interval_text)
            if parsed:
                start_t, end_t = parsed
                st.session_state[shift_start_key] = start_t
                st.session_state[shift_end_key] = end_t
                st.rerun()
            else:
                st.warning("Saat aralığı çözülemedi, formatı kontrol edin.")

    if st.button("Kaydet", key=f"{key_prefix}_save"):
        # Session state'ten değerleri al
        shift_start_val = st.session_state.get(shift_start_key)
        shift_end_val = st.session_state.get(shift_end_key)
        ot_start_val = st.session_state.get(ot_start_key)
        ot_end_val = st.session_state.get(ot_end_key)
        
        payload = {
            "date": date_str,
            "team_member_id": member_id,
            "work_type": wt,
            "food_payment": fp,
            "shift_start": compose_datetime_str(current_date, shift_start_val) if shift_start_val else None,
            "shift_end": compose_datetime_str(current_date, shift_end_val) if shift_end_val else None,
            "overtime_start": compose_datetime_str(current_date, ot_start_val) if ot_start_val else None,
            "overtime_end": compose_datetime_str(current_date, ot_end_val) if ot_end_val else None,
        }
        return payload

    return None


def _get_work_type_short(work_type: str) -> str:
    """Work type için kısa etiket döndür."""
    mapping = {
        "Office": "OF",
        "Remote": "RM",
        "Report": "RP",
        "Annual Leave": "AL",
        "OFF": "—",
    }
    # Özel work type'lar için ilk 2 harfi büyük harfle al
    if work_type not in mapping:
        return "CU"
    return mapping.get(work_type, work_type[:2].upper())


def _get_work_type_color_class(work_type: str) -> str:
    """Work type için CSS renk sınıfı döndür."""
    mapping = {
        "Office": "work-type-office",
        "Remote": "work-type-remote",
        "Report": "work-type-report",
        "Annual Leave": "work-type-leave",
        "OFF": "work-type-off",
    }
    # Özel work type'lar için varsayılan renk
    return mapping.get(work_type, "work-type-custom")


def _cell_label_for_entries(entries) -> tuple[str, str]:
    """
    Returns (label_text, color_class) tuple for cell display (admin mode - compact).
    """
    if not entries:
        return ("—", "work-type-empty")
    first = entries[0]
    work_type = first["work_type"]
    short_label = _get_work_type_short(work_type)
    color_class = _get_work_type_color_class(work_type)
    
    if len(entries) > 1:
        short_label = f"{len(entries)}"
        color_class += " work-type-multi"
    
    return (short_label, color_class)


def _format_time_range(shift_start: Optional[str], shift_end: Optional[str]) -> str:
    """Format shift time range for display."""
    if not shift_start or not shift_end:
        return ""
    try:
        start_dt = datetime.strptime(shift_start, "%Y-%m-%d %H:%M")
        end_dt = datetime.strptime(shift_end, "%Y-%m-%d %H:%M")
        return f"{start_dt.strftime('%H:%M')}–{end_dt.strftime('%H:%M')}"
    except Exception:
        return ""


def _format_overtime_range(overtime_start: Optional[str], overtime_end: Optional[str]) -> str:
    """Format overtime range for display."""
    if not overtime_start or not overtime_end:
        return ""
    try:
        start_dt = datetime.strptime(overtime_start, "%Y-%m-%d %H:%M")
        end_dt = datetime.strptime(overtime_end, "%Y-%m-%d %H:%M")
        return f"OT {start_dt.strftime('%H:%M')}–{end_dt.strftime('%H:%M')}"
    except Exception:
        return ""


def _get_work_type_color_hex(work_type: str) -> str:
    """Get hex color for work type."""
    mapping = {
        "Office": "#3b82f6",
        "Remote": "#10b981",
        "Report": "#8b5cf6",
        "Annual Leave": "#f59e0b",
        "OFF": "#6b7280",
    }
    return mapping.get(work_type, "#ec4899")  # default pink for custom


def _work_type_full_label(work_type: str) -> str:
    mapping = {
        "Office": "Office",
        "Remote": "Remote",
        "Report": "Report",
        "Annual Leave": "Annual Leave",
        "OFF": "OFF",
    }
    return mapping.get(work_type, work_type or "Custom")


def _get_work_type_display_label(work_type: str) -> str:
    """Tablo hücrelerinde gösterilecek açık etiket (badge için)."""
    mapping = {
        "Office": "Office",
        "Remote": "Remote",
        "Report": "Report",
        "Annual Leave": "Annual Leave",
        "OFF": "OFF",
    }
    # Custom work type'lar için ne girildiyse onu göster
    return mapping.get(work_type, work_type or "Custom")


def _render_table_cell_badge(entries: List[Any]) -> str:
    """
    Table cell için badge formatında HTML render.
    Boşsa boş string döner, doluysa badge(ler) döner.
    Badge metni açık yazı olacak (OF -> Office, RM -> Remote, vb.)
    """
    if not entries:
        return ""
    
    badge_parts = []
    for entry in entries:
        entry_dict = dict(entry) if hasattr(entry, "keys") else entry
        work_type = entry_dict.get("work_type", "")
        # Açık yazı kullan (kısaltma değil)
        display_label = _get_work_type_display_label(work_type)
        color_hex = _get_work_type_color_hex(work_type)
        
        shift_start = entry_dict.get("shift_start")
        shift_end = entry_dict.get("shift_end")
        time_range = _format_time_range(shift_start, shift_end)
        
        # Badge HTML - açık yazı ile
        badge_html = f'<div class="table-badge" style="background-color:{color_hex}; color:white; padding:0.2rem 0.5rem; border-radius:4px; font-size:0.7rem; font-weight:600; margin:0.1rem 0; display:inline-block;">{display_label}</div>'
        
        # Saat varsa altında küçük gri yazı
        if time_range:
            badge_html += f'<div style="font-size:0.65rem; color:#6b7280; margin-top:0.1rem;">{time_range}</div>'
        
        badge_parts.append(badge_html)
    
    # Birden fazla segment varsa alt alta göster (max 2)
    if len(badge_parts) > 1:
        return "<div style='display:flex; flex-direction:column; gap:0.2rem;'>" + "".join(badge_parts[:2]) + "</div>"
    else:
        return badge_parts[0] if badge_parts else ""


def _format_cell_value_for_aggrid(entries: List[Any]) -> str:
    """
    HTML formatında hücre değeri: renkli chip + saat + label veya boş string.
    Örnek: '<span class="chip" style="background-color:#3b82f6;">OFFICE</span> 09:00–18:00 Office'
    """
    if not entries:
        return ""
    
    html_parts = []
    for entry in entries:
        entry_dict = dict(entry) if hasattr(entry, "keys") else entry
        work_type = entry_dict.get("work_type", "")
        display_label = _get_work_type_display_label(work_type)
        color_hex = _get_work_type_color_hex(work_type)
        
        shift_start = entry_dict.get("shift_start")
        shift_end = entry_dict.get("shift_end")
        time_range = _format_time_range(shift_start, shift_end)
        
        full_label = _work_type_full_label(work_type)
        
        # HTML format: renkli chip + saat + label
        segment_html = f'<span class="cell-chip" style="background-color:{color_hex}; color:white; padding:0.15rem 0.4rem; border-radius:999px; font-size:0.7rem; font-weight:600; margin-right:0.3rem;">{display_label}</span>'
        
        if time_range:
            segment_html += f'<span style="font-size:0.75rem; margin-right:0.3rem;">{time_range}</span>'
        
        segment_html += f'<span style="font-size:0.75rem; color:#6b7280;">{full_label}</span>'
        
        html_parts.append(segment_html)
    
    # Birden fazla segment varsa, her birini ayrı satırda göster
    return "<br>".join(html_parts)


def render_cell_detailed(entries: List[Any]) -> str:
    """
    Detailed HTML renderer used in public read-only view.
    Admin grid buton label'i icin ayri bir plain-text label uretecegiz.
    """
    if not entries:
        # Public view icin bos hucre: sadece + gosterebiliriz
        return "<div class='cell-content'><div class='segment-top plus-sign'><span class='type-label' style='font-size:1.1rem;'>+</span></div></div>"

    html_parts = ['<div class="cell-content">']

    for entry in entries:
        entry_dict = dict(entry) if hasattr(entry, "keys") else entry

        work_type = entry_dict.get("work_type", "")
        short_label = _get_work_type_short(work_type)
        color_hex = _get_work_type_color_hex(work_type)
        full_label = _work_type_full_label(work_type)

        shift_start = entry_dict.get("shift_start")
        shift_end = entry_dict.get("shift_end")
        time_range = _format_time_range(shift_start, shift_end)

        overtime_start = entry_dict.get("overtime_start")
        overtime_end = entry_dict.get("overtime_end")
        ot_range = _format_overtime_range(overtime_start, overtime_end)

        html_parts.append('<div class="segment-block">')
        html_parts.append('<div class="segment-top">')
        html_parts.append(
            f'<span class="chip" style="background-color:{color_hex};">{short_label}</span>'
        )
        if time_range:
            html_parts.append(f'<span class="time-range">{time_range}</span>')
        html_parts.append("</div>")
        html_parts.append(f'<div class="type-label">{full_label}</div>')
        if ot_range:
            html_parts.append(f'<div class="overtime">{ot_range}</div>')
        html_parts.append("</div>")

    html_parts.append("</div>")
    return "".join(html_parts)


def _clear_cell_query_params():
    """Query param'lardan cell_mid ve cell_date'i temizle."""
    params = dict(st.query_params)
    if "cell_mid" in params:
        params.pop("cell_mid")
    if "cell_date" in params:
        params.pop("cell_date")
    if params != dict(st.query_params):
        st.query_params.update(params)


def _clear_modal_state():
    """Modal state'lerini temizle (query param'lar dahil)."""
    _clear_cell_query_params()
    if "modal_open" in st.session_state:
        st.session_state.modal_open = False
    if "selected_member_id" in st.session_state:
        st.session_state.selected_member_id = None
    if "selected_date" in st.session_state:
        st.session_state.selected_date = None
    if "last_open_key" in st.session_state:
        st.session_state.last_open_key = None


def _show_shift_dialog(member: dict, current_date: date, read_only: bool) -> None:
    """Seçili personel + gün için vardiyaları gösteren dialog/panel."""
    date_str_outer = current_date.isoformat()  # Closure için dış scope'ta tanımla

    def body():
        entries = list_shift_entries_for_member_and_date(member["id"], date_str_outer)

        if read_only:
            st.markdown(
                "<div class='badge-readonly'>Read-only schedule – sadece görüntüleme.</div>",
                unsafe_allow_html=True,
            )

        # "Sil (Bu günü temizle)" butonu - tüm vardiyaları sil (en üstte)
        if not read_only and entries:
            if st.button("🗑️ Sil (Bu günü temizle)", key="delete_all_shifts", type="secondary"):
                try:
                    # Tüm vardiyaları sil (tek sorgu ile)
                    deleted_count = delete_shifts_for_member_and_date(member["id"], date_str_outer)
                    
                    # Flash mesaj set et
                    st.session_state.flash_success = "Bu gün için tüm vardiyalar silindi."
                    
                    # Modal state'lerini temizle
                    _clear_modal_state()
                    
                    st.rerun()
                except Exception as ex:
                    st.error(f"Silme hatası: {ex}")

        if not entries:
            st.info("Bu gün için vardiya yok.")
        else:
            st.markdown("**Mevcut vardiyalar**")
            st.caption("Vardiyaları görüntüleyin/düzenleyin")
            for e in entries:
                row = dict(e)  # sqlite3.Row -> dict
                shift_title = row["work_type"]
                if row.get("shift_start") and row.get("shift_end"):
                    shift_title += f" | {row['shift_start'][-5:]} - {row['shift_end'][-5:]}"

                with st.expander(shift_title, expanded=False):
                    if read_only:
                        st.write(f"Work type: {row['work_type']}")
                        st.write(f"Food payment: {row['food_payment']}")
                        st.write(
                            f"Shift: {row.get('shift_start', '')} → {row.get('shift_end', '')}"
                        )
                        st.write(
                            f"Overtime: {row.get('overtime_start', '')} → {row.get('overtime_end', '')}"
                        )
                    else:
                        payload = _shift_segment_controls(
                            member_id=member["id"],
                            current_date=current_date,
                            existing=row,
                            key_prefix=f"edit_seg_{e['id']}",
                        )
                        if payload is not None:
                            val = validate_shift_payload(payload)
                            if not val.valid:
                                st.error("; ".join(val.errors))
                            else:
                                overlap = check_overlap_for_member_date(
                                    member["id"],
                                    payload["date"],
                                    payload.get("shift_start"),
                                    payload.get("shift_end"),
                                    exclude_entry_id=e["id"],
                                )
                                if not overlap.valid:
                                    st.error("; ".join(overlap.errors))
                                else:
                                    try:
                                        update_shift_entry(e["id"], payload)
                                        # Flash mesaj set et
                                        st.session_state.flash_success = "Vardiya güncellendi."
                                        # Modal state'lerini temizle
                                        _clear_modal_state()
                                        st.rerun()
                                    except Exception as ex:
                                        st.error(f"Güncelleme hatası: {ex}")

                        if st.button(
                            "Sil",
                            key=f"del_seg_{e['id']}",
                        ) and not read_only:
                            try:
                                delete_shift_entry(e["id"])
                                # Flash mesaj set et
                                st.session_state.flash_success = "Vardiya silindi."
                                # Modal state'lerini temizle
                                _clear_modal_state()
                                st.rerun()
                            except Exception as ex:
                                st.error(f"Silme hatası: {ex}")

        if not read_only:
            st.markdown("---")
            st.markdown("**+ Vardiya ekle**")
            new_payload = _shift_segment_controls(
                member_id=member["id"],
                current_date=current_date,
                existing=None,
                key_prefix="new_seg",
            )
            if new_payload is not None:
                val = validate_shift_payload(new_payload)
                if not val.valid:
                    st.error("; ".join(val.errors))
                else:
                    overlap = check_overlap_for_member_date(
                        member["id"],
                        new_payload["date"],
                        new_payload.get("shift_start"),
                        new_payload.get("shift_end"),
                    )
                    if not overlap.valid:
                        st.error("; ".join(overlap.errors))
                    else:
                        try:
                            create_shift_entry(new_payload)
                            # Flash mesaj set et (sayfa başında gösterilecek)
                            st.session_state.flash_success = "Yeni vardiya eklendi."
                            # Modal state'lerini temizle
                            _clear_modal_state()
                            st.rerun()
                        except Exception as ex:
                            st.error(f"Ekleme hatası: {ex}")

    # Streamlit versiyonuna gore dialog / experimental_dialog / inline panel
    dialog_fn = getattr(st, "dialog", None) or getattr(
        st, "experimental_dialog", None
    )
    title = f"Shift Düzenle: {member['team_member']} — {date_str_outer}"

    if dialog_fn is not None:
        @dialog_fn(title)
        def _dlg():
            body()
            # Modal içinde bir işlem yapılmadıysa (sadece X'e basıldıysa)
            # bir sonraki rerun'da state'i temizlemek için kontrol ekle
            # Ancak burada doğrudan state'i temizleyemeyiz çünkü dialog henüz kapanmadı
            # Bu yüzden state temizleme işlemi modal dışında yapılacak

        _dlg()
    else:
        st.markdown(f"### {title}")
        # Inline panel için kapat butonu ekle
        if st.button("Kapat", key="close_modal_inline"):
            _clear_modal_state()
            st.rerun()
        body()


def page_planning(
    selected_department_id: int,
    picked_date: date,
    *,
    read_only: bool,
    public_ctx: Optional[Dict[str, Any]] = None,
    access_token: Optional[str] = None,
):
    st.title("Planning")

    if read_only:
        st.markdown(
            "<div class='readonly-banner'>Bu görünüm paylaşılmış, sadece okuma amaçlıdır. "
            "Saatleri değiştiremezsiniz.</div>",
            unsafe_allow_html=True,
        )

    # Public view sadece departman bazlı
    members = list_team_members(department_id=selected_department_id)

    if not members:
        st.info("Bu departmanda henüz personel yok.")
        return

    col_view, col_date = st.columns([1, 2])
    with col_view:
        view_mode = st.radio(
            "Görünüm",
            ["Ay görünümü", "Hafta görünümü"],
            horizontal=True,
            key="view_mode",
        )
    with col_date:
        picked_date = st.date_input(
            "Ay (herhangi bir gününü seçin)",
            value=picked_date,
            key="planning_month",
        )

    if view_mode == "Ay görünümü":
        year = picked_date.year
        month = picked_date.month
        num_days = calendar.monthrange(year, month)[1]
        days = [date(year, month, d) for d in range(1, num_days + 1)]
    else:
        start_week, _ = week_range_for_date(picked_date)
        days = [start_week + pd.Timedelta(days=i) for i in range(7)]  # type: ignore

    st.markdown("---")
    
    # Vardiya tipleri legend (açık yazılarla)
    st.markdown(
        """
        <div style="margin-bottom: 1rem; padding: 0.5rem; background: #f9fafb; border-radius: 0.5rem; font-size: 0.85rem;">
        <strong>Vardiya Tipleri:</strong> 
        <span style="background: #3b82f6; color: white; padding: 0.15rem 0.4rem; border-radius: 999px; margin: 0 0.3rem;">Office</span>
        <span style="background: #10b981; color: white; padding: 0.15rem 0.4rem; border-radius: 999px; margin: 0 0.3rem;">Remote</span>
        <span style="background: #8b5cf6; color: white; padding: 0.15rem 0.4rem; border-radius: 999px; margin: 0 0.3rem;">Report</span>
        <span style="background: #f59e0b; color: white; padding: 0.15rem 0.4rem; border-radius: 999px; margin: 0 0.3rem;">Annual Leave</span>
        <span style="background: #ec4899; color: white; padding: 0.15rem 0.4rem; border-radius: 999px; margin: 0 0.3rem;">Custom</span>
        <span style="background: #6b7280; color: white; padding: 0.15rem 0.4rem; border-radius: 999px; margin: 0 0.3rem;">OFF</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    
    st.subheader("Vardiya Planı")

    # Flash mesaj kontrolü (sayfa başında)
    flash_success = st.session_state.get("flash_success")
    if flash_success:
        st.success(flash_success)
        st.session_state.flash_success = None

    # Query param kontrolü - cell tıklaması için (one-shot event gate)
    # ÖNEMLİ: Eğer flash_success varsa (yani başka bir tab'dan gelindi), query param'ları yok say
    query_params = st.query_params
    cell_mid = query_params.get("cell_mid", None) if not flash_success else None
    cell_date = query_params.get("cell_date", None) if not flash_success else None
    
    # One-shot event gate: sadece yeni query param geldiyse modal aç
    if cell_mid and cell_date and not read_only and not flash_success:
        try:
            member_id = int(cell_mid)
            clicked_date = datetime.strptime(cell_date, "%Y-%m-%d").date()
            current_key = f"{member_id}|{cell_date}"
            last_open_key = st.session_state.get("last_open_key", None)
            modal_open = st.session_state.get("modal_open", False)
            
            # Sadece yeni bir tıklama ise modal aç (last_open_key farklı veya yok)
            if current_key != last_open_key:
                clicked_member = next((m for m in members if m["id"] == member_id), None)
                if clicked_member:
                    # State'leri set et
                    st.session_state.selected_member_id = member_id
                    st.session_state.selected_date = clicked_date
                    st.session_state.modal_open = True
                    st.session_state.last_open_key = current_key
                    
                    # Query param'ları hemen temizle (bir daha tetiklenmesin)
                    _clear_cell_query_params()
        except (ValueError, TypeError):
            pass
    
    # Modal sadece modal_open == True iken render edilsin
    modal_open = st.session_state.get("modal_open", False)
    if modal_open and not read_only:
        selected_member_id = st.session_state.get("selected_member_id")
        selected_date = st.session_state.get("selected_date")
        
        # Query param yoksa ve modal_open true ise, modal kapatıldı demektir (X'e basıldı)
        # State'leri temizle
        if not cell_mid and not cell_date:
            _clear_modal_state()
        elif selected_member_id and selected_date:
            # Modal açık, render et
            clicked_member = next((m for m in members if m["id"] == selected_member_id), None)
            if clicked_member:
                _show_shift_dialog(clicked_member, selected_date, read_only)
    
    # Gün isimleri mapping
    day_names_tr = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]
    
    # HTML Table yapısı
    table_html = '<table class="planning-table" style="width:100%; border-collapse:collapse; margin-top:1rem;">'
    
    # Header row
    table_html += '<thead><tr>'
    table_html += '<th style="text-align:left; padding:0.75rem; border:1px solid #e5e7eb; background:#f9fafb; font-weight:600; position:sticky; left:0; z-index:10;">Personel</th>'
    for d in days:
        is_weekend = d.weekday() >= 5
        day_name = day_names_tr[d.weekday()]
        header_class = "weekend-header" if is_weekend else ""
        header_style = "background:#f3f4f6;" if is_weekend else "background:#f9fafb;"
        
        if view_mode == "Ay görünümü":
            header_text = f"<strong>{d.day}</strong><br><small>{day_name}</small>"
        else:
            header_text = f"<strong>{d.day}/{d.month}</strong><br><small>{day_name}</small>"
        
        table_html += f'<th class="{header_class}" style="text-align:center; padding:0.5rem; border:1px solid #e5e7eb; {header_style} font-weight:600; min-width:80px;">{header_text}</th>'
    table_html += '</tr></thead>'
    
    # PERFORMANCE: Batch query - tüm vardiyaları tek seferde çek
    start_date = min(days).isoformat()
    end_date = max(days).isoformat()
    all_shifts = list_shift_entries_for_department_and_range(selected_department_id, start_date, end_date)
    
    # Index: member_id (DB id) -> date -> [entries]
    shifts_index = {}
    for shift in all_shifts:
        db_member_id = shift.get("team_member_id")  # DB id (integer)
        shift_date = shift.get("date")
        if not shift_date or not db_member_id:
            continue
        if db_member_id not in shifts_index:
            shifts_index[db_member_id] = {}
        if shift_date not in shifts_index[db_member_id]:
            shifts_index[db_member_id][shift_date] = []
        shifts_index[db_member_id][shift_date].append(shift)
    
    # Body rows
    table_html += '<tbody>'
    for member in members:
        table_html += '<tr>'
        # Personel adı
        table_html += f'<td style="text-align:left; padding:0.75rem; border:1px solid #e5e7eb; background:#fafafa; position:sticky; left:0; z-index:5; font-weight:500;">{member["team_member"]}</td>'
        
        # Gün hücreleri
        for d in days:
            date_str = d.isoformat()
            # Index'ten çek (tek query'den)
            entries = shifts_index.get(member["id"], {}).get(date_str, [])
            is_weekend = d.weekday() >= 5
            cell_class = "weekend-cell" if is_weekend else "normal-cell"
            cell_style = "background:#f9fafb;" if is_weekend else ""
            
            # Badge içeriği
            badge_content = _render_table_cell_badge(entries)
            
            # Tıklanabilir cell (admin'de) - <a href> link kullan (token ile)
            if not read_only and access_token:
                member_id = member["id"]
                link_href = f"?token={access_token}&cell_mid={member_id}&cell_date={date_str}"
                # Hücre içeriği link olarak render et (boş olsa bile tıklanabilir)
                cell_content = f'<a class="cell-link" href="{link_href}" target="_self">{badge_content if badge_content else "&nbsp;"}</a>'
                cell_html = f'<td class="{cell_class}" style="padding:0; border:1px solid #e5e7eb; {cell_style} text-align:center; vertical-align:middle; min-height:60px; height:60px;">{cell_content}</td>'
            else:
                # Viewer veya token yoksa: tıklanamaz, sadece görüntüleme
                cell_html = f'<td class="{cell_class}" style="padding:0.5rem; border:1px solid #e5e7eb; {cell_style} text-align:center; vertical-align:middle; min-height:60px; height:60px;">{badge_content if badge_content else ""}</td>'
            
            table_html += cell_html
        
        table_html += '</tr>'
    table_html += '</tbody></table>'
    
    st.markdown(table_html, unsafe_allow_html=True)


def page_export():
    departments = list_departments()
    if not departments:
        st.info("Önce en az bir departman ekleyin.")
        return

    dept_map = {d["name"]: d["id"] for d in departments}
    selected_dept_name = st.selectbox("Departman", list(dept_map.keys()), key="export_dept")
    selected_dept_id = dept_map[selected_dept_name]

    st.title(f"Export (Departman: {selected_dept_name})")
    st.caption("Export sadece seçili departmanı kapsar. Ek filtre yoktur.")

    today = date.today()
    default_start = date(today.year, today.month, 1)
    default_end = date(
        today.year, today.month, calendar.monthrange(today.year, today.month)[1]
    )
    date_range = st.date_input(
        "Tarih aralığı",
        value=(default_start, default_end),
    )

    if isinstance(date_range, tuple):
        start_date, end_date = date_range
    else:
        start_date = end_date = date_range

    if st.button("Verileri getir ve CSV hazırla"):
        if start_date > end_date:
            st.error("Başlangıç tarihi bitiş tarihinden büyük olamaz.")
            return

        rows = export_csv_rows(
            department_id=selected_dept_id,
            start_date=start_date,
            end_date=end_date,
        )
        if not rows:
            st.info("Seçilen filtrelerle kayıt bulunamadı.")
            return

        # CSV kolon sırası sabit
        df = pd.DataFrame(rows, columns=EXPORT_COLUMNS)
        st.dataframe(df, use_container_width=True)

        csv_bytes = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "CSV indir",
            data=csv_bytes,
            file_name="shifts_export.csv",
            mime="text/csv",
        )


def page_bulk_operations(selected_dept_id: Optional[int], picked_date: date):
    """Toplu vardiya girişi ve kopyalama."""
    st.title("Toplu İşlemler")
    
    if selected_dept_id is None:
        st.info("Önce bir departman seçin (Planning sekmesinden).")
        return
    
    members = list_team_members(department_id=selected_dept_id)
    if not members:
        st.info("Bu departmanda personel yok.")
        return
    
    st.subheader("1. Toplu Vardiya Girişi")
    st.write("Seçili personellere aynı tarih aralığında aynı vardiyayı ekleyin.")
    
    selected_member_ids = st.multiselect(
        "Personeller (birden fazla seçebilirsiniz)",
        options=[(m["id"], f"{m['team_member']} (ID: {m['team_member_id']})") for m in members],
        format_func=lambda x: x[1],
        key="bulk_members",
    )
    
    col_date1, col_date2 = st.columns(2)
    with col_date1:
        bulk_start_date = st.date_input("Başlangıç tarihi", value=picked_date, key="bulk_start")
    with col_date2:
        bulk_end_date = st.date_input("Bitiş tarihi", value=picked_date, key="bulk_end")
    
    # Work type ve saatler
    bulk_work_type = st.selectbox("work_type", ["(Özel girin)"] + WORK_TYPES, key="bulk_work_type")
    if bulk_work_type == "(Özel girin)":
        bulk_work_type = st.text_input("Özel work_type", key="bulk_work_type_custom", placeholder="örn: Babalık izni")
    
    bulk_food_payment = st.selectbox("food_payment", FOOD_PAYMENT_VALUES, key="bulk_food")
    
    col_bulk_t1, col_bulk_t2 = st.columns(2)
    with col_bulk_t1:
        bulk_shift_start = st.time_input("shift_start (opsiyonel)", value=None, key="bulk_shift_start")
    with col_bulk_t2:
        bulk_shift_end = st.time_input("shift_end (opsiyonel)", value=None, key="bulk_shift_end")
    
    col_bulk_ot1, col_bulk_ot2 = st.columns(2)
    with col_bulk_ot1:
        bulk_ot_start = st.time_input("overtime_start (opsiyonel)", value=None, key="bulk_ot_start")
    with col_bulk_ot2:
        bulk_ot_end = st.time_input("overtime_end (opsiyonel)", value=None, key="bulk_ot_end")
    
    if st.button("Toplu Vardiya Ekle", key="bulk_add"):
        if not selected_member_ids:
            st.warning("En az bir personel seçin.")
        elif bulk_start_date > bulk_end_date:
            st.error("Başlangıç tarihi bitiş tarihinden büyük olamaz.")
        elif not bulk_work_type or not bulk_work_type.strip():
            st.warning("Work type girin.")
        else:
            work_type = bulk_work_type.strip()
            added_count = 0
            errors = []
            
            current_date = bulk_start_date
            while current_date <= bulk_end_date:
                date_str = current_date.isoformat()
                
                for member_id_tuple in selected_member_ids:
                    member_id = member_id_tuple[0]
                    try:
                        payload = {
                            "date": date_str,
                            "team_member_id": member_id,
                            "work_type": work_type,
                            "food_payment": bulk_food_payment,
                            "shift_start": compose_datetime_str(current_date, bulk_shift_start) if bulk_shift_start else None,
                            "shift_end": compose_datetime_str(current_date, bulk_shift_end) if bulk_shift_end else None,
                            "overtime_start": compose_datetime_str(current_date, bulk_ot_start) if bulk_ot_start else None,
                            "overtime_end": compose_datetime_str(current_date, bulk_ot_end) if bulk_ot_end else None,
                        }
                        
                        val = validate_shift_payload(payload)
                        if not val.valid:
                            errors.append(f"{date_str}: {', '.join(val.errors)}")
                            continue
                        
                        overlap = check_overlap_for_member_date(
                            member_id,
                            date_str,
                            payload.get("shift_start"),
                            payload.get("shift_end"),
                        )
                        if not overlap.valid:
                            errors.append(f"{date_str}: {', '.join(overlap.errors)}")
                            continue
                        
                        create_shift_entry(payload)
                        added_count += 1
                    except Exception as e:
                        errors.append(f"{date_str}: {str(e)}")
                
                # Basit tarih artırma
                from datetime import timedelta
                current_date = current_date + timedelta(days=1)
            
            if added_count > 0:
                st.success(f"{added_count} vardiya eklendi.")
            if errors:
                st.error(f"Hatalar: {len(errors)} kayıt eklenemedi.")
                for err in errors[:10]:  # İlk 10 hatayı göster
                    st.text(err)
    
    st.markdown("---")
    st.subheader("2. Vardiya Kopyalama")
    st.write("Bir personelin vardiyasını diğer personellere kopyalayın. Kaynak tarih aralığını farklı tarihlere kopyalayabilirsiniz.")
    
    source_member = st.selectbox(
        "Kaynak personel",
        options=[(m["id"], f"{m['team_member']} (ID: {m['team_member_id']})") for m in members],
        format_func=lambda x: x[1],
        key="copy_source",
    )
    
    target_member_ids = st.multiselect(
        "Hedef personeller",
        options=[(m["id"], f"{m['team_member']} (ID: {m['team_member_id']})") for m in members if m["id"] != source_member[0]],
        format_func=lambda x: x[1],
        key="copy_targets",
    )
    
    st.markdown("**Kaynak tarih aralığı (kopyalanacak vardiyalar):**")
    col_source_date1, col_source_date2 = st.columns(2)
    with col_source_date1:
        source_start_date = st.date_input("Kaynak başlangıç tarihi", value=picked_date, key="copy_source_start")
    with col_source_date2:
        source_end_date = st.date_input("Kaynak bitiş tarihi", value=picked_date, key="copy_source_end")
    
    st.markdown("**Hedef tarih aralığı (vardiyaların kopyalanacağı tarihler):**")
    col_target_date1, col_target_date2 = st.columns(2)
    with col_target_date1:
        target_start_date = st.date_input("Hedef başlangıç tarihi", value=picked_date, key="copy_target_start")
    with col_target_date2:
        target_end_date = st.date_input("Hedef bitiş tarihi", value=picked_date, key="copy_target_end")
    
    if st.button("Vardiyaları Kopyala", key="bulk_copy"):
        if not target_member_ids:
            st.warning("En az bir hedef personel seçin.")
        elif source_start_date > source_end_date:
            st.error("Kaynak başlangıç tarihi bitiş tarihinden büyük olamaz.")
        elif target_start_date > target_end_date:
            st.error("Hedef başlangıç tarihi bitiş tarihinden büyük olamaz.")
        else:
            # Tarih aralığı uzunluklarını kontrol et
            source_range = (source_end_date - source_start_date).days + 1
            target_range = (target_end_date - target_start_date).days + 1
            
            if source_range != target_range:
                st.error(f"Kaynak ve hedef tarih aralıkları aynı uzunlukta olmalı. Kaynak: {source_range} gün, Hedef: {target_range} gün")
            else:
                copied_count = 0
                errors = []
                
                from datetime import timedelta
                source_date = source_start_date
                target_date = target_start_date
                day_offset = 0
                
                while source_date <= source_end_date and target_date <= target_end_date:
                    source_date_str = source_date.isoformat()
                    target_date_str = target_date.isoformat()
                    
                    source_entries = list_shift_entries_for_member_and_date(source_member[0], source_date_str)
                    
                    for entry in source_entries:
                        entry_dict = dict(entry)
                        for target_member_id_tuple in target_member_ids:
                            target_member_id = target_member_id_tuple[0]
                            try:
                                # Tarih offset'ini shift_start/end'e de uygula
                                shift_start = None
                                shift_end = None
                                overtime_start = None
                                overtime_end = None
                                
                                if entry_dict.get("shift_start"):
                                    # shift_start datetime'ını parse et, tarihini değiştir
                                    from datetime import datetime
                                    src_dt = datetime.strptime(entry_dict["shift_start"], "%Y-%m-%d %H:%M")
                                    shift_start = datetime.combine(target_date, src_dt.time()).strftime("%Y-%m-%d %H:%M")
                                
                                if entry_dict.get("shift_end"):
                                    src_dt = datetime.strptime(entry_dict["shift_end"], "%Y-%m-%d %H:%M")
                                    shift_end = datetime.combine(target_date, src_dt.time()).strftime("%Y-%m-%d %H:%M")
                                
                                if entry_dict.get("overtime_start"):
                                    src_dt = datetime.strptime(entry_dict["overtime_start"], "%Y-%m-%d %H:%M")
                                    overtime_start = datetime.combine(target_date, src_dt.time()).strftime("%Y-%m-%d %H:%M")
                                
                                if entry_dict.get("overtime_end"):
                                    src_dt = datetime.strptime(entry_dict["overtime_end"], "%Y-%m-%d %H:%M")
                                    overtime_end = datetime.combine(target_date, src_dt.time()).strftime("%Y-%m-%d %H:%M")
                                
                                payload = {
                                    "date": target_date_str,
                                    "team_member_id": target_member_id,
                                    "work_type": entry_dict["work_type"],
                                    "food_payment": entry_dict["food_payment"],
                                    "shift_start": shift_start,
                                    "shift_end": shift_end,
                                    "overtime_start": overtime_start,
                                    "overtime_end": overtime_end,
                                }
                                
                                val = validate_shift_payload(payload)
                                if not val.valid:
                                    errors.append(f"{source_date_str}→{target_date_str}: {', '.join(val.errors)}")
                                    continue
                                
                                overlap = check_overlap_for_member_date(
                                    target_member_id,
                                    target_date_str,
                                    payload.get("shift_start"),
                                    payload.get("shift_end"),
                                )
                                if not overlap.valid:
                                    errors.append(f"{source_date_str}→{target_date_str}: {', '.join(overlap.errors)}")
                                    continue
                                
                                create_shift_entry(payload)
                                copied_count += 1
                            except Exception as e:
                                errors.append(f"{source_date_str}→{target_date_str}: {str(e)}")
                    
                    source_date = source_date + timedelta(days=1)
                    target_date = target_date + timedelta(days=1)
                
                if copied_count > 0:
                    st.success(f"{copied_count} vardiya kopyalandı.")
                if errors:
                    st.error(f"Hatalar: {len(errors)} kayıt kopyalanamadı.")
                    for err in errors[:10]:
                        st.text(err)
    
    st.markdown("---")
    st.subheader("3. Toplu Vardiya Silme")
    st.write("Seçili personellerin belirtilen tarih aralığındaki vardiyalarını toplu olarak silin.")
    
    delete_member_ids = st.multiselect(
        "Personeller (birden fazla seçebilirsiniz)",
        options=[(m["id"], f"{m['team_member']} (ID: {m['team_member_id']})") for m in members],
        format_func=lambda x: x[1],
        key="delete_members",
    )
    
    col_delete_date1, col_delete_date2 = st.columns(2)
    with col_delete_date1:
        delete_start_date = st.date_input("Silinecek başlangıç tarihi", value=picked_date, key="delete_start")
    with col_delete_date2:
        delete_end_date = st.date_input("Silinecek bitiş tarihi", value=picked_date, key="delete_end")
    
    # Work type filtresi (opsiyonel)
    delete_work_type_filter = st.selectbox(
        "Work type filtresi (opsiyonel - boş bırakırsanız tüm work type'lar silinir)",
        ["(Tümü)"] + WORK_TYPES + ["(Özel girin)"],
        key="delete_work_type_filter",
    )
    
    if delete_work_type_filter == "(Özel girin)":
        delete_work_type_custom = st.text_input("Özel work_type", key="delete_work_type_custom", placeholder="örn: Babalık izni")
        delete_work_type_filter = delete_work_type_custom if delete_work_type_custom else None
    elif delete_work_type_filter == "(Tümü)":
        delete_work_type_filter = None
    
    # Önizleme: Silinecek kayıt sayısı
    if delete_member_ids and delete_start_date and delete_end_date:
        preview_count = 0
        current_date = delete_start_date
        while current_date <= delete_end_date:
            date_str = current_date.isoformat()
            for member_id_tuple in delete_member_ids:
                member_id = member_id_tuple[0]
                entries = list_shift_entries_for_member_and_date(member_id, date_str)
                if delete_work_type_filter:
                    entries = [e for e in entries if dict(e).get("work_type") == delete_work_type_filter]
                preview_count += len(entries)
            from datetime import timedelta
            current_date = current_date + timedelta(days=1)
        
        if preview_count > 0:
            st.info(f"⚠️ **Önizleme:** {preview_count} vardiya kaydı silinecek.")
        else:
            st.info("Seçilen kriterlere uygun vardiya kaydı bulunamadı.")
    
    if st.button("Toplu Vardiya Sil", key="bulk_delete", type="primary"):
        if not delete_member_ids:
            st.warning("En az bir personel seçin.")
        elif delete_start_date > delete_end_date:
            st.error("Başlangıç tarihi bitiş tarihinden büyük olamaz.")
        else:
            deleted_count = 0
            errors = []
            
            current_date = delete_start_date
            while current_date <= delete_end_date:
                date_str = current_date.isoformat()
                
                for member_id_tuple in delete_member_ids:
                    member_id = member_id_tuple[0]
                    try:
                        entries = list_shift_entries_for_member_and_date(member_id, date_str)
                        
                        # Work type filtresi uygula
                        if delete_work_type_filter:
                            entries = [e for e in entries if dict(e).get("work_type") == delete_work_type_filter]
                        
                        # Her entry'yi sil
                        for entry in entries:
                            entry_dict = dict(entry) if hasattr(entry, "keys") else entry
                            entry_id = entry_dict.get("id")
                            if entry_id:
                                delete_shift_entry(entry_id)
                                deleted_count += 1
                    except Exception as e:
                        errors.append(f"{date_str} - {member_id}: {str(e)}")
                
                from datetime import timedelta
                current_date = current_date + timedelta(days=1)
            
            if deleted_count > 0:
                st.success(f"✅ {deleted_count} vardiya kaydı silindi.")
                st.rerun()
            if errors:
                st.error(f"Hatalar: {len(errors)} kayıt silinemedi.")
                for err in errors[:10]:
                    st.text(err)


def page_share(department_id: int, current_token: str):
    """Paylaşım linkleri oluşturma sayfası (admin only)."""
    st.title("Paylaşım")
    st.write(
        "Buradan departman için admin (düzenleme) ve viewer (sadece görüntüleme) linkleri oluşturabilirsiniz. "
        "Her link 1 kere üretilir ve değişmez."
    )
    
    departments = list_departments()
    current_dept = next((d for d in departments if d["id"] == department_id), None)
    if not current_dept:
        st.error("Departman bulunamadı.")
        return
    
    st.subheader(f"Departman: {current_dept['name']}")
    if not _get_app_base_url():
        st.info(
            "Tam link (https://...) göstermek için `APP_BASE_URL` ayarlayın. "
            "Örn: `APP_BASE_URL = \"https://your-app.streamlit.app\"`"
        )
    
    # Admin link
    st.markdown("### 👑 Admin Link (Düzenleme)")
    admin_link = get_access_link_by_department_and_role(department_id, "admin")
    if admin_link:
        st.markdown(f"**Departman:** `{current_dept['name']}`  \n**Rol:** `ADMIN`")
        st.code(_build_access_url(admin_link["token"]), language="text")
        if st.button("📋 Admin Link'i Kopyala", key="copy_admin_link"):
            st.write("✅ Kopyalandı! (Manuel olarak kopyalayın)")
        st.caption("Bu link ile departman vardiyalarını düzenleyebilirsiniz.")
    else:
        if st.button("🔗 Admin Link Oluştur", key="create_admin_link"):
            try:
                admin_link = create_access_link(department_id, "admin", f"{current_dept['name']} | Admin")
                st.code(_build_access_url(admin_link["token"]), language="text")
                st.success("Admin link oluşturuldu!")
                st.rerun()
            except Exception as e:
                st.error(f"Hata: {e}")
    
    st.markdown("---")
    
    # Viewer link
    st.markdown("### 👁️ Viewer Link (Sadece Görüntüleme)")
    viewer_link = get_access_link_by_department_and_role(department_id, "viewer")
    if viewer_link:
        st.markdown(f"**Departman:** `{current_dept['name']}`  \n**Rol:** `VIEWER`")
        st.code(_build_access_url(viewer_link["token"]), language="text")
        if st.button("📋 Viewer Link'i Kopyala", key="copy_viewer_link"):
            st.write("✅ Kopyalandı! (Manuel olarak kopyalayın)")
        st.caption("Bu link ile departman vardiyalarını sadece görüntüleyebilirsiniz.")
    else:
        if st.button("🔗 Viewer Link Oluştur", key="create_viewer_link"):
            try:
                viewer_link = create_access_link(department_id, "viewer", f"{current_dept['name']} | Viewer")
                st.code(_build_access_url(viewer_link["token"]), language="text")
                st.success("Viewer link oluşturuldu!")
                st.rerun()
            except Exception as e:
                st.error(f"Hata: {e}")



def render_public_view(public_ctx: Dict[str, Any]):
    """Public read-only view - edit UI asla render edilmez."""
    st.set_page_config(
        page_title="Shift Planner - Read Only",
        layout="wide",
        initial_sidebar_state="collapsed"
    )
    _inject_global_css()
    
    departments = list_departments()
    if not departments:
        st.error("Departman bulunamadı.")
        st.stop()
    
    dept_map = {d["name"]: d["id"] for d in departments}
    scope_dept_id = public_ctx["scope_id"]
    scope_dept = next((d for d in departments if d["id"] == scope_dept_id), None)
    
    if not scope_dept:
        st.error("Geçersiz departman.")
        st.stop()
    
    # Read-only banner
    st.markdown(
        "<div class='readonly-banner'><strong>Read-only schedule</strong> - Bu görünüm paylaşılmış, sadece okuma amaçlıdır. "
        "Saatleri değiştiremezsiniz.</div>",
        unsafe_allow_html=True,
    )
    
    st.title(f"Planning - {scope_dept['name']}")
    
    # Sidebar minimal
    st.sidebar.title("Shift Planner")
    st.sidebar.markdown(f"**Departman:** {scope_dept['name']}")
    
    today = date.today()
    picked_date = st.sidebar.date_input(
        "Ay (herhangi bir gününü seçin)",
        value=today,
        key="public_planning_month",
    )
    
    # Planning page - read-only
    page_planning(
        selected_department_id=scope_dept_id,
        picked_date=picked_date,
        read_only=True,
        public_ctx=public_ctx,
    )
    
    st.stop()  # Rest of app never renders


def main():
    _inject_global_css()
    
    # Initialize database (after Streamlit is initialized so st.secrets is available)
    try:
        init_db()
    except ValueError as e:
        st.error(f"❌ Database Configuration Error:\n\n{e}")
        st.stop()
        return
    
    # Token-based access check - MUST be first
    access_ctx = _resolve_token_access()
    
    if not access_ctx["has_access"]:
        render_access_denied(access_ctx.get("error", "Token required"))
        return

    # Normal app flow - only reached if not public view
    st.set_page_config(page_title="Shift Planner", layout="wide")
    
    # Sidebar: departman ve tarih secimi
    st.sidebar.title("Shift Planner")

    departments = list_departments()
    if not departments:
        st.sidebar.info("Önce en az bir departman ekleyin.")
        selected_dept_id = None
        selected_dept_name = None
    # Normal app flow - token is valid
    st.set_page_config(page_title="Shift Planner", layout="wide")
    
    token = access_ctx["token"]
    department_id = access_ctx["department_id"]
    role = access_ctx["role"]  # "admin" or "viewer"
    is_admin = role == "admin"
    is_viewer = role == "viewer"
    
    # Get department info
    departments = list_departments()
    current_dept = next((d for d in departments if d["id"] == department_id), None)
    
    if not current_dept:
        st.error("Departman bulunamadı.")
        st.stop()
    
    # Sidebar: departman bilgisi (sabit, token'dan geliyor)
    st.sidebar.title("Shift Planner")
    st.sidebar.markdown(f"**Departman:** {current_dept['name']}")
    st.sidebar.markdown(f"**Rol:** {'👑 Admin' if is_admin else '👁️ Viewer'}")
    
    if is_viewer:
        st.sidebar.info("🔒 Read-only modu - Sadece görüntüleme")
    
    today = date.today()
    picked_date = today

    # Tabs - viewer'da sadece Planning, admin'de tüm sekmeler
    if is_admin:
        tabs = st.tabs(["Planning", "People", "Export", "Paylaşım", "Toplu İşlemler"])
    else:
        tabs = st.tabs(["Planning"])

    # ÖNEMLİ: Planning tab'ı dışındaki tab'lara geçildiğinde query param'ları hemen temizle
    # Bu, Planning tab'ı render edilmeden önce yapılmalı
    # Ayrıca, eğer modal açık değilse ve query param'lar varsa, temizle (başka tab'dan gelindi demektir)
    query_params_check = st.query_params
    if (query_params_check.get("cell_mid") or query_params_check.get("cell_date")) and not st.session_state.get("modal_open", False):
        _clear_cell_query_params()

    with tabs[0]:
        page_planning(
            selected_department_id=department_id,
            picked_date=picked_date,
            read_only=is_viewer,
            public_ctx=None,
            access_token=token,
        )

    if is_admin:
        with tabs[1]:
            _clear_modal_state()
            _clear_cell_query_params()  # Query param'ları da temizle
            page_departments_people()

        with tabs[2]:
            _clear_modal_state()
            _clear_cell_query_params()
            page_export()

        with tabs[3]:
            _clear_modal_state()
            _clear_cell_query_params()
            page_share(department_id, token)

        with tabs[4]:
            _clear_modal_state()
            _clear_cell_query_params()  # Toplu işlemler sekmesine geçildiğinde query param'ları temizle
            page_bulk_operations(department_id, picked_date)


if __name__ == "__main__":
    main()


