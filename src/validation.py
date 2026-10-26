"""Shared validation for HTML requests and JSON endpoints."""
import math

class ValidationError(ValueError):
    def __init__(self,errors):
        self.errors=errors
        super().__init__('; '.join(f'{k}: {v}' for k,v in errors.items()))

SORT_FIELDS={
 'index':('rating','title','budget','revenue','votes','revenue_minus_budget'),
 'gems':('gem_score','rating','votes','roi'),
 'bombs':('shortfall','roi','rating','budget'),
}
SORT_LABELS={'rating':'Rating','title':'Movie title','budget':'Production budget','revenue':'Box-office revenue',
             'votes':'Vote count','revenue_minus_budget':'Revenue minus production budget','gem_score':'Gem score',
             'shortfall':'Production-budget shortfall','roi':'Revenue minus budget (% of budget)'}
# Accept existing bookmarked URLs without a migration.
LEGACY_SORTS={
 'vote_average_desc':('rating','desc'),'vote_average_asc':('rating','asc'),
 'title_asc':('title','asc'),'budget_desc':('budget','desc'),'revenue_desc':('revenue','desc'),
 'vote_count_desc':('votes','desc'),'profit_desc':('revenue_minus_budget','desc'),
 'profit_asc':('revenue_minus_budget','asc'),'net_loss_desc':('shortfall','desc'),
 'roi_asc':('roi','asc'),'rating_desc':('rating','desc'),'votes_asc':('votes','asc'),
 'roi_desc':('roi','desc'),'gem_score_desc':('gem_score','desc'),
}

def numeric(raw,key,errors,integer=False,minimum=0,maximum=None,default=None):
    val=raw.get(key,'')
    if val is None or str(val).strip()=='':return default
    try:
        n=float(val)
        if not math.isfinite(n):raise ValueError()
        if integer:
            # IDs/money must not be silently rounded through a float.
            s=str(val).strip()
            if not s.lstrip('-').isdigit():raise ValueError()
            n=int(s)
        if n<minimum or (maximum is not None and n>maximum) or (integer and n>9223372036854775807):raise ValueError()
        return n
    except (ValueError,TypeError,OverflowError):
        errors[key]=f'Enter a {"whole " if integer else ""}number from {minimum}'+(f' to {maximum}' if maximum is not None else ' or greater')+'.'
        return default

def query(raw,page_type,c):
    errors={};f={}
    for key in ('title','actor','character'):
        f[key]=str(raw.get(key,'')).strip()[:300]
    f['source']=raw.get('source','movies')
    allowed=('both','movies','tmdb','demo','manual') if page_type=='degrees' else ('movies','tmdb','demo','manual')
    if f['source'] not in allowed:errors['source']='Choose an available data source.'
    if page_type=='degrees' and 'source' not in raw:f['source']='both'
    f['page']=numeric(raw,'page',errors,True,1,1_000_000,1)
    f['actor_id']=numeric(raw,'actor_id',errors,True,-9223372036854775807)
    f['genre_id']=numeric(raw,'genre_id',errors,True,1)
    for key,table in [('actor_id','people'),('genre_id','catalog_genres')]:
        if f[key] is not None and not c.execute(f'SELECT 1 FROM {table} WHERE id=?',(f[key],)).fetchone():errors[key]='This selection is absent from the current catalog.'
    if page_type in SORT_FIELDS:
        field=raw.get('sort_by',SORT_FIELDS[page_type][0])
        field,default_order=LEGACY_SORTS.get(field,(field,'desc')) if isinstance(field,str) else (None,'desc')
        f['sort_by']=field
        f['sort_order']=raw.get('sort_order',default_order)
        if field not in SORT_FIELDS[page_type]:errors['sort_by']='Choose a listed sort field.'
        if f['sort_order'] not in ('asc','desc'):errors['sort_order']='Choose ascending or descending.'
    if page_type in ('index','gems','bombs'):
        f['min_rating']=numeric(raw,'min_rating',errors,maximum=10,default=7.4 if page_type=='gems' else None)
        f['max_rating']=numeric(raw,'max_rating',errors,maximum=10)
        f['min_budget']=numeric(raw,'min_budget',errors,True,default=10_000_000 if page_type=='bombs' else None)
        if f['min_rating'] is not None and f['max_rating'] is not None and f['min_rating']>f['max_rating']:errors['max_rating']='Maximum rating must be at least the minimum.'
    if page_type=='gems':
        f['min_votes']=numeric(raw,'min_votes',errors,True,default=50)
        f['max_votes']=numeric(raw,'max_votes',errors,True,default=4500)
        f['max_budget']=numeric(raw,'max_budget',errors,True,default=35_000_000 if 'max_budget' not in raw else None)
        if f['min_votes']>f['max_votes']:errors['max_votes']='Maximum votes must be at least the minimum.'
    if page_type=='differences':
        f['field']=raw.get('field','')
        if f['field'] not in ('','title','budget','revenue','vote_average','vote_count'):errors['field']='Choose a listed field.'
    if page_type=='degrees':
        for key in ('start','end'):
            f[key]=numeric(raw,key,errors,True,-9223372036854775807)
            if f[key] is not None and not c.execute('SELECT 1 FROM people WHERE id=?',(f[key],)).fetchone():errors[key]='Actor is absent from the current catalog. Choose another actor.'
        f['depth']=numeric(raw,'depth',errors,True,0,3,0)
    if errors:raise ValidationError(errors)
    return f


def manual_entry(raw, c):
    """Validate a movie and its optional cast/genres before any writes occur."""
    errors = {}
    title = str(raw.get('title', '')).strip()
    if not 1 <= len(title) <= 300:
        errors['title'] = 'Enter a movie title of 1–300 characters.'
    movie_id = numeric(raw, 'movie_id', errors, True, -9223372036854775807)
    if movie_id is not None:
        if not c.execute('SELECT 1 FROM films WHERE id=?', (movie_id,)).fetchone():
            errors['movie_id'] = 'Choose an existing movie ID, or leave this blank to create a movie.'
        elif c.execute("SELECT 1 FROM film_values WHERE movie_id=? AND source='manual'", (movie_id,)).fetchone():
            errors['movie_id'] = 'This movie already has a manual entry.'
    values = {'title': title}
    for key in ('budget', 'revenue', 'vote_count'):
        values[key] = numeric(raw, key, errors, True)
    values['vote_average'] = numeric(raw, 'vote_average', errors, maximum=10)
    genre_ids = []
    for value in raw.getlist('genre_ids'):
        gid = numeric({'genre': value}, 'genre', errors, True, 1)
        if gid is None or not c.execute('SELECT 1 FROM catalog_genres WHERE id=?', (gid,)).fetchone():
            errors['genres'] = 'Choose genres from the list.'
        elif gid not in genre_ids:
            genre_ids.append(gid)
    ids, names, roles = (raw.getlist(key) for key in ('actor_id', 'actor_name', 'role'))
    if len(ids) != len(names) or len(ids) != len(roles) or len(ids) > 100:
        errors['cast'] = 'Use at most 100 complete cast rows.'
    cast = []
    for index, (aid, name, role) in enumerate(zip(ids, names, roles), 1):
        aid, name, role = aid.strip(), name.strip(), role.strip()
        if not (aid or name or role):
            continue
        key = f'cast row {index}'
        if bool(aid) == bool(name):
            errors[key] = 'Enter either an existing actor ID or a new actor name.'
            continue
        if len(name) > 300 or len(role) > 1000:
            errors[key] = 'Use at most 300 characters for the actor name and 1,000 for the character.'
            continue
        actor_id = numeric({'actor': aid}, 'actor', errors, True, -9223372036854775807) if aid else None
        if aid and (actor_id is None or not c.execute('SELECT 1 FROM people WHERE id=?', (actor_id,)).fetchone()):
            errors[key] = 'That actor ID is absent from the catalog.'
        cast.append(dict(actor_id=actor_id, name=name, role=role or 'Unknown role'))
    if errors:
        raise ValidationError(errors)
    return dict(movie_id=movie_id, values=values, genre_ids=genre_ids, cast=cast)
