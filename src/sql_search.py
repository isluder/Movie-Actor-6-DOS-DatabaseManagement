"""Run a single bounded SQL query through a read-only SQLite connection."""
from pathlib import Path
import sqlite3
import time

ROW_LIMIT = 500
DEFAULT_SQL = 'SELECT id, title FROM films ORDER BY title LIMIT 25;'


def search(path, sql):
    if not sql.strip():
        raise ValueError('Enter a SELECT query.')
    if len(sql) > 20_000:
        raise ValueError('Use at most 20,000 characters.')
    conn = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
    try:
        conn.execute('PRAGMA query_only=ON')
        conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1_000_000)
        conn.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 100)
        allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}

        def authorize(action, arg1, arg2, database, trigger):
            if action not in allowed:
                return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_FUNCTION and (arg2 or '').lower() == 'load_extension':
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        conn.set_authorizer(authorize)
        deadline = time.monotonic() + 2
        conn.set_progress_handler(lambda: time.monotonic() > deadline, 1000)
        cursor = conn.execute(sql)
        if not cursor.description:
            raise ValueError('Only queries that return data are allowed.')
        columns = [item[0] for item in cursor.description]
        rows = []
        truncated = False
        for row in cursor:
            if len(rows) == ROW_LIMIT:
                truncated = True
                break
            rows.append([None if value is None else str(value)[:2000] for value in row])
        return dict(columns=columns, rows=rows, truncated=truncated, limit=ROW_LIMIT)
    except sqlite3.Error as error:
        raise ValueError('Query could not run: ' + str(error) + '. Use one read-only SELECT query; execution is limited to 2 seconds.') from error
    finally:
        conn.close()


EXAMPLES = [
    dict(label='Highest rated', sql="""SELECT f.id, v.title, v.vote_average, v.vote_count
FROM films AS f
JOIN film_values AS v ON v.movie_id = f.id
WHERE v.source = 'movies' AND v.vote_count >= 1000
ORDER BY v.vote_average DESC, v.vote_count DESC
LIMIT 50;"""),
    dict(label='Box-office shortfalls', sql="""SELECT movie_id, title, budget, revenue,
       budget - revenue AS shortfall
FROM film_values
WHERE source = 'movies'
  AND budget >= 10000000 AND revenue > 0 AND revenue < budget
ORDER BY shortfall DESC
LIMIT 50;"""),
    dict(label='Actor credits', sql="""SELECT DISTINCT p.name, f.title, cr.role, cr.source
FROM people AS p
JOIN cast_roles AS cr ON cr.actor_id = p.id
JOIN films AS f ON f.id = cr.movie_id
WHERE p.name LIKE '%Tom Hanks%'
ORDER BY f.title, cr.source
LIMIT 50;"""),
    dict(label='Source differences', sql="""SELECT a.movie_id, a.title,
       a.vote_average AS movies_rating, b.vote_average AS tmdb_rating,
       a.budget AS movies_budget, b.budget AS tmdb_budget,
       a.revenue AS movies_revenue, b.revenue AS tmdb_revenue
FROM film_values AS a
JOIN film_values AS b ON b.movie_id = a.movie_id
WHERE a.source = 'movies' AND b.source = 'tmdb'
  AND (a.vote_average IS NOT b.vote_average
       OR a.budget IS NOT b.budget OR a.revenue IS NOT b.revenue)
ORDER BY a.title
LIMIT 50;"""),
    dict(label='Movies by genre', sql="""SELECT g.name AS genre, COUNT(DISTINCT fg.movie_id) AS movie_count
FROM catalog_genres AS g
JOIN film_genres AS fg ON fg.genre_id = g.id
GROUP BY g.id, g.name
ORDER BY movie_count DESC;"""),
    dict(label='Manual entries', sql="""SELECT movie_id, title, budget, revenue, vote_average, vote_count
FROM film_values
WHERE source = 'manual'
ORDER BY title
LIMIT 50;"""),
]
