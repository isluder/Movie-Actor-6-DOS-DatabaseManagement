"""Explicitly closed SQLite transactions and source-aware catalog queries."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import uuid

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = str(BASE_DIR / 'movies.db')
SCHEMA_VERSION = '3'
SOURCES = {'movies': 'The Movies Dataset', 'tmdb': 'TMDB 5000', 'demo': 'Demo', 'manual': 'Manual entries'}
GEMS = dict(min_rating=7.4, min_votes=50, max_votes=4500, max_budget=35_000_000)
CATALOG_TABLES = ['film_genres','cast_roles','film_values','catalog_genres','people','films','catalog_meta']

@contextmanager
def connection(db_path=DB_PATH):
    conn = sqlite3.connect(str(db_path), timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()

get_connection = connection

def init_db(db_path=DB_PATH):
    with connection(db_path) as c:
        if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='catalog_meta'").fetchone():
            if version(c)!='uninitialized' and schema_version(c)!=SCHEMA_VERSION:
                raise ValueError('Older catalog schema: run src/ingest_data.py rebuild --dataset both --confirm.')
        c.executescript((BASE_DIR / 'schema.sql').read_text())

def version(c):
    r = c.execute("SELECT value FROM catalog_meta WHERE key='version'").fetchone()
    return r[0] if r else 'uninitialized'

def schema_version(c):
    row=c.execute("SELECT value FROM catalog_meta WHERE key='schema_version'").fetchone()
    return row[0] if row else None


def bump_version(c):
    c.execute("INSERT INTO catalog_meta VALUES('version',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (uuid.uuid4().hex,))

def dictionaries(rows):
    return [dict(r) for r in rows]

def genres(c):
    return dictionaries(c.execute('SELECT * FROM catalog_genres ORDER BY name'))

def cast_preview(c,movie_id,source):
    """Prefer the selected source's credit order, with each performer shown once."""
    rows=c.execute("""SELECT p.id,p.name FROM cast_roles cr JOIN people p ON p.id=cr.actor_id
        WHERE cr.movie_id=? ORDER BY (cr.source=?) DESC,cr.source,cr.credit_order,p.id""",(movie_id,source))
    seen=set();out=[]
    for row in rows:
        if row['id'] not in seen:
            seen.add(row['id']);out.append(dict(row))
            if len(out)==3:break
    return out


def suggestions(c, text):
    if not text.strip():
        return []
    # Prefix lookups use indexed names, substring matches remain supported.
    return dictionaries(c.execute('''SELECT p.id,p.name,COUNT(DISTINCT cr.movie_id) movie_count
        FROM people p LEFT JOIN cast_roles cr ON cr.actor_id=p.id
        WHERE p.name LIKE ?
        GROUP BY p.id ORDER BY (p.name LIKE ?) DESC,p.name,p.id LIMIT 20''',
        ('%'+text.strip()+'%',text.strip()+'%')))

# Ambiguous rows within one source remain visible for comparison, but do not
# supply numerical values to filters, summaries or financial calculations.
METRICS = """WITH chosen AS (
 SELECT movie_id,source,MIN(title) title,COUNT(*) variants,
 CASE WHEN COUNT(*)=1 THEN MIN(budget) END budget,
 CASE WHEN COUNT(*)=1 THEN MIN(revenue) END revenue,
 CASE WHEN COUNT(*)=1 THEN MIN(vote_average) END vote_average,
 CASE WHEN COUNT(*)=1 THEN MIN(vote_count) END vote_count
 FROM film_values WHERE source=:source GROUP BY movie_id,source
), metrics AS (
 SELECT f.id,f.title display_title,m.title,m.budget,m.revenue,m.vote_average,m.vote_count,m.variants,
 CASE WHEN m.budget>0 AND m.revenue>0 THEN m.revenue-m.budget END net_profit,
 CASE WHEN m.budget>0 AND m.revenue>0 THEN 100.0*(m.revenue-m.budget)/m.budget END roi_percent
 FROM films f LEFT JOIN chosen m ON f.id=m.movie_id
) """

def query_movies(c, page_type, f):
    p = dict(f)
    conditions = ['1=1']
    if f.get('title'):
        conditions.append('EXISTS(SELECT 1 FROM film_values v WHERE v.movie_id=m.id AND v.title LIKE :title_pattern) OR m.display_title LIKE :title_pattern')
        conditions[-1] = '('+conditions[-1]+')'
        p['title_pattern']='%'+f['title']+'%'
    if f.get('actor') or f.get('actor_id') or f.get('character'):
        cast_conditions=['cr.movie_id=m.id']
        if f.get('actor'):
            cast_conditions.append('EXISTS(SELECT 1 FROM people p WHERE p.id=cr.actor_id AND p.name LIKE :actor_pattern)')
            p['actor_pattern']='%'+f['actor']+'%'
        if f.get('actor_id'):
            cast_conditions.append('cr.actor_id=:actor_id')
        if f.get('character'):
            cast_conditions.append('cr.role LIKE :character_pattern')
            p['character_pattern']='%'+f['character']+'%'
        conditions.append('EXISTS(SELECT 1 FROM cast_roles cr WHERE '+' AND '.join(cast_conditions)+')')
    if f.get('genre_id'):
        conditions.append('EXISTS(SELECT 1 FROM film_genres g WHERE g.movie_id=m.id AND g.genre_id=:genre_id)')
    numeric = page_type in ('gems','bombs') or any(f.get(k) is not None for k in ('min_rating','max_rating','min_budget'))
    if numeric:
        conditions.append('m.variants=1')
    for key,col,op in [('min_rating','vote_average','>='),('max_rating','vote_average','<='),('min_budget','budget','>=')]:
        if f.get(key) is not None:
            conditions.append(f'm.{col}{op}:{key}')
    if page_type=='gems':
        conditions += ['m.vote_count BETWEEN :min_votes AND :max_votes','m.budget>0']
        if f.get('max_budget') is not None:
            conditions.append('m.budget<=:max_budget')
    if page_type=='bombs':
        conditions += ['m.budget>0','m.revenue>0','m.revenue<m.budget']
    sorts={'rating':'m.vote_average','title':'COALESCE(m.title,m.display_title) COLLATE NOCASE',
           'budget':'m.budget','revenue':'m.revenue','votes':'m.vote_count','revenue_minus_budget':'m.net_profit',
           'shortfall':'(-m.net_profit)','roi':'m.roi_percent','gem_score':'gem_score'}
    direction={'asc':'ASC','desc':'DESC'}[f['sort_order']]
    where=' AND '.join(conditions)
    base=METRICS+' SELECT {select} FROM metrics m WHERE '+where
    counts=dict(c.execute(base.format(select='''COUNT(*) total,
        COALESCE(SUM(CASE WHEN m.net_profit<0 THEN -m.net_profit ELSE 0 END),0) total_shortfall,
        AVG(m.roi_percent) avg_roi,AVG(m.vote_average) average_rating,
        AVG(NULLIF(m.budget,0)) average_budget,SUM(NULLIF(m.revenue,0)) total_revenue'''),p).fetchone())
    excluded=dict(c.execute(METRICS+'''SELECT SUM(variants IS NULL) missing_source,SUM(variants>1) ambiguous FROM metrics''',p).fetchone())
    size=50 if page_type=='index' else 25
    p.update(limit=size,offset=(f['page']-1)*size)
    gem='m.vote_average*(1.0+(1.0-CAST(m.vote_count AS REAL)/(:max_votes+1))*0.25)' if page_type=='gems' else 'NULL'
    select=f'm.*, {gem} gem_score'
    sql=base.format(select=select)+' ORDER BY '+sorts[f['sort_by']]+' '+direction+' NULLS LAST,m.id LIMIT :limit OFFSET :offset'
    rows=dictionaries(c.execute(sql,p))
    for r in rows:
        r['sources']=dictionaries(c.execute('SELECT source,title,budget,revenue,vote_average,vote_count FROM film_values WHERE movie_id=? ORDER BY source,id',(r['id'],)))
        r['genres']=dictionaries(c.execute('''SELECT gt.id,gt.name FROM film_genres g JOIN catalog_genres gt ON gt.id=g.genre_id
            WHERE g.movie_id=? GROUP BY gt.id ORDER BY gt.name,gt.id''',(r['id'],)))
        r['cast_preview']=cast_preview(c,r['id'],f['source'])
    return dict(rows=rows,total=counts['total'],summary=counts,excluded=excluded,size=size,sql=sql)

def stats(c, source):
    counts={name:c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
            for name,table in [('movies','films'),('actors','people'),('roles','cast_roles'),('genres','catalog_genres')]}
    counts['gems']=c.execute(METRICS+'''SELECT COUNT(*) FROM metrics WHERE variants=1 AND vote_average>=7.4 AND vote_count BETWEEN 50 AND 4500 AND budget>0 AND budget<=35000000''',{'source':source}).fetchone()[0]
    counts['bombs']=c.execute(METRICS+'''SELECT COUNT(*) FROM metrics WHERE variants=1 AND budget>=10000000 AND revenue>0 AND revenue<budget''',{'source':source}).fetchone()[0]
    return counts

def movie_detail(c, movie_id):
    row=c.execute('SELECT * FROM films WHERE id=?',(movie_id,)).fetchone()
    if not row:return None
    d=dict(row)
    d['values']=dictionaries(c.execute('SELECT * FROM film_values WHERE movie_id=? ORDER BY source,id',(movie_id,)))
    d['cast']=dictionaries(c.execute("""SELECT cr.*,p.name FROM cast_roles cr JOIN people p ON p.id=cr.actor_id
        WHERE movie_id=? ORDER BY cr.source,cr.credit_order,p.id""",(movie_id,)))
    d['genres']=dictionaries(c.execute('SELECT g.*,gt.name FROM film_genres g JOIN catalog_genres gt ON g.genre_id=gt.id WHERE movie_id=? ORDER BY gt.name',(movie_id,)))
    return d

def difference_rows(c, f):
    fields = ['title', 'budget', 'revenue', 'vote_average', 'vote_count']
    expressions = {x: f'(COUNT(DISTINCT v.{x})>1 OR (COUNT(v.{x})>0 AND COUNT(v.{x})<COUNT(*)))' for x in fields}
    grouped = """SELECT f.id,f.title,""" + ','.join(expressions[x]+' AS '+x+'_diff' for x in fields) + """
        FROM films f JOIN film_values v ON v.movie_id=f.id WHERE
        EXISTS(SELECT 1 FROM film_values q WHERE q.movie_id=f.id AND q.title LIKE :title)
        GROUP BY f.id"""
    predicate = ' OR '.join(x+'_diff' for x in (fields if not f.get('field') else [f['field']]))
    sql = 'SELECT * FROM (' + grouped + ') WHERE ' + predicate
    substantive = '(title_diff OR budget_diff OR revenue_diff OR vote_average_diff)'
    p = {'title': '%'+f.get('title','')+'%', 'offset': (f['page']-1)*25}
    summary = dict(c.execute('SELECT COUNT(*) AS matches, COALESCE(SUM('+substantive+'),0) AS substantive, '
        'COALESCE(SUM(vote_count_diff AND NOT '+substantive+'),0) AS votes_only, '+
        ','.join('COALESCE(SUM('+x+'_diff),0) AS '+x for x in fields)+' FROM ('+sql+')', p).fetchone())
    rows = dictionaries(c.execute(sql+' ORDER BY title COLLATE NOCASE,id LIMIT 25 OFFSET :offset', p))
    for r in rows:
        r['sources'] = dictionaries(c.execute('SELECT * FROM film_values WHERE movie_id=? ORDER BY source,id', (r['id'],)))
        r['differing'] = [x for x in fields if r[x+'_diff']]
    return dict(rows=rows,total=summary['matches'],size=25,sql=sql,summary=summary)


def add_manual_entry(c, entry):
    """Call under BEGIN IMMEDIATE so locally allocated IDs cannot collide."""
    import json
    mid = entry['movie_id']
    values = entry['values']
    if mid is None:
        mid = min(0, c.execute('SELECT COALESCE(MIN(id),0) FROM films').fetchone()[0]) - 1
        c.execute('INSERT INTO films(id,title) VALUES(?,?)', (mid, values['title']))
    c.execute('''INSERT INTO film_values(movie_id,source,title,budget,revenue,vote_average,vote_count,signature)
        VALUES(?,'manual',?,?,?,?,?,?)''', (mid, values['title'], values['budget'], values['revenue'],
        values['vote_average'], values['vote_count'], json.dumps(values, sort_keys=True)))
    c.executemany("INSERT INTO film_genres VALUES(?,?,'manual')", [(mid, gid) for gid in entry['genre_ids']])
    for index, actor in enumerate(entry['cast']):
        aid = actor['actor_id']
        if aid is None:
            aid = min(0, c.execute('SELECT COALESCE(MIN(id),0) FROM people').fetchone()[0]) - 1
            c.execute('INSERT INTO people(id,name) VALUES(?,?)', (aid, actor['name']))
        c.execute("INSERT OR IGNORE INTO cast_roles VALUES(?,?,?,'manual',?)", (mid, aid, actor['role'], index))
    bump_version(c)
    return mid
