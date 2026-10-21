"""
Database access layer for Film Reel-ational Data.
Provides SQLite connection handling, schema initialization, multi-table queries,
CRUD operations, and analytical queries ('Bombed at the Box Office' & 'Hidden Gems').
"""

import os
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "movies.db")
SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql")


def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    """Create a SQLite connection with row factory and foreign key enforcement enabled."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: str = DB_PATH) -> None:
    """Initialize the SQLite database tables and indexes from schema.sql."""
    with get_connection(db_path) as conn:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.commit()


def get_dashboard_stats(db_path: str = DB_PATH) -> Dict[str, Any]:
    """Return high-level counts and aggregates across all relational tables."""
    with get_connection(db_path) as conn:
        stats = {}
        stats["movie_count"] = conn.execute("SELECT COUNT(*) FROM Movies").fetchone()[0]
        stats["actor_count"] = conn.execute("SELECT COUNT(*) FROM Actors").fetchone()[0]
        stats["cast_links"] = conn.execute("SELECT COUNT(*) FROM Movie_Cast").fetchone()[0]
        stats["genre_count"] = conn.execute("SELECT COUNT(*) FROM Genre_Types").fetchone()[0]
        stats["avg_rating"] = conn.execute(
            "SELECT ROUND(COALESCE(AVG(vote_average), 0), 2) FROM Movies WHERE vote_count > 0"
        ).fetchone()[0]
        stats["bombs_count"] = conn.execute(
            "SELECT COUNT(*) FROM Movies WHERE budget >= 10000000 AND revenue > 0 AND revenue < budget"
        ).fetchone()[0]
        stats["gems_count"] = conn.execute(
            "SELECT COUNT(*) FROM Movies WHERE vote_average >= 7.5 AND vote_count BETWEEN 50 AND 5000"
        ).fetchone()[0]
        return stats


def get_all_genres(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Return all available genres ordered alphabetically."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT gt.genre_id, gt.genre_name, COUNT(g.movie_id) AS movie_count
            FROM Genre_Types gt
            LEFT JOIN Genres g ON gt.genre_id = g.genre_id
            GROUP BY gt.genre_id, gt.genre_name
            ORDER BY gt.genre_name ASC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_actors(limit: int = 500, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Return actors ordered by name for dropdown selection."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT a.actor_id, a.actor_name, COUNT(mc.movie_id) AS movie_count
            FROM Actors a
            LEFT JOIN Movie_Cast mc ON a.actor_id = mc.actor_id
            GROUP BY a.actor_id, a.actor_name
            ORDER BY a.actor_name ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def search_movies(
    title_query: str = "",
    actor_query: str = "",
    character_query: str = "",
    genre_id: Optional[int] = None,
    min_rating: Optional[float] = None,
    max_rating: Optional[float] = None,
    min_budget: Optional[int] = None,
    sort_by: str = "vote_average_desc",
    limit: int = 100,
    db_path: str = DB_PATH,
) -> Tuple[List[Dict[str, Any]], str]:
    """
    Multi-table query searching across Movies, Actors, Movie_Cast, Genres, and Genre_Types.
    Returns (list_of_movie_dicts, executed_sql_preview).
    """
    conditions = ["1=1"]
    params: List[Any] = []

    if title_query.strip():
        conditions.append("m.title LIKE ?")
        params.append(f"%{title_query.strip()}%")

    if actor_query.strip():
        conditions.append(
            """EXISTS (
                SELECT 1 FROM Movie_Cast mc_filter
                JOIN Actors a_filter ON mc_filter.actor_id = a_filter.actor_id
                WHERE mc_filter.movie_id = m.movie_id
                  AND a_filter.actor_name LIKE ?
            )"""
        )
        params.append(f"%{actor_query.strip()}%")

    if character_query.strip():
        conditions.append(
            """EXISTS (
                SELECT 1 FROM Movie_Cast mc_char
                WHERE mc_char.movie_id = m.movie_id
                  AND mc_char.character_name LIKE ?
            )"""
        )
        params.append(f"%{character_query.strip()}%")

    if genre_id is not None:
        conditions.append(
            """EXISTS (
                SELECT 1 FROM Genres g_filter
                WHERE g_filter.movie_id = m.movie_id
                  AND g_filter.genre_id = ?
            )"""
        )
        params.append(genre_id)

    if min_rating is not None:
        conditions.append("m.vote_average >= ?")
        params.append(min_rating)

    if max_rating is not None:
        conditions.append("m.vote_average <= ?")
        params.append(max_rating)

    if min_budget is not None:
        conditions.append("m.budget >= ?")
        params.append(min_budget)

    sort_map = {
        "vote_average_desc": "(CASE WHEN m.vote_count >= 50 THEN 1 ELSE 0 END) DESC, m.vote_average DESC, m.vote_count DESC",
        "vote_average_asc": "(CASE WHEN m.vote_count >= 50 THEN 1 ELSE 0 END) DESC, m.vote_average ASC, m.vote_count DESC",
        "revenue_desc": "m.revenue DESC",
        "budget_desc": "m.budget DESC",
        "profit_desc": "(m.revenue - m.budget) DESC",
        "profit_asc": "(m.revenue - m.budget) ASC",
        "title_asc": "m.title ASC",
        "vote_count_desc": "m.vote_count DESC",
    }
    order_clause = sort_map.get(sort_by, "m.vote_average DESC, m.vote_count DESC")
    where_clause = " AND ".join(conditions)

    query = f"""
        SELECT
            m.movie_id,
            m.title,
            m.budget,
            m.revenue,
            (m.revenue - m.budget) AS net_profit,
            m.vote_average,
            m.vote_count,
            GROUP_CONCAT(DISTINCT gt.genre_name) AS genres,
            GROUP_CONCAT(DISTINCT a.actor_name) AS cast_names
        FROM Movies m
        LEFT JOIN Genres g ON m.movie_id = g.movie_id
        LEFT JOIN Genre_Types gt ON g.genre_id = gt.genre_id
        LEFT JOIN Movie_Cast mc ON m.movie_id = mc.movie_id
        LEFT JOIN Actors a ON mc.actor_id = a.actor_id
        WHERE {where_clause}
        GROUP BY m.movie_id
        ORDER BY {order_clause}
        LIMIT ?
    """
    params.append(limit)

    with get_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows], query.strip()


def get_movie_details(movie_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """Retrieve a single movie along with its full cast list and genre list."""
    with get_connection(db_path) as conn:
        movie_row = conn.execute(
            """
            SELECT
                movie_id,
                title,
                budget,
                revenue,
                (revenue - budget) AS net_profit,
                CASE
                    WHEN budget > 0 THEN ROUND(((CAST(revenue AS REAL) - budget) / budget) * 100, 1)
                    ELSE NULL
                END AS roi_percent,
                vote_average,
                vote_count
            FROM Movies
            WHERE movie_id = ?
            """,
            (movie_id,),
        ).fetchone()

        if not movie_row:
            return None

        movie = dict(movie_row)

        genres = conn.execute(
            """
            SELECT gt.genre_id, gt.genre_name
            FROM Genres g
            JOIN Genre_Types gt ON g.genre_id = gt.genre_id
            WHERE g.movie_id = ?
            ORDER BY gt.genre_name ASC
            """,
            (movie_id,),
        ).fetchall()
        movie["genres"] = [dict(g) for g in genres]
        movie["genre_ids"] = [g["genre_id"] for g in genres]

        cast = conn.execute(
            """
            SELECT a.actor_id, a.actor_name, mc.character_name
            FROM Movie_Cast mc
            JOIN Actors a ON mc.actor_id = a.actor_id
            WHERE mc.movie_id = ?
            ORDER BY a.actor_name ASC
            """,
            (movie_id,),
        ).fetchall()
        movie["cast"] = [dict(c) for c in cast]

        return movie


# ============================================================================
# CRUD Operations (Add, Edit, Remove Entries Across Tables)
# ============================================================================

def add_movie(
    title: str,
    budget: int,
    revenue: int,
    vote_average: float,
    vote_count: int,
    genre_ids: List[int],
    cast_entries: List[Tuple[str, str]],
    movie_id: Optional[int] = None,
    db_path: str = DB_PATH,
) -> int:
    """
    Insert a new movie into Movies, link its Genres, and create/link Actors in Movie_Cast.
    cast_entries is a list of (actor_name, character_name) tuples.
    Returns the newly created movie_id.
    """
    with get_connection(db_path) as conn:
        cur = conn.cursor()
        if movie_id is not None:
            cur.execute(
                """
                INSERT INTO Movies (movie_id, title, budget, revenue, vote_average, vote_count)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (movie_id, title.strip(), budget, revenue, vote_average, vote_count),
            )
            new_movie_id = movie_id
        else:
            cur.execute(
                """
                INSERT INTO Movies (title, budget, revenue, vote_average, vote_count)
                VALUES (?, ?, ?, ?, ?)
                """,
                (title.strip(), budget, revenue, vote_average, vote_count),
            )
            new_movie_id = cur.lastrowid

        for gid in set(genre_ids):
            cur.execute(
                "INSERT OR IGNORE INTO Genres (movie_id, genre_id) VALUES (?, ?)",
                (new_movie_id, gid),
            )

        for actor_name, character_name in cast_entries:
            actor_name = actor_name.strip()
            character_name = character_name.strip() or "Unknown Role"
            if not actor_name:
                continue
            existing_actor = cur.execute(
                "SELECT actor_id FROM Actors WHERE LOWER(actor_name) = LOWER(?)",
                (actor_name,),
            ).fetchone()
            if existing_actor:
                actor_id = existing_actor["actor_id"]
            else:
                cur.execute("INSERT INTO Actors (actor_name) VALUES (?)", (actor_name,))
                actor_id = cur.lastrowid

            cur.execute(
                """
                INSERT OR REPLACE INTO Movie_Cast (movie_id, actor_id, character_name)
                VALUES (?, ?, ?)
                """,
                (new_movie_id, actor_id, character_name),
            )

        conn.commit()
        return new_movie_id


def update_movie(
    movie_id: int,
    title: str,
    budget: int,
    revenue: int,
    vote_average: float,
    vote_count: int,
    genre_ids: List[int],
    db_path: str = DB_PATH,
) -> bool:
    """Update an existing movie's attributes and synchronize its genres."""
    with get_connection(db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE Movies
            SET title = ?, budget = ?, revenue = ?, vote_average = ?, vote_count = ?
            WHERE movie_id = ?
            """,
            (title.strip(), budget, revenue, vote_average, vote_count, movie_id),
        )
        if cur.rowcount == 0:
            return False

        cur.execute("DELETE FROM Genres WHERE movie_id = ?", (movie_id,))
        for gid in set(genre_ids):
            cur.execute(
                "INSERT OR IGNORE INTO Genres (movie_id, genre_id) VALUES (?, ?)",
                (movie_id, gid),
            )

        conn.commit()
        return True


def delete_movie(movie_id: int, db_path: str = DB_PATH) -> bool:
    """
    Delete a movie by movie_id.
    ON DELETE CASCADE automatically removes associated rows in Movie_Cast and Genres.
    """
    with get_connection(db_path) as conn:
        cur = conn.execute("DELETE FROM Movies WHERE movie_id = ?", (movie_id,))
        conn.commit()
        return cur.rowcount > 0


def add_or_update_cast_member(
    movie_id: int, actor_name: str, character_name: str, db_path: str = DB_PATH
) -> None:
    """Add an actor to a movie's cast (creating the Actor row if needed) or update character_name."""
    actor_name = actor_name.strip()
    character_name = character_name.strip() or "Uncredited"
    if not actor_name:
        return

    with get_connection(db_path) as conn:
        cur = conn.cursor()
        existing = cur.execute(
            "SELECT actor_id FROM Actors WHERE LOWER(actor_name) = LOWER(?)",
            (actor_name,),
        ).fetchone()
        if existing:
            actor_id = existing["actor_id"]
        else:
            cur.execute("INSERT INTO Actors (actor_name) VALUES (?)", (actor_name,))
            actor_id = cur.lastrowid

        cur.execute(
            """
            INSERT OR REPLACE INTO Movie_Cast (movie_id, actor_id, character_name)
            VALUES (?, ?, ?)
            """,
            (movie_id, actor_id, character_name),
        )
        conn.commit()


def remove_cast_member(movie_id: int, actor_id: int, db_path: str = DB_PATH) -> bool:
    """Remove an actor from a movie's cast."""
    with get_connection(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM Movie_Cast WHERE movie_id = ? AND actor_id = ?",
            (movie_id, actor_id),
        )
        conn.commit()
        return cur.rowcount > 0


# ============================================================================
# Milestone Analytical Features:
# 1. "Bombed at the Box Office"
# 2. "Hidden Gems"
# ============================================================================

def get_box_office_bombs(
    min_budget: int = 10_000_000,
    genre_id: Optional[int] = None,
    sort_by: str = "net_loss_desc",
    limit: int = 50,
    db_path: str = DB_PATH,
) -> Tuple[List[Dict[str, Any]], str]:
    """
    Identify movies that 'Bombed at the Box Office':
    - Filters movies with a significant production budget (budget >= min_budget)
      where box office revenue failed to recoup the budget (revenue < budget and revenue > 0).
    - Computes Net Loss ($), Return on Investment (ROI %), and Revenue-to-Budget ratio.
    """
    conditions = [
        "m.budget >= ?",
        "m.revenue > 0",
        "m.revenue < m.budget",
    ]
    params: List[Any] = [min_budget]

    if genre_id is not None:
        conditions.append(
            """EXISTS (
                SELECT 1 FROM Genres g_filter
                WHERE g_filter.movie_id = m.movie_id AND g_filter.genre_id = ?
            )"""
        )
        params.append(genre_id)

    sort_map = {
        "net_loss_desc": "(m.budget - m.revenue) DESC",
        "roi_asc": "((CAST(m.revenue AS REAL) - m.budget) / m.budget) ASC",
        "rating_asc": "m.vote_average ASC",
        "budget_desc": "m.budget DESC",
    }
    order_clause = sort_map.get(sort_by, "(m.budget - m.revenue) DESC")
    where_clause = " AND ".join(conditions)

    query = f"""
        SELECT
            m.movie_id,
            m.title,
            m.budget,
            m.revenue,
            (m.budget - m.revenue) AS net_loss,
            ROUND(((CAST(m.revenue AS REAL) - m.budget) / m.budget) * 100, 1) AS roi_percent,
            ROUND((CAST(m.revenue AS REAL) / m.budget) * 100, 1) AS recouped_percent,
            m.vote_average,
            m.vote_count,
            GROUP_CONCAT(DISTINCT gt.genre_name) AS genres,
            GROUP_CONCAT(DISTINCT a.actor_name) AS cast_names
        FROM Movies m
        LEFT JOIN Genres g ON m.movie_id = g.movie_id
        LEFT JOIN Genre_Types gt ON g.genre_id = gt.genre_id
        LEFT JOIN Movie_Cast mc ON m.movie_id = mc.movie_id
        LEFT JOIN Actors a ON mc.actor_id = a.actor_id
        WHERE {where_clause}
        GROUP BY m.movie_id
        ORDER BY {order_clause}
        LIMIT ?
    """
    params.append(limit)

    with get_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows], query.strip()


def get_hidden_gems(
    min_rating: float = 7.4,
    min_votes: int = 50,
    max_votes: int = 4500,
    max_budget: Optional[int] = 35_000_000,
    genre_id: Optional[int] = None,
    sort_by: str = "gem_score_desc",
    limit: int = 50,
    db_path: str = DB_PATH,
) -> Tuple[List[Dict[str, Any]], str]:
    """
    Identify 'Hidden Gems':
    - High critical/audience acclaim (vote_average >= min_rating)
    - Statistically reliable sample size (vote_count >= min_votes)
    - Overlooked by mainstream blockbuster audiences (vote_count <= max_votes)
    - Optional cap on production budget (budget <= max_budget)
    - Computes a 'Gem Score' rewarding high ratings with lower mainstream exposure.
    """
    conditions = [
        "m.vote_average >= ?",
        "m.vote_count >= ?",
        "m.vote_count <= ?",
    ]
    params: List[Any] = [min_rating, min_votes, max_votes]

    if max_budget is not None and max_budget > 0:
        conditions.append("m.budget <= ?")
        params.append(max_budget)

    if genre_id is not None:
        conditions.append(
            """EXISTS (
                SELECT 1 FROM Genres g_filter
                WHERE g_filter.movie_id = m.movie_id AND g_filter.genre_id = ?
            )"""
        )
        params.append(genre_id)

    sort_map = {
        "gem_score_desc": "gem_score DESC, m.vote_average DESC",
        "rating_desc": "m.vote_average DESC, m.vote_count ASC",
        "votes_asc": "m.vote_count ASC, m.vote_average DESC",
        "roi_desc": "CASE WHEN m.budget > 0 THEN (CAST(m.revenue AS REAL) / m.budget) ELSE 0 END DESC",
    }
    order_clause = sort_map.get(sort_by, "gem_score DESC, m.vote_average DESC")
    where_clause = " AND ".join(conditions)

    query = f"""
        SELECT
            m.movie_id,
            m.title,
            m.budget,
            m.revenue,
            m.vote_average,
            m.vote_count,
            ROUND(
                m.vote_average * (1.0 + (1.0 - (CAST(m.vote_count AS REAL) / (? + 1))) * 0.25),
                2
            ) AS gem_score,
            CASE
                WHEN m.budget > 0 AND m.revenue > 0
                THEN ROUND(((CAST(m.revenue AS REAL) - m.budget) / m.budget) * 100, 1)
                ELSE NULL
            END AS roi_percent,
            GROUP_CONCAT(DISTINCT gt.genre_name) AS genres,
            GROUP_CONCAT(DISTINCT a.actor_name) AS cast_names
        FROM Movies m
        LEFT JOIN Genres g ON m.movie_id = g.movie_id
        LEFT JOIN Genre_Types gt ON g.genre_id = gt.genre_id
        LEFT JOIN Movie_Cast mc ON m.movie_id = mc.movie_id
        LEFT JOIN Actors a ON mc.actor_id = a.actor_id
        WHERE {where_clause}
        GROUP BY m.movie_id
        ORDER BY {order_clause}
        LIMIT ?
    """
    # First param in SELECT is max_votes for normalizing the gem_score
    full_params = [max_votes] + params + [limit]

    with get_connection(db_path) as conn:
        rows = conn.execute(query, full_params).fetchall()
        return [dict(r) for r in rows], query.strip()
