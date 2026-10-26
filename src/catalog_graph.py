"""Read-only, source-aware graph exploration over the catalog."""
from collections import defaultdict
import re
try:
    from . import database as db, validation as valid
except ImportError:
    import database as db
    import validation as valid

TABLES = {'movie': ('films', 'title'), 'actor': ('people', 'name'), 'genre': ('catalog_genres', 'name')}


def filters(raw, c):
    errors = {}
    f = {'source': raw.get('source', 'movies'), 'kind': raw.get('kind', 'movie'),
         'q': raw.get('q', '').strip()[:200], 'role': raw.get('role', '').strip()[:200],
         'edge': raw.get('edge', 'both')}
    if f['source'] not in (*db.SOURCES,'both'):errors['source'] = 'Choose a listed source.'
    if f['kind'] not in TABLES:errors['kind'] = 'Choose Movies, Actors, or Genres.'
    if f['edge'] not in ('both', 'cast', 'genre'):errors['edge'] = 'Choose cast, genre, or both relationship types.'
    for field in ('budget', 'revenue'):
        for bound in ('min', 'max'):
            key = bound + '_' + field
            f[key] = valid.numeric(raw, key, errors, True)
        if f['min_'+field] is not None and f['max_'+field] is not None and f['min_'+field] > f['max_'+field]:
            errors[field] = 'The maximum must be at least the minimum.'
    f['genre_id'] = valid.numeric(raw, 'genre_id', errors, True, 1)
    if f['genre_id'] is not None and not c.execute('SELECT 1 FROM catalog_genres WHERE id=?', (f['genre_id'],)).fetchone():
        errors['genre_id'] = 'Choose a listed genre.'
    f['offset'] = valid.numeric(raw, 'offset', errors, True, 0, 1_000_000, 0)
    if f['source']=='both' and any(f[key] is not None for key in ('min_budget','max_budget','min_revenue','max_revenue')):
        errors['source']='Choose one numerical source before filtering budget or revenue.'
    if errors:raise valid.ValidationError(errors)
    return f


def eligible(f):
    params = dict(f,combined='both')
    terms = ['m.variants IS NOT NULL']
    for field in ('budget', 'revenue'):
        for bound, op in [('min', '>='), ('max', '<=')]:
            key = bound+'_'+field
            if f[key] is not None:
                terms += [f'm.{field}>0', f'm.{field}{op}:{key}']
    if f['genre_id'] is not None:
        terms.append('EXISTS(SELECT 1 FROM film_genres g WHERE g.movie_id=m.id AND g.genre_id=:genre_id AND (g.source=:source OR :source=:combined))')
    if f['role']:
        terms.append('EXISTS(SELECT 1 FROM cast_roles cr WHERE cr.movie_id=m.id AND (cr.source=:source OR :source=:combined) AND instr(lower(cr.role),lower(:role))>0)')
    metrics=db.METRICS if f['source']!='both' else '''WITH metrics AS (SELECT f.id,f.title display_title,f.title,1 variants FROM films f WHERE EXISTS(SELECT 1 FROM film_values v WHERE v.movie_id=f.id)) '''
    return metrics + ', eligible AS (SELECT m.* FROM metrics m WHERE ' + ' AND '.join(terms) + ') ', params


def search(c, f):
    cte, params = eligible(f)
    params['offset'] = f['offset']; params['q'] = f['q']
    if f['kind'] == 'movie':
        sql = '''SELECT e.id, e.display_title label FROM eligible e WHERE
          instr(lower(e.display_title),lower(:q))>0 OR instr(lower(e.title),lower(:q))>0 OR
          EXISTS(SELECT 1 FROM cast_roles cr JOIN people p ON p.id=cr.actor_id WHERE cr.movie_id=e.id AND (cr.source=:source OR :source=:combined) AND
           (instr(lower(p.name),lower(:q))>0 OR instr(lower(cr.role),lower(:q))>0)) OR
          EXISTS(SELECT 1 FROM film_genres g JOIN catalog_genres t ON t.id=g.genre_id WHERE g.movie_id=e.id AND (g.source=:source OR :source=:combined) AND instr(lower(t.name),lower(:q))>0)'''
    elif f['kind'] == 'actor':
        sql = '''SELECT p.id,p.name label FROM people p WHERE instr(lower(p.name),lower(:q))>0 AND EXISTS(
         SELECT 1 FROM cast_roles cr JOIN eligible e ON e.id=cr.movie_id WHERE cr.actor_id=p.id AND (cr.source=:source OR :source=:combined)
         AND instr(lower(cr.role),lower(:role))>0)'''
    else:
        sql = '''SELECT t.id,t.name label FROM catalog_genres t WHERE instr(lower(t.name),lower(:q))>0 AND EXISTS(
         SELECT 1 FROM film_genres g JOIN eligible e ON e.id=g.movie_id WHERE g.genre_id=t.id AND (g.source=:source OR :source=:combined))'''
    rows = db.dictionaries(c.execute(cte + sql + ' ORDER BY label,id LIMIT 21 OFFSET :offset', params))
    return {'results': [{'id': f"{f['kind']}:{r['id']}", 'label': r['label'], 'kind': f['kind']} for r in rows[:20]],
            'has_more': len(rows)>20, 'next_offset': f['offset']+min(20,len(rows)), 'catalog_version':db.version(c)}


def suggestions(c, f, field):
    if field not in ('q','role'):
        raise valid.ValidationError({'field':'Choose search terms or character roles.'})
    term=f[field].strip()
    if len(term)<2:return {'suggestions':[]}
    # A role input should suggest completions rather than filter itself first.
    scope=dict(f)
    if field=='role':scope['role']=''
    cte, params=eligible(scope)
    params['term']=term
    if field=='role':
        queries=[('role', "SELECT DISTINCT cr.role label FROM cast_roles cr JOIN eligible e ON e.id=cr.movie_id WHERE (cr.source=:source OR :source=:combined) AND instr(lower(cr.role),lower(:term))>0")]
    else:
        queries=[]
        if f['kind']=='movie':
            queries.append(('movie', "SELECT DISTINCT title label FROM eligible WHERE instr(lower(title),lower(:term))>0"))
        if f['kind'] in ('movie','actor'):
            queries.append(('actor', "SELECT DISTINCT p.name label FROM people p WHERE instr(lower(p.name),lower(:term))>0 AND EXISTS(SELECT 1 FROM cast_roles cr JOIN eligible e ON e.id=cr.movie_id WHERE cr.actor_id=p.id AND (cr.source=:source OR :source=:combined) AND instr(lower(cr.role),lower(:role))>0)"))
        if f['kind'] in ('movie','genre'):
            queries.append(('genre', "SELECT DISTINCT t.name label FROM catalog_genres t WHERE instr(lower(t.name),lower(:term))>0 AND EXISTS(SELECT 1 FROM film_genres g JOIN eligible e ON e.id=g.movie_id WHERE g.genre_id=t.id AND (g.source=:source OR :source=:combined))"))
    items=[]
    for kind,sql in queries:
        rows=c.execute(cte+sql+' ORDER BY (instr(lower(label),lower(:term))=1) DESC,label LIMIT 6',params)
        items.extend({'value':r['label'],'kind':kind} for r in rows if r['label'])
    return {'suggestions':items}


def parse_node(value):
    if not isinstance(value,str) or not re.fullmatch(r'(movie|actor|genre):-?\d{1,19}', value):
        raise valid.ValidationError({'node': 'Choose catalog movie, actor, or genre nodes.'})
    kind, number = value.split(':'); number=int(number)
    if abs(number)>9223372036854775807:raise valid.ValidationError({'node':'Invalid catalog ID.'})
    return kind, number


def view(c, f, node_ids, expand=None):
    if len(node_ids)>300:raise valid.ValidationError({'nodes':'Keep at most 300 nodes on the canvas.'})
    selected = set(parse_node(value) for value in node_ids)
    cte, params = eligible(f)
    more = False; next_offset = f['offset']; total = None
    if expand:
        kind, number = parse_node(expand)
        table, label = TABLES[kind]
        if not c.execute(f'SELECT 1 FROM {table} WHERE id=?',(number,)).fetchone():
            raise valid.ValidationError({'node':'This record is no longer in the catalog.'})
        selected.add((kind,number))
        if len(selected)>300:raise valid.ValidationError({'nodes':'Remove a node before expanding a new record.'})
        params['id']=number
        if kind == 'movie':
            queries=[]
            if f['edge'] in ('both','cast'):
                queries.append("SELECT DISTINCT 'actor' kind,cr.actor_id id FROM cast_roles cr JOIN eligible e ON e.id=cr.movie_id WHERE cr.movie_id=:id AND (cr.source=:source OR :source=:combined) AND instr(lower(cr.role),lower(:role))>0")
            if f['edge'] in ('both','genre'):
                queries.append("SELECT DISTINCT 'genre' kind,g.genre_id id FROM film_genres g JOIN eligible e ON e.id=g.movie_id WHERE g.movie_id=:id AND (g.source=:source OR :source=:combined)")
        else:
            enabled = f['edge'] in ('both', 'cast' if kind=='actor' else 'genre')
            table, column = ('cast_roles','actor_id') if kind=='actor' else ('film_genres','genre_id')
            role = ' AND instr(lower(link.role),lower(:role))>0' if kind=='actor' else ''
            queries=[f"SELECT DISTINCT 'movie' kind,e.id FROM eligible e JOIN {table} link ON e.id=link.movie_id WHERE link.{column}=:id AND (link.source=:source OR :source=:combined)"+role] if enabled else []
        if queries:
            neighbors=[(r['kind'],r['id']) for r in c.execute(cte+' UNION '.join(queries)+' ORDER BY kind,id',params)]
        else:neighbors=[]
        # Skip already visible neighbors, so expansion always makes progress.
        total=len(neighbors)
        remaining=[node for node in neighbors if node not in selected]
        batch=remaining[:min(20,300-len(selected))]
        selected.update(batch); more=len(remaining)>len(batch)
        next_offset=len(batch)
    movies={i for kind,i in selected if kind=='movie'}
    if movies:
        placeholders=','.join(str(i) for i in sorted(movies))  # Parsed bounded integers only.
        qualified={r['id'] for r in c.execute(cte+f'SELECT id FROM eligible WHERE id IN ({placeholders})',params)}
        selected={node for node in selected if node[0]!='movie' or node[1] in qualified}
    nodes=[]
    for kind, number in sorted(selected):
        table, label = TABLES[kind]
        row=c.execute(f'SELECT {label} FROM {table} WHERE id=?',(number,)).fetchone()
        if not row:continue
        data={'id':f'{kind}:{number}', 'label':row[0], 'kind':kind}
        if kind=='movie':
            data['values']=db.dictionaries(c.execute('SELECT source,title,budget,revenue,vote_average,vote_count FROM film_values WHERE movie_id=? ORDER BY source,id',(number,)))
        nodes.append({'data':data})
    ids={n['data']['id'] for n in nodes}; edges=[]
    for mid in sorted(i for kind,i in selected if kind=='movie'):
        if f'movie:{mid}' not in ids:continue
        if f['edge'] in ('both','cast'):
            credits=defaultdict(list)
            for row in c.execute("SELECT actor_id,role,source FROM cast_roles WHERE movie_id=? AND (source=? OR ?='both') AND instr(lower(role),lower(?))>0 ORDER BY actor_id,role",(mid,f['source'],f['source'],f['role'])):
                if f"actor:{row['actor_id']}" in ids:credits[row['actor_id']].append(dict(row))
            for aid,roles in credits.items():
                edges.append({'data':{'id':f'cast:{mid}:{aid}', 'source':f'actor:{aid}', 'target':f'movie:{mid}',
                                      'label':'acted in', 'kind':'cast', 'details':roles}})
        if f['edge'] in ('both','genre'):
            memberships=defaultdict(list)
            for row in c.execute("SELECT genre_id,source FROM film_genres WHERE movie_id=? AND (source=? OR ?='both') ORDER BY genre_id,source",(mid,f['source'],f['source'])):
                memberships[row['genre_id']].append(dict(row))
            for gid,records in memberships.items():
                if f'genre:{gid}' in ids:
                    edges.append({'data':{'id':f'genre-link:{mid}:{gid}','source':f'movie:{mid}','target':f'genre:{gid}','kind':'genre','label':'has genre','details':records}})
    return dict(nodes=nodes,edges=edges[:1000],truncated=len(edges)>1000,has_more=more,total=total,
                next_offset=next_offset,catalog_version=db.version(c))
