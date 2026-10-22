"""Shortest paths on the complete bipartite graph; rendering limits are separate."""
from collections import defaultdict, deque, OrderedDict
import threading
import json
import time
try:
    from . import database as db
except ImportError:
    import database as db

_CACHE=OrderedDict()
_LOCK=threading.Lock()

def adjacency(c, path, source):
    key=(str(path),db.version(c),source)
    with _LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key);return _CACHE[key]
    a=defaultdict(list);m=defaultdict(list)
    sql='''SELECT DISTINCT cr.movie_id,cr.actor_id FROM cast_roles cr JOIN films f ON f.id=cr.movie_id
        WHERE f.hidden=0 AND NOT EXISTS(SELECT 1 FROM cast_suppressions cs WHERE cs.movie_id=cr.movie_id AND cs.actor_id=cr.actor_id AND cs.role=cr.role AND cs.source=cr.source)'''
    params=[]
    if source!='both':sql+=' AND cr.source=?';params=[source]
    for mid,aid in c.execute(sql+' ORDER BY cr.movie_id,cr.actor_id',params):
        a[aid].append(mid);m[mid].append(aid)
    with _LOCK:
        _CACHE[key]=(a,m)
        while len(_CACHE)>4:_CACHE.popitem(last=False)
    return a,m

def shortest(a,m,start,end,seconds=10):
    if start==end:return 'same_actor',[('actor',start)]
    queue=deque([(start,0)]);parent={start:None};visited_movies=set();deadline=time.monotonic()+seconds
    while queue:
        actor,depth=queue.popleft()
        if time.monotonic()>deadline:return 'interrupted',[]
        if depth>=6:continue
        for movie in a.get(actor,[]):
            if movie in visited_movies:continue
            visited_movies.add(movie)
            for neighbor in m[movie]:
                if neighbor in parent:continue
                parent[neighbor]=(actor,movie)
                if neighbor==end:
                    path=[('actor',end)];cursor=end
                    while parent[cursor] is not None:
                        previous,mid=parent[cursor];path.extend([('movie',mid),('actor',previous)]);cursor=previous
                    return 'found',list(reversed(path))
                queue.append((neighbor,depth+1))
    return 'no_path',[]

def result(c,db_path,f):
    a,m=adjacency(c,db_path,f['source'])
    status,path=shortest(a,m,f['start'],f['end'])
    report_row=c.execute("SELECT value FROM catalog_meta WHERE key='report'").fetchone()
    complete=json.loads(report_row[0]).get('cast_complete',False) if report_row else False
    out={'status':status,'catalog_version':db.version(c),'source':f['source'],'depth':f['depth'],
         'cast_complete':complete,'degrees':(len(path)-1)//2 if path else None,'truncated':False,'nodes':[],'edges':[],'path':[]}
    if not path:return out
    nodes=set(path);path_edges=set()
    for x,y in zip(path,path[1:]):
        actor,movie=(x[1],y[1]) if x[0]=='actor' else (y[1],x[1]);path_edges.add((movie,actor))
    pairs=set(path_edges);frontier=sorted(i for kind,i in path if kind=='actor');expanded=set()
    for _ in range(f['depth']):
        next_frontier=set()
        for actor in frontier:
            if actor in expanded:continue
            expanded.add(actor)
            for movie in a.get(actor,[]):
                if len(nodes)>=300 and ('movie',movie) not in nodes:out['truncated']=True;continue
                nodes.add(('movie',movie));pairs.add((movie,actor))
                for other in m[movie]:
                    if len(pairs)>=1000:out['truncated']=True;break
                    if len(nodes)>=300 and ('actor',other) not in nodes:out['truncated']=True;continue
                    nodes.add(('actor',other));pairs.add((movie,other));next_frontier.add(other)
        frontier=sorted(next_frontier-expanded)
    actors={i for kind,i in nodes if kind=='actor'};movies={i for kind,i in nodes if kind=='movie'}
    # Prune any expansion pairs beyond the edge cap while retaining every path edge.
    ordered_pairs=sorted(path_edges)+sorted(pairs-path_edges)
    if len(ordered_pairs)>1000:out['truncated']=True
    pairs=set(ordered_pairs[:1000])
    nodes=set(path)|{('movie',mid) for mid,aid in pairs}|{('actor',aid) for mid,aid in pairs}
    out.update(describe(c,a,nodes,pairs,path,f['source'],path_edges))
    return out


def describe(c,a,nodes,pairs,path,source,path_edges):
    """One serializer for initial paths and incremental neighbor batches."""
    out={'nodes':[],'edges':[],'path':[]}
    movies={i for kind,i in nodes if kind=='movie'}
    for kind,i in sorted(nodes):
        if kind=='actor':
            row=c.execute('SELECT name FROM people WHERE id=?',(i,)).fetchone()
            details={'actor_id':i,'name':row[0],'movie_count':len(a.get(i,[]))}
            label=row[0]
        else:
            label=c.execute('SELECT title FROM films WHERE id=?',(i,)).fetchone()[0]
            details={'movie_id':i,'title':label,'sources':db.dictionaries(c.execute('SELECT source,title,budget,revenue,vote_average,vote_count FROM film_values WHERE movie_id=? ORDER BY source,id',(i,)))}
        out['nodes'].append({'data':{'id':f'{kind}:{i}','label':label,'kind':kind,'on_path':(kind,i) in path,'details':details}})
    by_movie=defaultdict(dict)
    if movies:
        placeholders=','.join('?' for _ in movies)
        sql=f'SELECT cr.* FROM cast_roles cr WHERE movie_id IN ({placeholders}) AND NOT EXISTS(SELECT 1 FROM cast_suppressions cs WHERE cs.movie_id=cr.movie_id AND cs.actor_id=cr.actor_id AND cs.role=cr.role AND cs.source=cr.source)'
        params=list(sorted(movies))
        if source!='both':sql+=' AND source=?';params.append(source)
        for r in c.execute(sql,params):
            key=(r['movie_id'],r['actor_id'])
            if key in pairs:by_movie[key][(r['source'],r['role'])]=True
    for mid,aid in sorted(pairs):
        details=[{'source':s,'role':r} for s,r in sorted(by_movie[(mid,aid)])]
        out['edges'].append({'data':{'id':f'cast:{mid}:{aid}','source':f'actor:{aid}','target':f'movie:{mid}',
                                      'on_path':(mid,aid) in path_edges,'details':details}})
    lookup={n['data']['id']:n['data']['label'] for n in out['nodes']}
    out['path']=[{'id':f'{kind}:{i}','kind':kind,'entity_id':i,'label':lookup[f'{kind}:{i}']} for kind,i in path]
    return out


def expand(c,db_path,kind,entity_id,source,offset=0,limit=15):
    """Return one page of immediate neighbors, not an entire co-star layer."""
    a,m=adjacency(c,db_path,source)
    neighbors=a.get(entity_id,[]) if kind=='actor' else m.get(entity_id,[])
    selected=neighbors[offset:offset+limit]
    other_kind='movie' if kind=='actor' else 'actor'
    nodes={(kind,entity_id)}|{(other_kind,i) for i in selected}
    pairs={(i,entity_id) if kind=='actor' else (entity_id,i) for i in selected}
    out=describe(c,a,nodes,pairs,[],source,set())
    out.update(node=f'{kind}:{entity_id}',catalog_version=db.version(c),source=source,
               total=len(neighbors),offset=offset,next_offset=offset+len(selected),
               has_more=offset+len(selected)<len(neighbors))
    return out


_DISTANCE_CACHE = OrderedDict()
_DISTANCE_LOCK = threading.Lock()


def distance_distribution(a, m, start, total_actors, seconds=5):
    """Exact component traversal: each movie/cast array is visited once, no clique."""
    started = time.monotonic()
    distances = {start: 0}
    movies = set()
    queue = deque([start])
    histogram = defaultdict(int)
    while queue:
        if time.monotonic() - started > seconds:
            return dict(status='interrupted', distribution=[], connected=None, disconnected=None,
                        average=None, maximum=None, within_six=None, beyond_six=None,
                        total_actors=total_actors, elapsed_seconds=time.monotonic() - started)
        actor = queue.popleft()
        for movie in a.get(actor, ()):
            if movie in movies:
                continue
            movies.add(movie)
            depth = distances[actor] + 1
            for other in m[movie]:
                if other not in distances:
                    distances[other] = depth
                    histogram[depth] += 1
                    queue.append(other)
    connected = len(distances) - 1
    maximum = max(histogram, default=None)
    farthest = min((actor for actor, depth in distances.items() if depth == maximum), default=None)
    # Reconstruct a deterministic shortest route from the distance labels, without
    # retaining parent tuples for hundreds of thousands of actors.
    path = []
    if farthest is not None:
        cursor = farthest
        path = [('actor', cursor)]
        while cursor != start:
            previous, shared = next((other, movie) for movie in a[cursor] for other in m[movie]
                                    if distances.get(other) == distances[cursor] - 1)
            path.extend([('movie', shared), ('actor', previous)])
            cursor = previous
        path.reverse()
    return dict(status='complete', distribution=[dict(degrees=d, actors=histogram[d]) for d in sorted(histogram)],
                connected=connected, disconnected=total_actors - 1 - connected,
                average=sum(d * n for d, n in histogram.items()) / connected if connected else None,
                maximum=maximum, farthest_actor=farthest, farthest_count=histogram.get(maximum, 0), farthest_path=path, within_six=sum(n for d, n in histogram.items() if d <= 6),
                beyond_six=sum(n for d, n in histogram.items() if d > 6), total_actors=total_actors,
                elapsed_seconds=time.monotonic() - started)


def actor_statistics(c, db_path, start, source):
    """Bounded cache stores summaries, never an all-pairs distance matrix."""
    version = db.version(c)
    key = (str(db_path), version, source, start)
    # Serialize cold traversals to avoid concurrent copies of expensive work.
    with _DISTANCE_LOCK:
        if key in _DISTANCE_CACHE:
            _DISTANCE_CACHE.move_to_end(key)
            return {**_DISTANCE_CACHE[key], 'cached': True}
        a, m = adjacency(c, db_path, source)
        total = c.execute('SELECT COUNT(*) FROM people').fetchone()[0]
        out = distance_distribution(a, m, start, total)
        report = c.execute("SELECT value FROM catalog_meta WHERE key='report'").fetchone()
        out.update(start=start, actor_name=c.execute('SELECT name FROM people WHERE id=?', (start,)).fetchone()[0],
                   source=source, catalog_version=version, cached=False, network_actors=len(a),
                   direct_movies=len(a.get(start, ())),
                   cast_complete=json.loads(report[0]).get('cast_complete', False) if report else False)
        if out['status'] == 'complete':
            out['farthest_path'] = [dict(kind=kind, entity_id=entity_id,
                label=c.execute('SELECT '+('name FROM people' if kind=='actor' else 'title FROM films')+' WHERE id=?',
                                (entity_id,)).fetchone()[0]) for kind, entity_id in out['farthest_path']]
            _DISTANCE_CACHE[key] = out
            while len(_DISTANCE_CACHE) > 128:
                _DISTANCE_CACHE.popitem(last=False)
        return dict(out)
