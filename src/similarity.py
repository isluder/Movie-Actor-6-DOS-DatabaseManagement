"""Small, explainable sparse movie vectors; building the catalog index is explicit."""
from collections import Counter, defaultdict
from functools import lru_cache
import gzip
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time

try:
    from . import database as db
except ImportError:
    import database as db

FORMAT = 1


def index_path(database):
    return Path(str(database) + '.similarity.json.gz')


def documents(c, ids=None):
    """Keep source-specific title variants, deduplicate cast and genre identities."""
    films = {r['id']: {'id': r['id'], 'title': r['title'], 'tokens': set()} for r in
             c.execute('SELECT id,title FROM films' + (' WHERE id IN (' + ','.join('?' for _ in ids) + ')' if ids else ''), ids or [])}
    if not films:
        return []
    def rows(sql):
        # Sample reads use indexed movie IDs rather than scanning all catalog edges.
        if ids:
            sql += ' WHERE movie_id IN (' + ','.join('?' for _ in ids) + ')'
        return c.execute(sql, ids or [])
    for film in films.values():
        film['tokens'].update('title:' + token for token in re.findall(r'\w+', film['title'].casefold()))
    for row in rows('SELECT movie_id,title FROM film_values'):
        films[row['movie_id']]['tokens'].update('title:' + token for token in re.findall(r'\w+', row['title'].casefold()))
    for table, field, prefix in [('cast_roles', 'actor_id', 'actor'), ('film_genres', 'genre_id', 'genre')]:
        for row in rows(f'SELECT movie_id,{field} FROM {table}'):
            films[row['movie_id']]['tokens'].add(f'{prefix}:{row[field]}')
    return list(films.values())


def vectorize(docs):
    counts = Counter(token for doc in docs for token in doc['tokens'])
    total = len(docs)
    for doc in docs:
        groups = defaultdict(dict)
        for token in sorted(doc['tokens']):
            groups[token.split(':')[0]][token] = math.log((1 + total) / (1 + counts[token])) + 1
        weights = {}
        # Equal contribution from each available group; large casts do not dominate.
        for group in groups.values():
            norm = math.sqrt(sum(value * value for value in group.values()))
            weights.update({token: value / norm for token, value in group.items()})
        norm = math.sqrt(len(groups)) or 1
        doc['vector'] = {token: value / norm for token, value in weights.items()}
        del doc['tokens']
    return docs


def benchmark(database, sample=1500):
    """Read-only stratified sample; never builds or writes the full index."""
    with db.connection(database) as c:
        ids = [r[0] for r in c.execute('SELECT id FROM films ORDER BY id')]
        selected = ids[::max(1, len(ids) // sample)][:sample]
        started = time.perf_counter()
        docs = vectorize(documents(c, selected))
        vectors_seconds = time.perf_counter() - started
    started = time.perf_counter()
    payload = json.dumps(docs).encode()
    compressed = gzip.compress(payload)
    serialization_seconds = time.perf_counter() - started
    scale = len(ids) / max(1, len(docs))
    estimate = (vectors_seconds + serialization_seconds) * scale
    return dict(movies=len(ids), sample=len(docs), sample_seconds=round(vectors_seconds + serialization_seconds, 3),
                estimated_seconds=round(estimate, 1), estimated_compressed_mb=round(len(compressed)*scale/1024**2, 1))


def build(database):
    """Explicit CLI action only; atomically publish an index of one catalog snapshot."""
    with db.connection(database) as c:
        c.execute('BEGIN')
        version = db.version(c)
        docs = vectorize(documents(c))
    path = index_path(database)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.similarity-')
    try:
        with os.fdopen(fd, 'wb') as raw:
            with gzip.GzipFile(fileobj=raw, mode='wb') as zipped:
                zipped.write(json.dumps(dict(format=FORMAT, version=version, movies=docs)).encode())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)
    return len(docs)


@lru_cache(maxsize=2)
def _load(path, stamp, size):
    with gzip.open(path, 'rt') as handle:
        return json.load(handle)


def load(database, version):
    path = index_path(database)
    if not path.exists():return None
    stat = path.stat()
    try:
        payload = _load(str(path), stat.st_mtime_ns, stat.st_size)
    except (OSError, ValueError, EOFError):
        return None
    if not isinstance(payload, dict):return None
    if payload.get('format') != FORMAT or payload.get('version') != version:return None
    return payload['movies']


def recommend(docs, movie_id, limit=20):
    by_id = {doc['id']: doc for doc in docs}
    selected = by_id.get(movie_id)
    if selected is None:raise ValueError('Choose a movie from the catalog.')
    vector = selected['vector']
    results = []
    for doc in docs:
        if doc['id'] == movie_id:continue
        shared = vector.keys() & doc['vector'].keys()
        score = sum(vector[token] * doc['vector'][token] for token in shared)
        if score > 0:
            results.append(dict(id=doc['id'], title=doc['title'], score=min(1, score),
                                shared=sorted(shared)))
    results.sort(key=lambda item: (-item['score'], item['title'].casefold(), item['id']))
    return selected, results[:limit]
