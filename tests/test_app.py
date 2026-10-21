import csv
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from src import database as db, graph, validation, features
from src.app import create_app
from src.ingest_data import run_ingestion, stage_catalog, activate
from werkzeug.security import generate_password_hash, check_password_hash


def fixtures(root):
    for source,folder,movie_name,credits_name in [('tmdb','TMDB 5000 Movie Dataset','tmdb_5000_movies.csv','tmdb_5000_credits.csv'),('movies','The Movies Dataset','movies_metadata.csv','credits.csv')]:
        path=Path(root)/folder;path.mkdir()
        values=[dict(id=1,title="Apostrophe's Movie",budget=10000000,revenue=5000000,vote_average=7.5 if source=='movies' else 8,vote_count=100,genres=json.dumps([dict(id=18,name='Drama')])),
                dict(id=2,title='Second',budget=1000000,revenue=2000000,vote_average=8,vote_count=200,genres='[]'),
                dict(id=3,title='No known budget',budget=0,revenue=0,vote_average=9,vote_count=100,genres='[]')]
        if source=='movies':
            values += [dict(values[1]),{**values[1],'vote_average':9},{**values[2],'id':'not-an-id'}]
        else:values += [{**values[2],'id':4,'title':'TMDB exclusive'}]
        with (path/movie_name).open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(values[0]));w.writeheader();w.writerows(values)
        key='movie_id' if source=='tmdb' else 'id'
        with (path/credits_name).open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=[key,'cast']);w.writeheader()
            for mid,actors in [(1,[(10,'Same Name','Hero'),(11,'Same Name','Villain'),(10,'Same Name','Narrator')]),(2,[(11,'Same Name','Other'),(12,'Third Actor','Lead')]),(3,[])]:
                w.writerow({key:mid,'cast':json.dumps([dict(id=i,name=n,character=r) for i,n,r in actors])})


class AppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name);fixtures(cls.root)
        cls.feature_config=cls.root/'test-features.yaml'
        cls.feature_config.write_text('application_features: {}\n')
        cls.seed=cls.root/'seed.db';run_ingestion(cls.root,'both',db_path=cls.seed)
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def setUp(self):
        self.temp_case=tempfile.TemporaryDirectory();self.path=Path(self.temp_case.name)/'test.db'
        with db.connection(self.seed) as source,db.connection(self.path) as target:source.backup(target)
        self.app=create_app(dict(TESTING=True,DATABASE=str(self.path),DATA_DIR=str(self.root),SECRET_KEY='test-secret',FEATURE_CONFIG=str(self.feature_config)))
        self.client=self.app.test_client()
        with db.connection(self.path) as c:
            for username,admin in [('admin',1),('alice',0),('bob',0)]:
                c.execute('INSERT INTO users(username,display_name,password_hash,is_admin) VALUES(?,?,?,?)',(username,username,generate_password_hash('password-for-tests'),admin))
    def tearDown(self):self.temp_case.cleanup()
    def csrf(self,client=None):
        client=client or self.client;client.get('/login')
        with client.session_transaction() as s:return s['csrf']
    def post(self,url,data=None,client=None):
        client=client or self.client
        return client.post(url,data={**(data or {}),'csrf_token':self.csrf(client)})
    def login(self,user='admin',client=None):
        self.assertEqual(self.post('/login',{'username':user,'password':'password-for-tests'},client).status_code,302)

    def test_import_coverage_variants_and_raw(self):
        with db.connection(self.path) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM films').fetchone()[0],4)
            self.assertEqual(c.execute("SELECT variants FROM source_metrics WHERE movie_id=2 AND source='movies'").fetchone()[0],2)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM source_records WHERE status='rejected'").fetchone()[0],1)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM cast_roles WHERE actor_id=10 AND movie_id=1 AND source='movies'").fetchone()[0],2)
            self.assertFalse(c.execute('PRAGMA foreign_key_check').fetchall())

    def test_pages_render_and_pagination(self):
        for url in ['/','/hidden-gems','/bombs','/source-differences','/source-differences?field=vote_average','/movie/1','/six-degrees','/six-degrees?start=10&end=12&depth=1','/register','/login']:
            with self.subTest(url=url):self.assertEqual(self.client.get(url).status_code,200)
        self.login()
        for url in ['/imports','/my-searches','/movie/new','/movie/1/edit?source=movies','/source-record/1']:
            with self.subTest(url=url):self.assertEqual(self.client.get(url).status_code,200)
        with db.connection(self.path) as c:
            c.executemany('INSERT INTO films(id,title) VALUES(?,?)',[(i,'Extra '+str(i)) for i in range(100,160)])
        response=self.client.get('/')
        self.assertIn(b'64 matches',response.data)
        self.assertIn(b'Next',response.data)

    def feature_app(self, flags=None, config_file=None):
        config=dict(TESTING=True,DATABASE=str(self.path),DATA_DIR=str(self.root),SECRET_KEY='test-secret',FEATURE_CONFIG=str(self.feature_config),FEATURES=flags or {})
        if config_file is not None:config['FEATURE_CONFIG']=config_file
        return create_app(config)

    def test_yaml_feature_configuration(self):
        config=Path(self.temp_case.name)/'features.yaml'
        config.write_text('application_features:\n  Movie Search: Disable\n  Password Changes: Disable\n')
        app=self.feature_app(config_file=config)
        client=app.test_client()
        self.assertEqual(client.get('/').location,'/hidden-gems')
        self.assertEqual(client.get('/password').status_code,404)
        self.assertNotIn(b'>Movie Search</a>',client.get('/hidden-gems').data)
        self.assertIn(b'Bombed at the Box Office',client.get('/bombs').data)
        # A running process uses its startup snapshot until restarted.
        config.write_text('application_features:\n  Movie Search: Enable\n')
        self.assertEqual(client.get('/').status_code,302)
        self.assertEqual(self.feature_app(config_file=config).test_client().get('/').status_code,200)
        for text in ['application_features: [Movie Search]', 'application_features:\n  Movie Search: Maybe',
                     'application_features:\n  Movie Search: Enable\n  Movie Search: Disable',
                     'application_features:\n  Unknown Feature: Enable', 'other: {}', 'application_features: [']:
            config.write_text(text)
            with self.subTest(text=text),self.assertRaises(ValueError):self.feature_app(config_file=config)
        with self.assertRaises(ValueError):self.feature_app(config_file=config.with_name('missing.yaml'))

    def test_disabled_accounts_and_dependent_features(self):
        app=self.feature_app({'accounts':False})
        client=app.test_client()
        # An existing signed-in session cannot bypass a disabled account feature.
        with db.connection(self.path) as c:admin=c.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
        with client.session_transaction() as session:session.update(uid=admin,uv=0,csrf='test')
        for url in ['/login','/register','/password','/my-searches','/my-searches/1/open','/imports','/movie/new','/movie/1/edit']:
            with self.subTest(url=url):self.assertEqual(client.get(url).status_code,404)
        for url in ['/login','/register','/logout','/password','/my-searches','/my-searches/1','/imports','/movie/new',
                    '/movie/1/edit','/movie/1/delete','/movie/1/genres','/movie/1/cast/add','/movie/1/cast/remove']:
            with self.subTest(url=url):self.assertEqual(client.post(url).status_code,404)
        page=client.get('/').data
        for label in [b'Log in',b'Create account',b'My Searches',b'Save or update',b'>Password</a>']:
            self.assertNotIn(label,page)
        self.assertNotIn(b'Admin actions',client.get('/movie/1').data)
        self.assertEqual(client.get('/six-degrees').status_code,200)
        with db.connection(self.path) as c:self.assertEqual(c.execute('SELECT count(*) FROM users').fetchone()[0],3)

    def test_independent_feature_switches_and_saved_searches(self):
        self.login('alice')
        self.post('/my-searches',{'name':'Retained gems','page_type':'gems','spec':'{}'})
        with db.connection(self.path) as c:qid=c.execute('SELECT id FROM saved_queries').fetchone()[0]
        app=self.feature_app({'hidden_gems':False,'box_office':False,'source_differences':False,
            'registration':False,'password_changes':False,'catalog_editing':False,'catalog_imports':False,
            'interactive_graph':False,'dashboard':False,'sql_previews':False,'source_provenance':False})
        client=app.test_client();self.login('alice',client)
        for url in ['/hidden-gems','/bombs','/source-differences','/register','/password','/source-record/1',
                    '/imports','/movie/new','/api/neighborhood?start=10&end=12','/api/expand-node?node=actor:10']:
            with self.subTest(url=url):self.assertEqual(client.get(url).status_code,404)
        listing=client.get('/').data
        for label in [b'Hidden Gems',b'Bombed at the Box Office',b'Source Differences',b'stat-card',b'View parameterized SQL']:
            self.assertNotIn(label,listing)
        path=client.get('/six-degrees?start=10&end=12&depth=3')
        self.assertEqual(path.status_code,200)
        self.assertIn(b'Shortest path: 2 degrees.',path.data)
        self.assertNotIn(b'cytoscape',path.data)
        self.assertNotIn(b'graph.js',path.data)
        self.assertEqual(client.get('/api/connections?start=10&end=12&depth=3').json['depth'],0)
        self.assertNotIn(b'Original rows and provenance',client.get('/movie/1').data)
        self.assertIn(b'Retained gems',client.get('/my-searches').data)
        self.assertIn(b'Feature disabled',client.get('/my-searches').data)
        self.assertEqual(client.get(f'/my-searches/{qid}/open').status_code,404)
        self.assertEqual(self.post('/my-searches',{'name':'Blocked','page_type':'gems','spec':'{}'},client).status_code,404)
        self.assertEqual(self.post(f'/my-searches/{qid}',{'action':'update','spec':'{}'},client).status_code,404)
        self.assertEqual(self.post(f'/my-searches/{qid}',{'action':'rename','name':'Kept'},client).status_code,302)
        self.assertEqual(self.post(f'/my-searches/{qid}',{'action':'delete'},client).status_code,302)
        disabled=self.feature_app({'saved_searches':False,'six_degrees':False}).test_client()
        self.assertNotIn(b'Log in</a> to save',disabled.get('/').data)
        self.assertNotIn(b'href="/six-degrees',disabled.get('/movie/1').data)
        for url in ['/my-searches','/six-degrees','/api/connections?start=10&end=12','/api/expand-node?node=actor:10']:
            self.assertEqual(disabled.get(url).status_code,404)

    def test_validation_and_same_cast_member(self):
        for val in ['abc','NaN','Infinity','-1','11']:
            self.assertEqual(self.client.get('/?min_rating='+val).status_code,400)
        self.assertEqual(self.client.get('/?min_rating=8&max_rating=7').status_code,400)
        self.assertEqual(self.client.get('/?min_budget=-1').status_code,400)
        self.assertEqual(self.client.get('/api/connections?start=10000&end=10').status_code,400)
        self.assertEqual(self.client.get('/?actor_id=10&character=Villain').status_code,200)
        self.assertIn(b'0 matches',self.client.get('/?actor_id=10&character=Villain').data)
        self.assertIn(b'1 matches',self.client.get('/?actor_id=10&character=Hero').data)
        self.assertEqual(len(self.client.get('/api/actors?q=Same').json['actors']),2)

    def test_independent_sort_field_and_direction(self):
        with db.connection(self.path) as c:
            for mid,title,budget,revenue,rating,votes in [(20,'Zebra',10_000_000,5_000_000,7.5,500),
                    (21,'alpha',20_000_000,8_000_000,8,200),(22,'Beta',30_000_000,9_000_000,9,100)]:
                title='Sort fixture '+title
                c.execute('INSERT INTO films(id,title) VALUES(?,?)',(mid,title))
                c.execute('''INSERT INTO film_values(movie_id,source,title,budget,revenue,vote_average,vote_count,signature)
                    VALUES(?,'tmdb',?,?,?,?,?,?)''',(mid,title,budget,revenue,rating,votes,str(mid)))
            ascending={'rating':[20,21,22],'title':[21,22,20],'budget':[20,21,22],'revenue':[20,21,22],
                'votes':[22,21,20],'revenue_minus_budget':[22,21,20],'shortfall':[20,21,22],
                'roi':[22,21,20],'gem_score':[20,21,22]}
            for page,fields in validation.SORT_FIELDS.items():
                for field in fields:
                    for direction in ('asc','desc'):
                        with self.subTest(page=page,field=field,direction=direction):
                            f=validation.query(dict(title='Sort fixture',source='tmdb',sort_by=field,sort_order=direction),page,c)
                            result=db.query_movies(c,page,f)
                            expected=ascending[field] if direction=='asc' else ascending[field][::-1]
                            self.assertEqual([r['id'] for r in result['rows']],expected)
                            self.assertEqual(result['total'],3)
            # Missing and ambiguous metrics remain last in either direction.
            for direction,expected in [('asc',[1,3,2,4]),('desc',[3,1,2,4])]:
                f=validation.query(dict(sort_by='rating',sort_order=direction),'index',c)
                result=db.query_movies(c,'index',f)
                self.assertEqual([r['id'] for r in result['rows'] if r['id']<20],expected)
            # Title sorting includes movies missing from the selected source.
            c.execute("INSERT INTO films VALUES(23,'Sort fixture Absent',0)")
            f=validation.query(dict(title='Sort fixture',source='tmdb',sort_by='title',sort_order='asc'),'index',c)
            self.assertEqual([r['id'] for r in db.query_movies(c,'index',f)['rows']],[23,21,22,20])
        for url in ['/?sort_by=rating&sort_order=asc','/hidden-gems?sort_by=rating&sort_order=asc',
                    '/bombs?sort_by=budget&sort_order=asc']:
            page=self.client.get(url)
            self.assertEqual(page.status_code,200)
            self.assertIn(b'<label for="sort_by">Sort by</label>',page.data)
            self.assertIn(b'<option value="asc" selected>Ascending</option>',page.data)
            self.assertNotIn(b'<option value="net_loss_desc"',page.data)
        for url in ['/?sort_by=not-a-column','/?sort_order=DROP%20TABLE%20films','/bombs?sort_by=gem_score',
                    '/hidden-gems?sort_order=up','/?sort_order=']:
            self.assertEqual(self.client.get(url).status_code,400)

    def test_sort_pagination_and_legacy_saved_queries(self):
        with db.connection(self.path) as c:
            for mid in range(100,155):
                c.execute("INSERT INTO films(id,title) VALUES(?,'Page fixture')",(mid,))
                c.execute('''INSERT INTO film_values(movie_id,source,title,vote_average,vote_count,signature)
                    VALUES(?,'tmdb','Page fixture',8,100,?)''',(mid,str(mid)))
            for direction in ('asc','desc'):
                pages=[]
                for page in (1,2):
                    f=validation.query(dict(title='Page fixture',source='tmdb',sort_by='rating',sort_order=direction,page=page),'index',c)
                    result=db.query_movies(c,'index',f)
                    self.assertEqual(result['total'],55)
                    pages.extend(r['id'] for r in result['rows'])
                self.assertEqual(pages,list(range(100,155)))
            for legacy,(field,direction) in validation.LEGACY_SORTS.items():
                page=next(p for p,fields in validation.SORT_FIELDS.items() if field in fields)
                f=validation.query({'sort_by':legacy},page,c)
                self.assertEqual((f['sort_by'],f['sort_order']),(field,direction))
            alice=c.execute("SELECT id FROM users WHERE username='alice'").fetchone()[0]
            qid=c.execute('''INSERT INTO saved_queries(user_id,name,page_type,spec,catalog_version)
                VALUES(?,'Legacy shortfall','bombs',?,?)''',(alice,json.dumps({'sort_by':'net_loss_desc'}),db.version(c))).lastrowid
        self.login('alice')
        reopened=self.client.get(f'/my-searches/{qid}/open',follow_redirects=True)
        self.assertEqual(reopened.status_code,200)
        self.assertIn(b'<option value="shortfall" selected>Production-budget shortfall</option>',reopened.data)
        self.assertIn(b'<option value="desc" selected>Descending</option>',reopened.data)
        response=self.post('/my-searches',{'name':'Ascending budget','page_type':'bombs',
            'spec':json.dumps({'sort_by':'budget','sort_order':'asc'})})
        self.assertEqual(response.status_code,302)
        with db.connection(self.path) as c:
            row=c.execute("SELECT id,spec FROM saved_queries WHERE name='Ascending budget'").fetchone()
            spec=json.loads(row['spec'])
            self.assertEqual((spec['sort_by'],spec['sort_order']),('budget','asc'))
            new_id=row['id']
        self.assertIn('sort_order=asc',self.client.get(f'/my-searches/{new_id}/open').location)
        for invalid in [{'sort_by':[]},{'sort_by':{}},{'sort_order':['asc']}]:
            self.assertEqual(self.post('/my-searches',{'name':'Invalid sort','page_type':'bombs','spec':json.dumps(invalid)}).status_code,400)

    def test_analytics_source_coherence(self):
        with db.connection(self.path) as c:
            f=validation.query({},'gems',c);r=db.query_movies(c,'gems',f)
            self.assertEqual(r['total'],db.stats(c,'movies')['gems'])
            self.assertEqual([x['id'] for x in r['rows']],[1])
            f=validation.query({'min_rating':'7.6','source':'movies'},'index',c)
            self.assertEqual(db.query_movies(c,'index',f)['total'],1) # Only movie 3; movie 2 ambiguous, movie 4 missing.
            f=validation.query({'min_rating':'7.6','source':'tmdb'},'index',c)
            self.assertEqual(db.query_movies(c,'index',f)['total'],4)
            bombs=db.query_movies(c,'bombs',validation.query({},'bombs',c))
            self.assertEqual(bombs['summary']['total_shortfall'],5000000)

    def dashboard_payload(self,response):
        marker='<script id="dashboard-data" type="application/json">'
        return json.loads(response.data.decode().split(marker,1)[1].split('</script>',1)[0])

    def test_dashboard_source_metrics_and_feature_flags(self):
        data=self.dashboard_payload(self.client.get('/'))
        self.assertEqual(data['defaults'],['movies','actors','gems','bombs'])
        metrics={m['id']:m for m in data['metrics']}
        self.assertEqual(metrics['movies']['value'],4)
        self.assertEqual(metrics['gems']['value'],1)
        self.assertEqual(metrics['average_rating']['value'],8.25)
        self.assertEqual(metrics['average_budget']['value'],10_000_000)
        self.assertEqual(metrics['total_revenue']['value'],5_000_000)
        tmdb=self.dashboard_payload(self.client.get('/?source=tmdb'))
        selected={m['id']:m for m in tmdb['metrics']}
        self.assertEqual(selected['average_rating']['value'],8.5)
        self.assertEqual(selected['average_budget']['value'],5_500_000)
        self.assertEqual(selected['total_revenue']['value'],7_000_000)
        self.assertIn('TMDB 5000',selected['average_rating']['scope'])
        self.assertIn('all sources',selected['movies']['scope'])
        empty=self.dashboard_payload(self.client.get('/?title=NotInFixture'))
        empty_metrics={m['id']:m for m in empty['metrics']}
        self.assertEqual(empty_metrics['matches']['display'],'0')
        self.assertEqual(empty_metrics['average_rating']['display'],'—')
        self.assertEqual(empty_metrics['shortfall']['display'],'$0')
        disabled=self.feature_app({'dashboard':False}).test_client()
        for path in ['/','/hidden-gems','/bombs']:
            self.assertNotIn(b'id="dashboard-data"',disabled.get(path).data)
        hidden=self.feature_app({'hidden_gems':False,'box_office':False}).test_client()
        flags_data=self.dashboard_payload(hidden.get('/'))
        available={m['id'] for m in flags_data['metrics']}
        self.assertTrue({'gems','bombs','shortfall'}.isdisjoint(available))
        self.assertTrue(set(flags_data['defaults'])<=available)

    def test_dashboard_totals_cover_all_result_pages(self):
        with db.connection(self.path) as c:
            for mid in range(100,155):
                c.execute("INSERT INTO films(id,title) VALUES(?,'Dashboard fixture')",(mid,))
                c.execute('''INSERT INTO film_values(movie_id,source,title,budget,revenue,vote_average,vote_count,signature)
                    VALUES(?,'tmdb','Dashboard fixture',20000000,10000000,8,100,?)''',(mid,str(mid)))
        for page in (1,2,3):
            data=self.dashboard_payload(self.client.get(f'/bombs?source=tmdb&page={page}'))
            self.assertEqual(data['defaults'],['matches','shortfall','avg_roi'])
            values={m['id']:m['value'] for m in data['metrics']}
            self.assertEqual(values['matches'],56)
            self.assertEqual(values['shortfall'],555_000_000)
            self.assertEqual(values['avg_roi'],-50)
        gems=self.dashboard_payload(self.client.get('/hidden-gems?source=tmdb'))
        self.assertEqual(gems['defaults'],['matches','average_rating','average_budget'])

    def test_compact_sources_and_cast_previews(self):
        with db.connection(self.path) as c:
            self.assertEqual([p['id'] for p in db.cast_preview(c,1,'movies')],[10,11])
            c.execute("UPDATE film_values SET vote_count=101 WHERE movie_id=3 AND source='tmdb'")
            c.execute('''INSERT INTO cast_suppressions SELECT movie_id,actor_id,role,source
                FROM cast_roles WHERE actor_id=10''')
            result=db.query_movies(c,'index',validation.query({'title':"Apostrophe"},'index',c))
            self.assertEqual([p['id'] for p in result['rows'][0]['cast_preview']],[11])
            self.assertEqual(result['rows'][0]['genres'][0]['name'],'Drama')
        listing=self.client.get('/?title=No+known+budget')
        self.assertIn(b'class="source-peek"',listing.data)
        self.assertNotIn(b'Values differ: vote count',listing.data)
        comparison=self.client.get('/source-differences?title=No+known+budget&field=vote_count')
        self.assertIn(b'Values differ: vote count',comparison.data)
        self.assertIn(b'101 votes',comparison.data)

    def test_saved_query_ownership_and_replay(self):
        self.login('alice')
        response=self.post('/my-searches',{'name':'My gems','page_type':'gems','spec':'{}','note':'Try these'})
        self.assertEqual(response.status_code,302)
        with db.connection(self.path) as c:q=c.execute('SELECT id FROM saved_queries').fetchone()[0]
        self.assertEqual(self.client.get(f'/my-searches/{q}/open').status_code,302)
        self.post(f'/my-searches/{q}',{'action':'update','spec':'{"max_budget":""}'})
        self.assertIn('max_budget=',self.client.get(f'/my-searches/{q}/open').location)
        self.assertEqual(self.post(f'/my-searches/{q}',{'action':'favorite'}).status_code,302)
        self.assertEqual(self.post(f'/my-searches/{q}',{'action':'update','spec':'{"min_rating":"NaN"}'}).status_code,400)
        self.login('bob')
        self.assertEqual(self.client.get(f'/my-searches/{q}/open').status_code,404)
        self.assertEqual(self.post(f'/my-searches/{q}',{'action':'delete'}).status_code,404)
        self.assertNotIn(b'My gems',self.client.get('/my-searches').data)

    def test_auth_csrf_permissions_and_passwords(self):
        self.assertEqual(self.client.post('/login',data={}).status_code,400)
        self.login('alice')
        self.assertEqual(self.client.get('/imports').status_code,403)
        self.assertEqual(self.post('/movie/1/delete').status_code,403)
        self.assertEqual(self.post('/register',{'username':'carol','display_name':'Carol','password':'a-long-password','is_admin':'1'}).status_code,302)
        with db.connection(self.path) as c:
            row=c.execute("SELECT * FROM users WHERE username='carol'").fetchone()
            self.assertEqual(row['is_admin'],0);self.assertTrue(check_password_hash(row['password_hash'],'a-long-password'))
        self.assertEqual(self.post('/password',{'current_password':'password-for-tests','password':'new-long-password'}).status_code,302)
        with self.client.session_transaction() as s:self.assertNotIn('uid',s)

    def test_override_and_new_local_ids(self):
        self.login()
        payload=dict(title='Local title',budget='123',revenue='456',vote_average='8.5',vote_count='100',source='movies')
        self.assertEqual(self.post('/movie/1/edit',payload).status_code,302)
        with db.connection(self.path) as c:
            r=c.execute('SELECT * FROM local_overrides').fetchone()
            self.assertEqual(r['vote_average'],8.5);self.assertEqual(r['vote_count'],100)
            self.assertEqual(c.execute("SELECT title FROM film_values WHERE movie_id=1 AND source='movies'").fetchone()[0],"Apostrophe's Movie")
        self.assertEqual(self.post('/movie/new',payload).status_code,302)
        self.assertEqual(self.post('/movie/1/cast/add',{'actor_mode':'new','actor_name':'Same Name','character_name':'New Role'}).status_code,302)
        with db.connection(self.path) as c:
            self.assertLess(c.execute('SELECT MIN(id) FROM films').fetchone()[0],0)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM people WHERE name='Same Name'").fetchone()[0],3)

    def test_graph_paths_limits_and_invalidation(self):
        result=self.client.get('/api/connections?start=10&end=12').json
        self.assertEqual(result['status'],'found');self.assertEqual(result['degrees'],2)
        self.assertEqual([x['entity_id'] for x in result['path']],[10,1,11,2,12])
        self.assertEqual(self.client.get('/api/connections?start=10&end=10').json['status'],'same_actor')
        with db.connection(self.path) as c:
            c.execute("INSERT INTO people VALUES(99,'Isolated')")
            db.bump_version(c)
        self.assertEqual(self.client.get('/api/connections?start=10&end=99').json['status'],'no_path')
        self.login();self.post('/movie/1/delete')
        self.assertEqual(self.client.get('/api/connections?start=10&end=12').json['status'],'no_path')
        self.assertEqual(graph.shortest({1:[1]},{1:[1,2]},1,2,seconds=-1)[0],'interrupted')
        a={i:[] for i in range(1,9)};m={i:[i,i+1] for i in range(1,8)}
        for mid,actors in m.items():
            for actor in actors:a[actor].append(mid)
        self.assertEqual(graph.shortest(a,m,1,7)[0],'found')
        self.assertEqual(graph.shortest(a,m,1,8)[0],'no_path')

    def test_rebuild_backup_and_failure_preserve_accounts(self):
        self.login('alice');self.post('/my-searches',{'name':'Saved','page_type':'index','spec':'{}'})
        with db.connection(self.path) as c:old=db.version(c)
        with self.assertRaises(ValueError):run_ingestion(self.root/'missing','both',db_path=self.path)
        with db.connection(self.path) as c:self.assertEqual(db.version(c),old)
        report=run_ingestion(self.root,'both',db_path=self.path)
        self.assertTrue(Path(report['backup']).exists())
        with db.connection(self.path) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM users').fetchone()[0],3)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM saved_queries').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM films').fetchone()[0],4)
        with db.connection(report['backup']) as c:self.assertEqual(db.version(c),old)
        stage=Path(self.temp_case.name)/'bad.db';stage_catalog(stage,'both',self.root)
        # A staging schema failure occurs after replacement starts; the transaction must roll back.
        with db.connection(stage) as c:c.execute('DROP TABLE cast_roles')
        with db.connection(self.path) as c:before=db.version(c)
        with self.assertRaises(sqlite3.Error):activate(stage,self.path)
        with db.connection(self.path) as c:
            self.assertEqual(db.version(c),before)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM films').fetchone()[0],4)

    def test_graph_render_limit_does_not_limit_shortest_path(self):
        with db.connection(self.path) as c:
            c.executemany('INSERT INTO people VALUES(?,?)',[(i,'Extra '+str(i)) for i in range(1000,1400)])
            c.executemany("INSERT INTO cast_roles VALUES(1,?,'Crowd','movies')",[(i,) for i in range(1000,1400)])
            db.bump_version(c)
        r=self.client.get('/api/neighborhood?start=10&end=12&depth=3').json
        self.assertEqual(r['degrees'],2);self.assertTrue(r['truncated'])
        self.assertLessEqual(len(r['nodes']),300);self.assertLessEqual(len(r['edges']),1000)
        self.assertTrue(all(item['id'] in {n['data']['id'] for n in r['nodes']} for item in r['path']))

    def test_incremental_node_expansion(self):
        r=self.client.get('/api/expand-node?node=actor:11').json
        self.assertEqual(r['node'],'actor:11');self.assertEqual(r['total'],2)
        self.assertEqual({n['data']['id'] for n in r['nodes']},{'actor:11','movie:1','movie:2'})
        self.assertEqual(len(r['edges']),2)
        r=self.client.get('/api/expand-node?node=movie:1&limit=1').json
        self.assertEqual(r['total'],2);self.assertTrue(r['has_more']);self.assertEqual(r['next_offset'],1)
        r2=self.client.get('/api/expand-node?node=movie:1&limit=1&offset=1').json
        self.assertFalse(r2['has_more'])
        self.assertNotEqual(r['edges'][0]['data']['source'],r2['edges'][0]['data']['source'])
        # All roles and source labels survive, without duplicating a movie/actor edge.
        r=self.client.get('/api/expand-node?node=movie:1&source=movies').json
        edge=next(e['data'] for e in r['edges'] if e['data']['source']=='actor:10')
        self.assertEqual({x['role'] for x in edge['details']},{'Hero','Narrator'})
        self.assertTrue(all(x['source']=='movies' for x in edge['details']))
        for args,code in [('node=wrong:1',400),('node=actor:abc',400),('node=actor:9999',404),
                          ('node=actor:10&offset=-1',400),('node=actor:10&limit=16',400),
                          ('node=actor:10&catalog_version=old',409)]:
            with self.subTest(args=args):self.assertEqual(self.client.get('/api/expand-node?'+args).status_code,code)
        self.login();self.post('/movie/1/delete')
        self.assertEqual(self.client.get('/api/expand-node?node=movie:1').status_code,404)
        self.assertEqual(self.client.get('/api/expand-node?node=actor:10').json['total'],0)

    def test_incremental_expansion_is_bounded_and_source_specific(self):
        with db.connection(self.path) as c:
            c.executemany('INSERT INTO people VALUES(?,?)',[(i,'Extra '+str(i)) for i in range(1000,1040)])
            c.executemany("INSERT INTO cast_roles VALUES(1,?,'Crowd','movies')",[(i,) for i in range(1000,1040)])
            db.bump_version(c)
        r=self.client.get('/api/expand-node?node=movie:1&source=movies').json
        self.assertEqual(len(r['nodes']),16);self.assertEqual(len(r['edges']),15)
        self.assertEqual(r['total'],42);self.assertTrue(r['has_more'])
        r=self.client.get('/api/expand-node?node=movie:1&source=tmdb').json
        self.assertEqual(r['total'],2)
        self.assertTrue(all('actor:1000'!=n['data']['id'] for n in r['nodes']))

    def test_local_role_suppression_and_restore(self):
        self.login()
        old=self.client.get('/api/connections?start=10&end=12').json['catalog_version']
        for source in ['movies','tmdb']:
            for role in ['Hero','Narrator']:
                response=self.post('/movie/1/cast/remove',{'actor_id':'10','role':role,'source':source})
                self.assertEqual(response.status_code,302)
        r=self.client.get('/api/connections?start=10&end=12').json
        self.assertEqual(r['status'],'no_path');self.assertNotEqual(r['catalog_version'],old)
        self.assertIn(b'0 matches',self.client.get('/?actor_id=10&character=Hero').data)
        with db.connection(self.path) as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM cast_roles WHERE actor_id=10').fetchone()[0],4)
        self.post('/movie/1/cast/remove',{'actor_id':'10','role':'Hero','source':'movies','restore':'1'})
        self.assertEqual(self.client.get('/api/connections?start=10&end=12').json['status'],'found')

    def test_login_throttle_and_saved_filter_update(self):
        for _ in range(5):
            self.assertEqual(self.post('/login',{'username':'alice','password':'bad'}).status_code,400)
        self.assertEqual(self.post('/login',{'username':'alice','password':'bad'}).status_code,429)
        self.login('bob')
        self.post('/my-searches',{'name':'One','page_type':'index','spec':'{}'})
        with db.connection(self.path) as c:q=c.execute('SELECT id FROM saved_queries').fetchone()[0]
        self.assertEqual(self.post('/my-searches',{'name':'Updated','page_type':'index','existing_query_id':str(q),'spec':'{"min_rating":"8"}'}).status_code,302)
        with db.connection(self.path) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM saved_queries').fetchone()[0],1)
            self.assertEqual(json.loads(c.execute('SELECT spec FROM saved_queries').fetchone()[0])['min_rating'],8)
        self.assertEqual(self.client.get('/?page=99999999999999999999').status_code,400)
        self.assertEqual(self.client.get('/movie/9999999999999999999999').status_code,404)

    def test_transactions_close_commit_and_rollback(self):
        with db.connection(self.path) as c:conn=c;c.execute("INSERT INTO people VALUES(50,'Closed')")
        with self.assertRaises(sqlite3.ProgrammingError):conn.execute('SELECT 1')
        with self.assertRaises(RuntimeError):
            with db.connection(self.path) as c:
                conn=c;c.execute("INSERT INTO people VALUES(51,'Rollback')");raise RuntimeError()
        with self.assertRaises(sqlite3.ProgrammingError):conn.execute('SELECT 1')
        with db.connection(self.path) as c:self.assertFalse(c.execute('SELECT 1 FROM people WHERE id=51').fetchone())

    def test_factory_does_not_initialize_database(self):
        path=Path(self.temp_case.name)/'nonexistent.db'
        app=create_app(dict(TESTING=True,DATABASE=str(path),SECRET_KEY='test'))
        self.assertFalse(path.exists());self.assertEqual(app.test_client().get('/').status_code,503)
        self.assertFalse(path.exists())

if __name__=='__main__':unittest.main()
