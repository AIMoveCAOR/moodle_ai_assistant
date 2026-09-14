"""Per-user access scope resolver — queries Moodle DB for cohort membership
and course enrolments. Results are cached in-memory for 60 seconds."""

import logging
import os
import time
from typing import Optional

import pymysql
import pymysql.cursors

logger = logging.getLogger(__name__)

_COHORT_QUERY = """
    SELECT DISTINCT cm.cohortid
    FROM mdl_cohort_members cm
    WHERE cm.userid = %s
"""

_ENROL_QUERY = """
    SELECT DISTINCT e.courseid
    FROM mdl_user_enrolments ue
    JOIN mdl_enrol e ON e.id = ue.enrolid
    WHERE ue.userid = %s
      AND ue.status = 0
      AND e.status = 0
"""

_CATEGORY_COURSES_QUERY = """
    SELECT id
    FROM mdl_course
    WHERE category = %s
"""

# Moodle keeps its site administrators in a single comma-separated config value,
# not in mdl_role_assignments — an admin typically has no role assignment and no
# enrolment row anywhere. See get_enrolled_course_ids for why that matters here.
_SITEADMINS_QUERY = """
    SELECT value
    FROM mdl_config
    WHERE name = 'siteadmins'
"""


class SiloService:
    """Resolves per-user access scope from the Moodle MySQL DB.

    Both methods cache their results for ``_cache_ttl`` seconds (default 60)
    keyed by user_id.  Raises on DB failure — callers must treat that as 503.
    """

    def __init__(
        self,
        db_host: str = "localhost",
        db_user: str = "moodleuser",
        db_password: Optional[str] = None,
        db_name: str = "moodle",
        cache_ttl: float = 60.0,
    ):
        self._db_host = db_host
        self._db_user = db_user
        self._db_password = db_password or os.getenv("MOODLE_DB_PASSWORD", "")
        self._db_name = db_name
        self._cache_ttl = cache_ttl
        self._cohort_cache: dict[int, tuple[list[int], float]] = {}
        self._course_cache: dict[int, tuple[list[str], float]] = {}
        self._category_course_cache: dict[int, tuple[list[str], float]] = {}
        self._siteadmin_cache: tuple[Optional[set[str]], float] = (None, 0.0)

    def _connect(self):
        return pymysql.connect(
            host=self._db_host,
            user=self._db_user,
            password=self._db_password,
            database=self._db_name,
            cursorclass=pymysql.cursors.Cursor,
            connect_timeout=5,
        )

    def get_allowed_cohorts(self, user_id: int) -> list[int]:
        """Return Moodle cohort IDs the user belongs to."""
        cached, ts = self._cohort_cache.get(user_id, (None, 0.0))
        if cached is not None and (time.time() - ts) < self._cache_ttl:
            return list(cached)

        conn = None
        try:
            conn = self._connect()
            with conn.cursor() as cur:
                cur.execute(_COHORT_QUERY, (user_id,))
                rows = cur.fetchall()
        finally:
            if conn is not None:
                conn.close()

        result = [row[0] for row in rows]
        self._cohort_cache[user_id] = (result, time.time())
        logger.debug(f"SiloService: user {user_id} cohorts={result}")
        return result

    def _siteadmin_ids(self, cur=None) -> set[str]:
        """The `siteadmins` id set, cached for ``_cache_ttl`` like everything else.

        Takes an open cursor when the caller already has one, so resolving a
        user's scope stays a single connection rather than two.
        """
        cached, ts = self._siteadmin_cache
        if cached is not None and (time.time() - ts) < self._cache_ttl:
            return cached

        if cur is not None:
            cur.execute(_SITEADMINS_QUERY)
            rows = cur.fetchall()
        else:
            conn = None
            try:
                conn = self._connect()
                with conn.cursor() as own:
                    own.execute(_SITEADMINS_QUERY)
                    rows = own.fetchall()
            finally:
                if conn is not None:
                    conn.close()

        raw = rows[0][0] if rows and rows[0] and rows[0][0] else ""
        result = {part.strip() for part in str(raw).split(",") if part.strip()}
        self._siteadmin_cache = (result, time.time())
        return result

    def is_site_admin(self, user_id: int) -> bool:
        """True if the user is listed in Moodle's `siteadmins` config value.

        The value is a comma-separated list of user ids ("2,3,19,280"). Compared
        element-wise, never as a substring, so user 28 does not match 280. A
        missing or unreadable row means "not an admin" — the safe direction.
        """
        return str(user_id) in self._siteadmin_ids()

    def get_enrolled_course_ids(self, user_id: int) -> Optional[list[str]]:
        """Return active Moodle course IDs the user is enrolled in.

        Returns ``None`` — meaning *no enrolment filter*, every indexed course —
        for site administrators, who reach every course in Moodle without an
        enrolment row and would otherwise resolve to ``[]``. Callers pass this
        straight to ``similarity_search_all_courses(allowed_course_ids=...)``,
        where ``None`` skips the filter and ``[]`` allows nothing; an ordinary
        user enrolled in nothing must keep getting ``[]``.
        """
        cached, ts = self._course_cache.get(user_id, (None, 0.0))
        if cached is not None and (time.time() - ts) < self._cache_ttl:
            return list(cached)

        conn = None
        try:
            conn = self._connect()
            with conn.cursor() as cur:
                if str(user_id) in self._siteadmin_ids(cur):
                    logger.debug(
                        f"SiloService: user {user_id} is a site admin — no course filter"
                    )
                    return None
                cur.execute(_ENROL_QUERY, (user_id,))
                rows = cur.fetchall()
        finally:
            if conn is not None:
                conn.close()

        result = [str(row[0]) for row in rows]
        self._course_cache[user_id] = (result, time.time())
        logger.debug(f"SiloService: user {user_id} courses={result}")
        return result

    def get_course_ids_by_category(self, category_id: int) -> list[str]:
        """Return Moodle course IDs belonging to the given course category.

        Used to narrow retrieval to a student's selected craft domain (see
        DOMAIN_MAP in services/rag_service.py) — independent of enrolment.
        """
        cached, ts = self._category_course_cache.get(category_id, (None, 0.0))
        if cached is not None and (time.time() - ts) < self._cache_ttl:
            return list(cached)

        conn = None
        try:
            conn = self._connect()
            with conn.cursor() as cur:
                cur.execute(_CATEGORY_COURSES_QUERY, (category_id,))
                rows = cur.fetchall()
        finally:
            if conn is not None:
                conn.close()

        result = [str(row[0]) for row in rows]
        self._category_course_cache[category_id] = (result, time.time())
        logger.debug(f"SiloService: category {category_id} courses={result}")
        return result
