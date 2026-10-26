"""Source-aware Flask catalog. Importing this module never initializes a database."""
from contextlib import contextmanager
import json
import hmac
import secrets
import os
from pathlib import Path
import sqlite3
from urllib.parse import urlencode

import click
from flask import Flask, abort, g, session, jsonify, redirect, render_template, request, url_for, has_request_context
try:
    from . import database as db, graph, validation as valid, features, dashboard, sql_search as sql_tools
    from .ingest_data import run_ingestion, DATA_DIR
except ImportError:
    import database as db
    import graph
    import validation as valid
    import features
    import dashboard
    import sql_search as sql_tools
    from ingest_data import run_ingestion, DATA_DIR

PAGES={page:features.LABELS[key] for page,key in features.PAGE_FEATURES.items()}

def create_app(config=None):
    app=Flask(__name__)
    app.config.from_mapping(DATABASE=db.DB_PATH,DATA_DIR=str(DATA_DIR),SECRET_KEY=os.environ.get('MOVIE_SECRET_KEY') or secrets.token_hex(32),
        FEATURE_CONFIG=os.environ.get('MOVIE_CONFIG_FILE',str(features.DEFAULT_CONFIG)),
        MAX_CONTENT_LENGTH=1024*1024)
    app.config.update(config or {})
    app.config['FEATURES']=features.load_features(app.config['FEATURE_CONFIG'],app.config.get('FEATURES'))
    flags=app.config['FEATURES']
    enabled_pages={page:label for page,label in PAGES.items() if flags[features.PAGE_FEATURES[page]]}
    home_endpoint=next(iter(enabled_pages),'setup')
    # Schema creation is explicit through init-db/rebuild; factory construction is read-only for the database.
    @contextmanager
    def connected():
        with db.connection(app.config['DATABASE']) as c:
            if has_request_context() and request.method=='GET':c.execute('BEGIN')
            yield c

    @app.url_value_preprocessor
    def bound_route_ids(endpoint, values):
        for key,value in (values or {}).items():
            if key in ('movie_id',) and abs(value)>9223372036854775807:abort(404)

    @app.before_request
    def load_context():
        g.ready=False;g.version='uninitialized'
        if request.endpoint in (None,'static'):return
        required=features.ENDPOINT_FEATURES.get(request.endpoint)
        disabled=required and not flags[required]
        if request.path=='/api/neighborhood' and not flags['interactive_graph']:disabled=True
        if request.endpoint=='actors_api' and not any(flags[key] for key in ('movie_search','six_degrees')):disabled=True
        if disabled:
            if request.endpoint=='index' and enabled_pages:return redirect(url_for(home_endpoint))
            if request.path.startswith('/api/'):return jsonify(errors={'feature':'This feature is disabled in the application configuration.'}),404
            abort(404,description='This feature is disabled in the application configuration.')
        if not Path(app.config['DATABASE']).exists():
            if request.endpoint not in ('setup','static'):return render_template('setup.html'),503
            return
        with connected() as c:
            if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='catalog_meta'").fetchone():
                if request.endpoint not in ('setup','static'):return render_template('setup.html'),503
                return
            g.version=db.version(c)
            g.ready=g.version!='uninitialized' and db.schema_version(c)==db.SCHEMA_VERSION
        if not g.ready and request.endpoint!='setup':return render_template('setup.html'),503
    @app.context_processor
    def context():
        return dict(sources=db.SOURCES,pages=PAGES,nav_pages=enabled_pages,features=flags,home_endpoint=home_endpoint,
                    page_features=features.PAGE_FEATURES,sort_fields=valid.SORT_FIELDS,sort_labels=valid.SORT_LABELS,
                    catalog_version=g.get('version','uninitialized'))

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
            if page_type=='differences' and flags['dashboard'] and not errors:
                dashboard_data=dashboard.difference_cards(result)
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

    @app.route('/sql-search', methods=['GET', 'POST'])
    def sql_search():
        sql = request.form.get('sql', sql_tools.DEFAULT_SQL)
        result = None
        error = None
        if request.method == 'POST':
            try:result = sql_tools.search(app.config['DATABASE'], sql)
            except ValueError as exc:error = str(exc)
        with connected() as c:
            schema = db.dictionaries(c.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name"))
        return render_template('sql_search.html', sql=sql, result=result, error=error, schema=schema, examples=sql_tools.EXAMPLES), 400 if error else 200

    @app.route('/manual-entry', methods=['GET', 'POST'])
    def manual_entry():
        errors = {}
        session.setdefault('csrf', secrets.token_hex(32))
        if request.method == 'POST':
            if not hmac.compare_digest(session['csrf'].encode(), request.form.get('csrf_token', '').encode()):
                abort(400, description='The form expired. Refresh the page and try again.')
            try:
                with connected() as c:
                    c.execute('BEGIN IMMEDIATE')
                    entry = valid.manual_entry(request.form, c)
                    mid = db.add_manual_entry(c, entry)
                return redirect(url_for('movie_detail', movie_id=mid), code=303)
            except valid.ValidationError as exc:errors = exc.errors
        with connected() as c:genre_list = db.genres(c)
        cast_rows = list(zip(request.form.getlist('actor_id'), request.form.getlist('actor_name'), request.form.getlist('role'))) or [('', '', '')]
        return render_template('manual_entry.html', values=request.form, errors=errors, genres=genre_list,
                               cast_rows=cast_rows, csrf_token=session['csrf']), 400 if errors else 200

    @app.route('/movie/<int(signed=True):movie_id>')
    def movie_detail(movie_id):
        with connected() as c:
            movie=db.movie_detail(c,movie_id)
            if not movie:abort(404)
        return render_template('detail.html',movie=movie)

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
        return render_template('degrees.html',page_type='degrees',filters=f,errors=errors,graph_result=result,actor_labels=labels,dashboard_data=dashboard.degree_cards() if flags['dashboard'] else None),400 if errors else 200

    @app.route('/api/actor-statistics')
    def actor_statistics_api():
        with connected() as c:
            f=valid.query(request.args,'degrees',c)
            if f['start'] is None:raise valid.ValidationError({'start':'Select a starting actor.'})
            out=graph.actor_statistics(c,app.config['DATABASE'],f['start'],f['source'])
            out['dashboard']=dashboard.degree_cards(out)
            return jsonify(out)

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
            if entity_id is None or not c.execute(f'SELECT 1 FROM {table} WHERE id=?',(entity_id,)).fetchone():
                return jsonify(errors={'node':'This node is absent from the current catalog.'}),404
            if request.args.get('catalog_version') not in (None,db.version(c)):
                return jsonify(errors={'catalog':'The catalog changed. Find the connection again before expanding.'}),409
            return jsonify(graph.expand(c,app.config['DATABASE'],node[0],entity_id,f['source'],offset,limit))

    @app.cli.command('init-db')
    def init_command():
        try:db.init_db(app.config['DATABASE'])
        except ValueError as error:raise click.ClickException(str(error)) from error
        click.echo('Schema initialized. Import a catalog with rebuild-catalog or src/ingest_data.py.')

    @app.cli.command('rebuild-catalog')
    @click.option('--dataset',type=click.Choice(['both','tmdb','movies','demo']),default='both')
    @click.confirmation_option(prompt='Back up and rebuild the movie catalog?')
    def rebuild_catalog(dataset):
        click.echo(json.dumps(run_ingestion(app.config['DATA_DIR'],dataset,db_path=app.config['DATABASE']),indent=2))

    return app

if __name__=='__main__':create_app().run(host='127.0.0.1',port=5000)
