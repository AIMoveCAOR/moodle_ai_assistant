"""Site admins see every course in Moodle without being enrolled in any.

Moodle grants site administrators access through the `siteadmins` config value,
not through `mdl_user_enrolments` — an admin normally has no enrolment rows and no
role assignments at all. `get_enrolled_course_ids` read only the enrolments table,
so it returned `[]` for them, and `similarity_search_all_courses` treats `[]` as
"allow nothing" (an empty allow-list is still an allow-list). Every course question
an admin asked reached the relevance gate with zero course chunks and was refused:

    similarity_search_all_courses: user enrolled in no indexed courses
    retrieve_final_dual: 2 candidates (annotations=2, course=0)

`None` is the value that means "no enrolment filter", so admins get that. It is
kept distinct from `[]` deliberately: a genuinely unenrolled ordinary user must
still see nothing, which is what test_unenrolled_user_still_sees_nothing pins.
"""

from unittest.mock import MagicMock, patch

import pytest


def _make_service():
    from services.silo_service import SiloService
    return SiloService(db_password="test")


def _conn_returning(rows_by_query):
    """A pymysql connection whose cursor answers based on the SQL it is given."""
    cursor = MagicMock()
    state = {}

    def execute(sql, params=()):
        for needle, rows in rows_by_query.items():
            if needle in sql:
                state["rows"] = rows
                return
        state["rows"] = []

    cursor.execute.side_effect = execute
    cursor.fetchall.side_effect = lambda: state.get("rows", [])
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn


def test_site_admin_gets_no_enrolment_filter():
    """A site admin must come back as None — 'every indexed course'."""
    svc = _make_service()
    conn = _conn_returning({"siteadmins": [("2,3,19,280",)], "mdl_user_enrolments": []})
    with patch("services.silo_service.pymysql.connect", return_value=conn):
        assert svc.get_enrolled_course_ids(280) is None


def test_unenrolled_user_still_sees_nothing():
    """The fix must not turn an ordinary unenrolled user into an admin."""
    svc = _make_service()
    conn = _conn_returning({"siteadmins": [("2,3,19,280",)], "mdl_user_enrolments": []})
    with patch("services.silo_service.pymysql.connect", return_value=conn):
        assert svc.get_enrolled_course_ids(777) == []


def test_enrolled_user_unchanged():
    svc = _make_service()
    conn = _conn_returning({"siteadmins": [("2,3,19,280",)], "mdl_user_enrolments": [(101,), (109,)]})
    with patch("services.silo_service.pymysql.connect", return_value=conn):
        assert svc.get_enrolled_course_ids(42) == ["101", "109"]


def test_admin_id_is_not_matched_as_substring():
    """'28' must not match the '280' entry — ids are compared per element."""
    svc = _make_service()
    conn = _conn_returning({"siteadmins": [("2,3,19,280",)], "mdl_user_enrolments": []})
    with patch("services.silo_service.pymysql.connect", return_value=conn):
        assert svc.get_enrolled_course_ids(28) == []


def test_siteadmins_handles_blank_and_spaced_entries():
    svc = _make_service()
    conn = _conn_returning({"siteadmins": [(" 2, ,280 ",)], "mdl_user_enrolments": []})
    with patch("services.silo_service.pymysql.connect", return_value=conn):
        assert svc.is_site_admin(280) is True
        assert svc.is_site_admin(9) is False


def test_missing_siteadmins_row_is_not_fatal():
    """An absent config row must degrade to 'not an admin', not raise."""
    svc = _make_service()
    conn = _conn_returning({"mdl_user_enrolments": []})
    with patch("services.silo_service.pymysql.connect", return_value=conn):
        assert svc.is_site_admin(280) is False


# ── the pipeline's domain narrowing must cope with None ──────────────────────

def test_domain_narrowing_of_admin_scope_yields_the_domain_courses():
    """A craft button must still narrow an admin, not widen back to everything."""
    from pipeline import narrow_to_domain
    assert narrow_to_domain(None, ["83", "101"]) == ["83", "101"]


def test_domain_narrowing_intersects_for_ordinary_users():
    from pipeline import narrow_to_domain
    assert narrow_to_domain(["101", "55"], ["83", "101"]) == ["101"]


def test_domain_narrowing_cannot_widen_beyond_enrolment():
    """The intersection is the access-control guarantee — pin it."""
    from pipeline import narrow_to_domain
    assert narrow_to_domain([], ["83", "101"]) == []
