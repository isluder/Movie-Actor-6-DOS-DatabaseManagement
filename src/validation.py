"""Shared validation for HTML requests, saved specifications and JSON endpoints."""
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
# Accept existing bookmarked URLs and saved query specifications without a migration.
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
    allowed=('both','movies','tmdb','demo','local') if page_type=='degrees' else ('movies','tmdb','demo','local')
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

def movie(raw):
    errors={};d={'title':str(raw.get('title','')).strip()}
    if not d['title'] or len(d['title'])>300:errors['title']='Enter a title of 1–300 characters.'
    for key in ('budget','revenue','vote_count'):d[key]=numeric(raw,key,errors,True,default=0)
    d['vote_average']=numeric(raw,'vote_average',errors,maximum=10,default=0)
    if errors:raise ValidationError(errors)
    return {key:d[key] for key in ('title','budget','revenue','vote_average','vote_count')}
