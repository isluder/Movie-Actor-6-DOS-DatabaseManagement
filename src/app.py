"""Source-aware Flask catalog. Importing this module never initializes a database."""
from functools import wraps
from contextlib import contextmanager
import getpass
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
from urllib.parse import urlencode

import click
from flask import Flask, abort, flash, g, jsonify, redirect, render_template, request, session, url_for, has_request_context
from werkzeug.security import check_password_hash, generate_password_hash
try:
    from . import database as db, graph, validation as valid, features, dashboard
    from .ingest_data import run_ingestion, DATA_DIR
except ImportError:
    import database as db
    import graph
    import validation as valid
    import features
    import dashboard
    from ingest_data import run_ingestion, DATA_DIR

PAGES={page:features.LABELS[key] for page,key in features.PAGE_FEATURES.items()}

def create_app(config=None):
    app=Flask(__name__)
    app.config.from_mapping(DATABASE=db.DB_PATH,DATA_DIR=str(DATA_DIR),SECRET_KEY=os.environ.get('MOVIE_SECRET_KEY'),
        FEATURE_CONFIG=os.environ.get('MOVIE_CONFIG_FILE',str(features.DEFAULT_CONFIG)),
        SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',SESSION_COOKIE_SECURE=False,MAX_CONTENT_LENGTH=1024*1024)
    app.config.update(config or {})
    app.config['FEATURES']=features.load_features(app.config['FEATURE_CONFIG'],app.config.get('FEATURES'))
    flags=app.config['FEATURES']
    enabled_pages={page:label for page,label in PAGES.items() if flags[features.PAGE_FEATURES[page]]}
    home_endpoint=next(iter(enabled_pages),'setup')
    if not app.config['SECRET_KEY']:
        secret=Path(app.config['DATABASE']).parent/'.session-secret'
        secret.parent.mkdir(parents=True,exist_ok=True)
        try:
            fd=os.open(secret,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        except FileExistsError:pass
        else:
            with os.fdopen(fd,'w') as f:f.write(secrets.token_hex(32))
        app.config['SECRET_KEY']=secret.read_text().strip()
    # Schema creation is explicit through init-db/rebuild; factory construction is read-only for the database.
    @contextmanager
    def connected():
        with db.connection(app.config['DATABASE']) as c:
            if has_request_context() and request.method=='GET':c.execute('BEGIN')
            yield c

    def login_required(admin=False):
        def decorate(fn):
            @wraps(fn)
            def inner(*args,**kwargs):
                if not g.user:
                    if request.path.startswith('/api/'):abort(401)
                    flash('Please log in to continue.','error');return redirect(url_for('login'))
                if admin and not g.user['is_admin']:abort(403)
                return fn(*args,**kwargs)
            return inner
        return decorate

    @app.url_value_preprocessor
    def bound_route_ids(endpoint, values):
        for key,value in (values or {}).items():
            if key in ('movie_id','record_id','query_id') and abs(value)>9223372036854775807:abort(404)

    @app.before_request
    def load_context():
        g.user=None;g.ready=False;g.version='uninitialized'
        required=features.ENDPOINT_FEATURES.get(request.endpoint)
        disabled=required and not flags[required]
        if request.path=='/api/neighborhood' and not flags['interactive_graph']:disabled=True
        if request.endpoint=='actors_api' and not any(flags[key] for key in ('movie_search','six_degrees','catalog_editing')):disabled=True
        if disabled:
            if request.endpoint=='index' and enabled_pages:return redirect(url_for(home_endpoint))
            if request.path.startswith('/api/'):return jsonify(errors={'feature':'This feature is disabled in the application configuration.'}),404
            abort(404,description='This feature is disabled in the application configuration.')
        if not Path(app.config['DATABASE']).exists():
            if request.endpoint not in ('setup','static'):return render_template('setup.html'),503
            return
        with connected() as c:
            if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'").fetchone():
                if request.endpoint not in ('setup','static'):return render_template('setup.html'),503
                return
            g.version=db.version(c);g.ready=g.version!='uninitialized'
            if flags['accounts'] and session.get('uid'):
                row=c.execute('SELECT id,username,display_name,is_admin,session_version FROM users WHERE id=?',(session['uid'],)).fetchone()
                if row and row['session_version']==session.get('uv'):g.user=dict(row)
                else:session.clear()
        if request.method=='POST':
            expected=session.get('csrf','');actual=request.form.get('csrf_token') or request.headers.get('X-CSRF-Token','')
            if not expected or not hmac.compare_digest(expected,actual):abort(400,description='The form expired. Refresh the page and try again.')

    @app.context_processor
    def context():
        session.setdefault('csrf',secrets.token_hex(32))
        choices=[]
        if flags['saved_searches'] and g.get('user'):
            with connected() as c:
                choices=db.dictionaries(c.execute('SELECT id,name,note,page_type FROM saved_queries WHERE user_id=? ORDER BY name,id',(g.user['id'],)))
        return dict(sources=db.SOURCES,pages=PAGES,nav_pages=enabled_pages,features=flags,home_endpoint=home_endpoint,
                    page_features=features.PAGE_FEATURES,sort_fields=valid.SORT_FIELDS,sort_labels=valid.SORT_LABELS,
                    csrf_token=session['csrf'],catalog_version=g.get('version','uninitialized'),saved_choices=choices)

    @app.template_filter('currency')
    def currency(value):
        return 'Unknown' if value is None or value==0 else ('-' if value<0 else '')+f'${abs(value):,.0f}'

    @app.errorhandler(valid.ValidationError)
    def invalid(error):
        if request.path.startswith('/api/'):return jsonify(errors=error.errors),400
        return render_template('error.html',message=str(error)),400

    @app.errorhandler(sqlite3.IntegrityError)
    def integrity(error):
        app.logger.warning('Rejected database write: %s',error)
        return render_template('error.html',message='That change conflicts with existing data. Check the selected IDs and try again.'),400

    @app.route('/setup')
    def setup():return render_template('setup.html')

    def listing(page_type):
        if not g.ready:return render_template('setup.html'),503
        errors={};f=dict(request.args)
        with connected() as c:
            try:
                f=valid.query(request.args,page_type,c)
                result=db.difference_rows(c,f) if page_type=='differences' else db.query_movies(c,page_type,f)
            except valid.ValidationError as e:
                errors=e.errors;result=dict(rows=[],total=0,size=50 if page_type=='index' else 25,sql='',excluded={})
            genre_list=db.genres(c)
            counts=db.stats(c,f.get('source','movies')) if not errors and flags['dashboard'] and page_type in dashboard.DEFAULTS else None
            dashboard_data=dashboard.cards(counts,result,db.SOURCES[f['source']],page_type,flags) if counts is not None else None
        page=int(f.get('page') or 1) if not errors else 1
        def page_url(n):return url_for(page_type)+'?'+urlencode({**dict(request.args),'page':n})
        return render_template('listing.html',page_type=page_type,filters=f,errors=errors,result=result,genres=genre_list,
                               stats=counts,dashboard_data=dashboard_data,page=page,page_url=page_url),400 if errors else 200

    @app.route('/')
    def index():return listing('index')
    @app.route('/hidden-gems')
    def gems():return listing('gems')
    @app.route('/bombs')
    def bombs():return listing('bombs')
    @app.route('/source-differences')
    def differences():return listing('differences')

    @app.route('/movie/<int(signed=True):movie_id>')
    def movie_detail(movie_id):
        with connected() as c:
            movie=db.movie_detail(c,movie_id)
            if not movie:abort(404)
            genre_options=db.genres(c)
            local_genres={r[0] for r in c.execute("SELECT genre_id FROM film_genres WHERE movie_id=? AND source='local'",(movie_id,))}
            records=db.dictionaries(c.execute('''SELECT r.id,r.row_number,r.status,r.reason,s.source,s.kind,s.path,s.sha256,ir.imported_at
                FROM source_records r JOIN source_files s ON s.id=r.file_id JOIN import_runs ir ON ir.id=s.run_id
                WHERE r.movie_id=? ORDER BY s.source,s.kind,r.row_number''',(movie_id,)))
        return render_template('detail.html',movie=movie,records=records,genre_options=genre_options,local_genres=local_genres)

    @app.route('/source-record/<int:record_id>')
    def source_record(record_id):
        with connected() as c:
            row=c.execute('''SELECT r.*,s.source,s.kind,s.path,s.sha256,ir.imported_at FROM source_records r JOIN source_files s ON s.id=r.file_id
                             JOIN import_runs ir ON ir.id=s.run_id WHERE r.id=?''',(record_id,)).fetchone()
            if not row:abort(404)
        return render_template('record.html',record=dict(row))

    @app.route('/movie/new',methods=['GET','POST'])
    @login_required(admin=True)
    def add_movie_route():
        errors={}
        if request.method=='POST':
            try:
                d=valid.movie(request.form)
                with connected() as c:
                    c.execute('BEGIN IMMEDIATE')
                    mid=min(0,c.execute('SELECT COALESCE(MIN(id),0) FROM films').fetchone()[0])-1
                    c.execute('INSERT INTO films(id,title) VALUES(?,?)',(mid,d['title']))
                    c.execute('INSERT INTO film_values(movie_id,source,title,budget,revenue,vote_average,vote_count,signature) VALUES(?,?,?,?,?,?,?,?)',
                              (mid,'local',*d.values(),json.dumps(d,sort_keys=True)))
                    db.audit(c,mid,g.user['id'],'create local movie',d)
                flash('Local movie added. Select Local additions for its numerical metrics.','success')
                return redirect(url_for('movie_detail',movie_id=mid))
            except valid.ValidationError as e:errors=e.errors
        return render_template('movie_form.html',values=request.form,errors=errors,movie_id=None),400 if errors else 200

    @app.route('/movie/<int(signed=True):movie_id>/edit',methods=['GET','POST'])
    @login_required(admin=True)
    def edit_movie_route(movie_id):
        source=request.values.get('source','movies');errors={}
        if source not in db.SOURCES:abort(400)
        with connected() as c:
            if not c.execute('SELECT 1 FROM films WHERE id=?',(movie_id,)).fetchone():abort(404)
            rows=c.execute('SELECT * FROM film_values WHERE movie_id=? AND source=?',(movie_id,source)).fetchall()
            if not rows:abort(400,description='Select an available source record to override.')
            current=c.execute('SELECT * FROM local_overrides WHERE movie_id=? AND source=?',(movie_id,source)).fetchone()
            values=dict(current or rows[0])
            if request.method=='POST':
                try:
                    d=valid.movie(request.form)
                    c.execute('''INSERT INTO local_overrides VALUES(?,?,?,?,?,?,?) ON CONFLICT(movie_id,source) DO UPDATE SET
                        title=excluded.title,budget=excluded.budget,revenue=excluded.revenue,vote_average=excluded.vote_average,vote_count=excluded.vote_count''',(movie_id,source,*d.values()))
                    db.audit(c,movie_id,g.user['id'],'local override',{'source':source,'before':values,'after':d})
                    flash('Local override saved; imported originals are unchanged.','success')
                    return redirect(url_for('movie_detail',movie_id=movie_id))
                except valid.ValidationError as e:errors=e.errors;values=request.form
        return render_template('movie_form.html',values=values,errors=errors,movie_id=movie_id,source=source),400 if errors else 200

    @app.route('/movie/<int(signed=True):movie_id>/delete',methods=['POST'])
    @login_required(admin=True)
    def delete_movie_route(movie_id):
        with connected() as c:
            if not c.execute('SELECT 1 FROM films WHERE id=?',(movie_id,)).fetchone():abort(404)
            restore=request.form.get('restore')=='1'
            c.execute('UPDATE films SET hidden=? WHERE id=?',(0 if restore else 1,movie_id))
            db.audit(c,movie_id,g.user['id'],'restore movie' if restore else 'hide movie',{})
        flash('Movie removed from browsing and connection searches; its source originals remain inspectable.','success')
        return redirect(url_for('index'))

    @app.route('/movie/<int(signed=True):movie_id>/genres',methods=['POST'])
    @login_required(admin=True)
    def edit_genres(movie_id):
        with connected() as c:
            if not c.execute('SELECT 1 FROM films WHERE id=?',(movie_id,)).fetchone():abort(404)
            ids=[]
            for s in request.form.getlist('genre_ids'):
                if not s.isdecimal() or not c.execute('SELECT 1 FROM catalog_genres WHERE id=?',(int(s),)).fetchone():raise valid.ValidationError({'genre_ids':'Choose valid genre IDs.'})
                ids.append(int(s))
            c.execute("DELETE FROM film_genres WHERE movie_id=? AND source='local'",(movie_id,))
            c.executemany("INSERT OR IGNORE INTO film_genres VALUES(?,?,'local')",[(movie_id,i) for i in ids])
            db.audit(c,movie_id,g.user['id'],'set local genre additions',ids)
        return redirect(url_for('movie_detail',movie_id=movie_id))

    @app.route('/movie/<int(signed=True):movie_id>/cast/add',methods=['POST'])
    @login_required(admin=True)
    def add_cast_route(movie_id):
        with connected() as c:
            c.execute('BEGIN IMMEDIATE')
            if not c.execute('SELECT 1 FROM films WHERE id=? AND hidden=0',(movie_id,)).fetchone():abort(404)
            mode=request.form.get('actor_mode','existing');errors={}
            if mode=='new':
                name=request.form.get('actor_name','').strip()
                if not name or len(name)>300:raise valid.ValidationError({'actor_name':'Enter a name of 1–300 characters.'})
                aid=min(0,c.execute('SELECT COALESCE(MIN(id),0) FROM people').fetchone()[0])-1
                c.execute('INSERT INTO people VALUES(?,?)',(aid,name));c.execute("INSERT INTO actor_names VALUES(?,'local',?)",(aid,name))
            elif mode=='existing':
                aid=valid.numeric(request.form,'actor_id',errors,True,-9223372036854775807)
                if errors or aid is None or not c.execute('SELECT 1 FROM people WHERE id=?',(aid,)).fetchone():raise valid.ValidationError({'actor_id':'Select an existing actor by ID.'})
            else:raise valid.ValidationError({'actor_mode':'Choose existing or new actor.'})
            role=request.form.get('character_name','').strip() or 'Unknown role'
            if len(role)>1000:raise valid.ValidationError({'character_name':'Use at most 1,000 characters.'})
            c.execute("INSERT OR IGNORE INTO cast_roles VALUES(?,?,?,'local')",(movie_id,aid,role))
            db.audit(c,movie_id,g.user['id'],'add local cast',{'actor_id':aid,'role':role})
        return redirect(url_for('movie_detail',movie_id=movie_id))

    @app.route('/movie/<int(signed=True):movie_id>/cast/remove',methods=['POST'])
    @login_required(admin=True)
    def remove_cast_route(movie_id):
        errors={};aid=valid.numeric(request.form,'actor_id',errors,True,-9223372036854775807)
        if errors or aid is None:raise valid.ValidationError({'actor_id':'Choose a valid actor.'})
        with connected() as c:
            source=request.form.get('source','local');role=request.form.get('role','')
            if not c.execute('SELECT 1 FROM cast_roles WHERE movie_id=? AND actor_id=? AND role=? AND source=?',(movie_id,aid,role,source)).fetchone():abort(404)
            if request.form.get('restore')=='1':
                c.execute('DELETE FROM cast_suppressions WHERE movie_id=? AND actor_id=? AND role=? AND source=?',(movie_id,aid,role,source))
            elif source=='local':
                c.execute("DELETE FROM cast_roles WHERE movie_id=? AND actor_id=? AND role=? AND source='local'",(movie_id,aid,role))
            else:
                c.execute('INSERT OR IGNORE INTO cast_suppressions VALUES(?,?,?,?)',(movie_id,aid,role,source))
            db.audit(c,movie_id,g.user['id'],'restore cast' if request.form.get('restore')=='1' else 'remove cast',{'actor_id':aid,'role':role,'source':source})
        return redirect(url_for('movie_detail',movie_id=movie_id))

    @app.route('/register',methods=['GET','POST'])
    def register():
        errors={}
        if request.method=='POST':
            username=request.form.get('username','').strip();name=request.form.get('display_name','').strip();password=request.form.get('password','')
            if not (3<=len(username)<=40 and username.isascii() and all(x.isalnum() or x in '._-' for x in username)):errors['username']='Use 3–40 letters, numbers, dots, underscores or hyphens.'
            if not 1<=len(name)<=80:errors['display_name']='Use 1–80 characters.'
            if not 12<=len(password)<=256:errors['password']='Use 12–256 characters.'
            if not errors:
                with connected() as c:
                    if c.execute('SELECT 1 FROM users WHERE username=?',(username,)).fetchone():errors['username']='That username is unavailable.'
                    else:
                        c.execute('INSERT INTO users(username,display_name,password_hash) VALUES(?,?,?)',(username,name,generate_password_hash(password)))
                        flash('Account created. Please log in.','success');return redirect(url_for('login'))
        return render_template('auth.html',mode='register',errors=errors),400 if errors else 200

    @app.route('/login',methods=['GET','POST'])
    def login():
        errors={}
        if request.method=='POST':
            username=request.form.get('username','').strip()[:40];password=request.form.get('password','')[:256]
            key=(request.remote_addr or 'local')+':'+username.casefold();now=time.time()
            with connected() as c:
                c.execute('DELETE FROM login_attempts WHERE last_attempt<?',(now-900,))
                attempt=c.execute('SELECT * FROM login_attempts WHERE key=?',(key,)).fetchone()
                if attempt and attempt['failures']>=5:return render_template('auth.html',mode='login',errors={'login':'Too many attempts. Try again in 15 minutes.'}),429
                row=c.execute('SELECT * FROM users WHERE username=?',(username,)).fetchone()
                checked=check_password_hash(row['password_hash'] if row else app.config['_DUMMY_HASH'],password)
                if not row or not checked:
                    c.execute('INSERT INTO login_attempts VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET failures=failures+1,last_attempt=excluded.last_attempt',(key,now))
                    errors['login']='Invalid username or password.'
                else:
                    c.execute('DELETE FROM login_attempts WHERE key=?',(key,))
                    session.clear();session.update(uid=row['id'],uv=row['session_version'],csrf=secrets.token_hex(32))
                    return redirect(url_for('index'))
        return render_template('auth.html',mode='login',errors=errors),400 if errors else 200

    app.config['_DUMMY_HASH']=generate_password_hash(secrets.token_hex(24))

    @app.route('/logout',methods=['POST'])
    def logout():session.clear();return redirect(url_for('index'))

    @app.route('/password',methods=['GET','POST'])
    @login_required()
    def password():
        errors={}
        if request.method=='POST':
            new=request.form.get('password','')
            with connected() as c:
                row=c.execute('SELECT * FROM users WHERE id=?',(g.user['id'],)).fetchone()
                if not check_password_hash(row['password_hash'],request.form.get('current_password','')):errors['current_password']='Current password is incorrect.'
                if not 12<=len(new)<=256:errors['password']='Use 12–256 characters.'
                if not errors:
                    c.execute('UPDATE users SET password_hash=?,session_version=session_version+1 WHERE id=?',(generate_password_hash(new),g.user['id']))
                    session.clear();flash('Password changed. Please log in again.','success');return redirect(url_for('login'))
        return render_template('auth.html',mode='password',errors=errors),400 if errors else 200

    @app.route('/my-searches',methods=['GET','POST'])
    @login_required()
    def saved_queries():
        with connected() as c:
            if request.method=='POST':
                page_type=request.form.get('page_type')
                if page_type not in PAGES:abort(400)
                if not flags[features.PAGE_FEATURES[page_type]]:abort(404,description='This search feature is disabled.')
                try:raw=json.loads(request.form.get('spec','{}'))
                except ValueError:abort(400)
                if not isinstance(raw,dict):abort(400)
                spec=valid.query(raw,page_type,c)
                if page_type=='degrees' and (spec['start'] is None or spec['end'] is None):raise valid.ValidationError({'actors':'Select both endpoints before saving.'})
                name=request.form.get('name','').strip();note=request.form.get('note','').strip()
                if not 1<=len(name)<=100 or len(note)>2000:raise valid.ValidationError({'name':'Use a name of 1–100 characters and a note up to 2,000 characters.'})
                existing=request.form.get('existing_query_id')
                if existing:
                    row=c.execute('SELECT * FROM saved_queries WHERE id=? AND user_id=? AND page_type=?',(existing,g.user['id'],page_type)).fetchone()
                    if not row:abort(404)
                    c.execute('UPDATE saved_queries SET name=?,note=?,spec=?,catalog_version=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
                              (name,note,json.dumps(spec),db.version(c),existing))
                else:
                    c.execute('INSERT INTO saved_queries(user_id,name,note,page_type,spec,catalog_version) VALUES(?,?,?,?,?,?)',
                              (g.user['id'],name,note,page_type,json.dumps(spec),db.version(c)))
                flash('Search saved.','success');return redirect(url_for('saved_queries'))
            rows=db.dictionaries(c.execute('SELECT * FROM saved_queries WHERE user_id=? ORDER BY page_type,favorite DESC,name,id',(g.user['id'],)))
        return render_template('saved.html',queries=rows)

    @app.route('/my-searches/<int:query_id>/open')
    @login_required()
    def open_query(query_id):
        with connected() as c:
            row=c.execute('SELECT * FROM saved_queries WHERE id=? AND user_id=?',(query_id,g.user['id'])).fetchone()
            if not row:abort(404)
            if not flags[features.PAGE_FEATURES[row['page_type']]]:abort(404,description='This search feature is disabled. Your saved settings are retained.')
            if row['catalog_version']!=db.version(c):flash('The catalog changed since this search was saved. Results have been refreshed.','info')
            spec=json.loads(row['spec'])
        return redirect(url_for(row['page_type'])+'?'+urlencode({**{k:('' if v is None else v) for k,v in spec.items()},'_saved':query_id}))

    @app.route('/my-searches/<int:query_id>',methods=['POST'])
    @login_required()
    def update_query(query_id):
        with connected() as c:
            row=c.execute('SELECT * FROM saved_queries WHERE id=? AND user_id=?',(query_id,g.user['id'])).fetchone()
            if not row:abort(404)
            action=request.form.get('action','rename')
            if action=='delete':c.execute('DELETE FROM saved_queries WHERE id=?',(query_id,))
            elif action=='favorite':c.execute('UPDATE saved_queries SET favorite=1-favorite,updated_at=CURRENT_TIMESTAMP WHERE id=?',(query_id,))
            elif action=='update':
                if not flags[features.PAGE_FEATURES[row['page_type']]]:abort(404,description='This search feature is disabled.')
                try:raw=json.loads(request.form.get('spec','{}'))
                except ValueError:abort(400)
                if not isinstance(raw,dict):abort(400)
                spec=valid.query(raw,row['page_type'],c)
                c.execute('UPDATE saved_queries SET spec=?,catalog_version=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(json.dumps(spec),db.version(c),query_id))
            elif action=='rename':
                name=request.form.get('name','').strip();note=request.form.get('note','').strip()
                if not 1<=len(name)<=100 or len(note)>2000:raise valid.ValidationError({'name':'Enter a name of 1–100 characters and a note up to 2,000 characters.'})
                c.execute('UPDATE saved_queries SET name=?,note=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(name,note,query_id))
            else:abort(400)
        return redirect(url_for('saved_queries'))

    @app.route('/six-degrees')
    def degrees():
        errors={};f=dict(request.args);result=None
        with connected() as c:
            try:
                f=valid.query(request.args,'degrees',c)
                if not flags['interactive_graph']:f['depth']=0
                if f['start'] is not None and f['end'] is not None:result=graph.result(c,app.config['DATABASE'],f)
            except valid.ValidationError as e:errors=e.errors
        with connected() as c:
            labels={key:(c.execute('SELECT name FROM people WHERE id=?',(f.get(key),)).fetchone() or [''])[0] for key in ('start','end')}
        return render_template('degrees.html',page_type='degrees',filters=f,errors=errors,graph_result=result,actor_labels=labels),400 if errors else 200

    @app.route('/api/actors')
    def actors_api():
        with connected() as c:return jsonify(actors=db.suggestions(c,request.args.get('q','')[:100]),catalog_version=db.version(c))

    @app.route('/api/connections')
    @app.route('/api/neighborhood')
    def connections_api():
        with connected() as c:
            f=valid.query(request.args,'degrees',c)
            if not flags['interactive_graph']:f['depth']=0
            if f['start'] is None or f['end'] is None:raise valid.ValidationError({'actors':'Select two actors.'})
            return jsonify(graph.result(c,app.config['DATABASE'],f))

    @app.route('/api/expand-node')
    def expand_node_api():
        with connected() as c:
            f=valid.query(request.args,'degrees',c)
            errors={}
            node=request.args.get('node','').split(':')
            if len(node)!=2 or node[0] not in ('actor','movie'):
                raise valid.ValidationError({'node':'Choose an actor or movie node.'})
            entity_id=valid.numeric({'id':node[1]},'id',errors,True,-9223372036854775807)
            offset=valid.numeric(request.args,'offset',errors,True,0,1_000_000,0)
            limit=valid.numeric(request.args,'limit',errors,True,1,15,15)
            if errors:raise valid.ValidationError(errors)
            table='people' if node[0]=='actor' else 'films'
            visible=' AND hidden=0' if node[0]=='movie' else ''
            if entity_id is None or not c.execute(f'SELECT 1 FROM {table} WHERE id=?'+visible,(entity_id,)).fetchone():
                return jsonify(errors={'node':'This node is absent from the current catalog.'}),404
            if request.args.get('catalog_version') not in (None,db.version(c)):
                return jsonify(errors={'catalog':'The catalog changed. Find the connection again before expanding.'}),409
            return jsonify(graph.expand(c,app.config['DATABASE'],node[0],entity_id,f['source'],offset,limit))

    @app.route('/imports',methods=['GET','POST'])
    @login_required(admin=True)
    def imports():
        if request.method=='POST':
            selection=request.form.get('dataset','both')
            if request.form.get('confirmation')!='REBUILD':raise valid.ValidationError({'confirmation':'Type REBUILD to reset local catalog changes. Accounts and saved queries will remain.'})
            try:
                report=run_ingestion(app.config['DATA_DIR'],selection,db_path=app.config['DATABASE'])
                flash('Catalog rebuilt. Backup: '+report['backup'],'success')
            except (ValueError,OSError,sqlite3.Error):
                app.logger.exception('Rebuild failed');flash('Rebuild failed; the previous catalog remains active. Check the server log for details.','error')
            return redirect(url_for('imports'))
        with connected() as c:
            row=c.execute("SELECT value FROM catalog_meta WHERE key='report'").fetchone()
            rejected=db.dictionaries(c.execute('''SELECT r.id,r.row_number,r.status,r.reason,s.source,s.kind FROM source_records r JOIN source_files s ON s.id=r.file_id
                WHERE r.status!='valid' ORDER BY r.id LIMIT 100'''))
        return render_template('imports.html',report=json.loads(row[0]) if row else {},rejected=rejected)

    @app.cli.command('init-db')
    def init_command():
        db.init_db(app.config['DATABASE']);click.echo('Schema initialized. Use create-admin, then import a catalog.')

    @app.cli.command('create-admin')
    @click.argument('username')
    @click.option('--display-name',default=None)
    @click.password_option(confirmation_prompt=True)
    def create_admin(username,display_name,password):
        if not 12<=len(password)<=256:raise click.ClickException('Password must contain 12–256 characters.')
        if not (3<=len(username)<=40 and username.isascii() and all(x.isalnum() or x in '._-' for x in username)):raise click.ClickException('Use a username of 3–40 ASCII letters, numbers, dots, underscores or hyphens.')
        db.init_db(app.config['DATABASE'])
        with connected() as c:
            if c.execute('SELECT 1 FROM users WHERE username=?',(username,)).fetchone():raise click.ClickException('Username already exists.')
            c.execute('INSERT INTO users(username,display_name,password_hash,is_admin) VALUES(?,?,?,1)',(username,display_name or username,generate_password_hash(password)))
        click.echo('Admin created.')

    @app.cli.command('reset-password')
    @click.argument('username')
    @click.password_option(confirmation_prompt=True)
    def reset_password(username,password):
        if not 12<=len(password)<=256:raise click.ClickException('Password must contain 12–256 characters.')
        with connected() as c:
            if not c.execute('UPDATE users SET password_hash=?,session_version=session_version+1 WHERE username=?',(generate_password_hash(password),username)).rowcount:raise click.ClickException('Unknown username.')
        click.echo('Password reset; previous sessions invalidated.')

    @app.cli.command('rebuild-catalog')
    @click.option('--dataset',type=click.Choice(['both','tmdb','movies','demo']),default='both')
    @click.confirmation_option(prompt='Rebuild the catalog and reset local changes? Accounts and saved searches remain.')
    def rebuild_catalog(dataset):
        click.echo(json.dumps(run_ingestion(app.config['DATA_DIR'],dataset,db_path=app.config['DATABASE']),indent=2))

    return app

if __name__=='__main__':create_app().run(host='127.0.0.1',port=5000)
