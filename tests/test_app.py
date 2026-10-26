import csv
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from src import database as db, graph, validation, features
from src.app import create_app
from src.sql_search import EXAMPLES
from src.ingest_data import run_ingestion, stage_catalog, activate


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
    def tearDown(self):self.temp_case.cleanup()

    def test_home_and_new_feature_switches(self):
        home=self.client.get('/')
        self.assertIn(b'Every movie has a connection',home.data)
        for path in ['/movie-search','/similar-movies','/knowledge-graph','/hidden-gems','/bombs','/six-degrees']:
            self.assertIn(('href="'+path+'"').encode(),home.data)
        disabled=self.feature_app({'similar_movies':False,'knowledge_graph':False}).test_client()
        for path in ['/similar-movies','/knowledge-graph']:
            self.assertEqual(disabled.get(path).status_code,404)
            self.assertNotIn(('href="'+path+'"').encode(),disabled.get('/').data)

    def test_similarity_index_and_ranking(self):
        from src import similarity
        self.assertFalse(similarity.index_path(self.path).exists())
        self.assertIn(b'index is not ready',self.client.get('/similar-movies').data)
        benchmark=similarity.benchmark(self.path,2)
        self.assertEqual(benchmark['movies'],4)
        self.assertFalse(similarity.index_path(self.path).exists())
        with db.connection(self.path) as c:
            docs=similarity.documents(c)
            first=next(d for d in docs if d['id']==1)
            self.assertEqual(len([t for t in first['tokens'] if t.startswith('actor:')]),2)
        self.assertEqual(similarity.build(self.path),4)
        with db.connection(self.path) as c:docs=similarity.load(self.path,db.version(c))
        chosen,related=similarity.recommend(docs,1)
        self.assertEqual(related[0]['id'],2)
        self.assertTrue(all(0<r['score']<=1 and r['id']!=1 for r in related))
        self.assertEqual(len(related),1)
        page=self.client.get('/similar-movies?movie_id=1')
        self.assertEqual(page.status_code,200)
        self.assertIn(b'Second',page.data)
        self.assertIn(b'Same Name',page.data)
        self.assertNotIn(b'index is not ready',page.data)
        self.assertIn(b'Choose your starting movie',self.client.get('/similar-movies?q=Apostrophe').data)
        for raw in ['abc','999','9'*30]:
            self.assertEqual(self.client.get('/similar-movies?movie_id='+raw).status_code,400)
        with db.connection(self.path) as c:db.bump_version(c)
        self.assertIn(b'index is not ready',self.client.get('/similar-movies?movie_id=1').data)
        self.assertEqual(similarity.build(self.path),4)
        self.assertNotIn(b'index is not ready',self.client.get('/similar-movies').data)

    def test_movie_cast_and_missing_cast_message(self):
        populated=self.client.get('/movie/1')
        self.assertIn(b'Same Name',populated.data)
        self.assertIn(b'Hero',populated.data)
        self.assertIn(b'The Movies Dataset</td>',populated.data)
        self.assertIn(b'TMDB 5000</td>',populated.data)
        self.assertNotIn(b'No cast or role records',populated.data)
        empty=self.client.get('/movie/3')
        self.assertIn(b'No cast or role records are available',empty.data)
        self.assertNotIn(b'<th>Actor</th>',empty.data)

    def test_catalog_graph_search_expansion_and_read_only(self):
        base='/api/knowledge-graph/'
        with db.connection(self.path) as c:before='\n'.join(c.iterdump())
        found=self.client.get(base+'search?kind=movie&q=Same+Name').json
        self.assertEqual({r['id'] for r in found['results']},{'movie:1','movie:2'})
        actors=self.client.get(base+'search?kind=actor&q=Same+Name&min_revenue=1000000').json
        self.assertEqual({r['id'] for r in actors['results']},{'actor:10','actor:11'})
        genres=self.client.get(base+'search?kind=genre&q=Drama').json
        self.assertEqual(genres['results'][0]['id'],'genre:18')
        data=self.client.get(base+'view?node=movie:1&expand=movie:1').json
        self.assertEqual({n['data']['id'] for n in data['nodes']},{'movie:1','actor:10','actor:11','genre:18'})
        self.assertEqual({e['data']['kind'] for e in data['edges']},{'cast','genre'})
        credit=next(e['data'] for e in data['edges'] if e['data']['id']=='cast:1:10')
        self.assertEqual({r['role'] for r in credit['details']},{'Hero','Narrator'})
        self.assertEqual({r['source'] for r in credit['details']},{'movies'})
        cast=self.client.get(base+'view?node=movie:1&expand=movie:1&edge=cast&role=Hero').json
        self.assertEqual({n['data']['id'] for n in cast['nodes']},{'movie:1','actor:10'})
        expanded=self.client.get(base+'view?node=actor:11&expand=actor:11&min_revenue=4000000').json
        self.assertEqual({n['data']['id'] for n in expanded['nodes']},{'actor:11','movie:1'})
        # Movie 2 has conflicting source variants, so it cannot qualify for a financial filter.
        ambiguous=self.client.get(base+'search?kind=movie&min_revenue=1').json
        self.assertNotIn('movie:2',{r['id'] for r in ambiguous['results']})
        genre=self.client.get(base+'view?node=genre:18&expand=genre:18&edge=genre').json
        self.assertEqual({n['data']['id'] for n in genre['nodes']},{'movie:1','genre:18'})
        changed=self.client.get(base+'view?node=movie:1&node=actor:10&min_budget=20000000').json
        self.assertNotIn('movie:1',{n['data']['id'] for n in changed['nodes']})
        with db.connection(self.path) as c:self.assertEqual(before,'\n'.join(c.iterdump()))
        self.assertEqual(self.client.post(base+'view').status_code,405)

    def test_catalog_graph_validation_and_limits(self):
        base='/api/knowledge-graph/'
        for args in ['kind=sql','source=bad','min_budget=-1','min_revenue=NaN','min_budget=9&max_budget=1','edge=unknown','genre_id=999','offset=-1']:
            self.assertEqual(self.client.get(base+'search?'+args).status_code,400,args)
        for args in ['node=films:1','node=movie:9999999999999999999999','expand=actor:999','node=movie:1;DROP']:
            self.assertEqual(self.client.get(base+'view?'+args).status_code,400,args)
        self.assertEqual(self.client.get(base+'view?catalog_version=old').status_code,409)
        self.assertEqual(self.client.get(base+'view',query_string=[('node','actor:10')]*301).status_code,400)
        disabled=self.feature_app({'knowledge_graph':False}).test_client()
        for path in ['search','view']:self.assertEqual(disabled.get(base+path).status_code,404)
        # Independent of Six Degrees and its visualization switch.
        enabled=self.feature_app({'six_degrees':False,'interactive_graph':False}).test_client()
        self.assertEqual(enabled.get(base+'view?expand=movie:1').status_code,200)
        with db.connection(self.path) as c:
            c.executemany('INSERT INTO people VALUES(?,?)',[(100+i,'Extra') for i in range(25)])
            c.executemany("INSERT INTO cast_roles VALUES(1,?,'Extra','movies',0)",[(100+i,) for i in range(25)])
        first=self.client.get(base+'view?node=movie:1&expand=movie:1&edge=cast').json
        self.assertEqual(len(first['nodes']),21)
        self.assertTrue(first['has_more'])
        query=[('node',n['data']['id']) for n in first['nodes']]+[('expand','movie:1'),('edge','cast')]
        second=self.client.get(base+'view',query_string=query).json
        self.assertEqual(len(second['nodes']),28)
        self.assertFalse(second['has_more'])

    def test_direct_script_startup_catalog_graph(self):
        import subprocess
        import sys
        script = """
import os, runpy, sys
from flask import Flask
from unittest.mock import patch
os.environ['MOVIE_CONFIG_FILE']=sys.argv[3]
sys.path.insert(0,str(__import__('pathlib').Path(sys.argv[1]).parent))
def check(app, *args, **kwargs):
    app.config.update(TESTING=True,DATABASE=sys.argv[2])
    client=app.test_client()
    for url in ['/api/knowledge-graph/search?kind=genre&q=Drama',
                '/api/knowledge-graph/suggestions?kind=actor&q=Same',
                '/api/knowledge-graph/view?node=movie:1&expand=movie:1']:
        response=client.get(url)
        assert response.status_code==200, (url,response.status_code)
        assert response.is_json
with patch.object(Flask,'run',check):
    runpy.run_path(sys.argv[1],run_name='__main__')
"""
        result=subprocess.run([sys.executable,'-c',script,str(Path('src/app.py').resolve()),str(self.path),str(self.feature_config)],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_catalog_graph_suggestions(self):
        base='/api/knowledge-graph/suggestions'
        with db.connection(self.path) as c:before='\n'.join(c.iterdump())
        suggestions=self.client.get(base+'?kind=movie&q=Same').json['suggestions']
        self.assertIn({'kind':'actor','value':'Same Name'},suggestions)
        self.assertIn({'kind':'genre','value':'Drama'},self.client.get(base+'?kind=movie&q=Dra').json['suggestions'])
        self.assertIn({'kind':'movie','value':"Apostrophe's Movie"},self.client.get(base+'?kind=movie&q=Apo').json['suggestions'])
        self.assertIn({'kind':'role','value':'Hero'},self.client.get(base+'?field=role&role=He').json['suggestions'])
        self.assertEqual(self.client.get(base+'?kind=actor&q=Third&min_revenue=1').json['suggestions'],[])
        self.assertIn({'kind':'actor','value':'Third Actor'},self.client.get(base+'?kind=actor&q=Third&source=tmdb&min_revenue=1').json['suggestions'])
        self.assertEqual(self.client.get(base+'?q=A').json['suggestions'],[])
        self.assertEqual(self.client.get(base+'?field=unknown').status_code,400)
        self.assertEqual(self.feature_app({'knowledge_graph':False}).test_client().get(base+'?q=Same').status_code,404)
        with db.connection(self.path) as c:self.assertEqual(before,'\n'.join(c.iterdump()))

    def test_all_pages_and_related_apis_can_be_disabled_in_yaml(self):
        routes={
            'home':['/'], 'movie_details':['/movie/1'], 'setup':['/setup'],
            'movie_search':['/movie-search'], 'hidden_gems':['/hidden-gems'],
            'box_office':['/bombs'], 'source_differences':['/source-differences'],
            'six_degrees':['/six-degrees','/api/connections','/api/actor-statistics'],
            'interactive_graph':['/api/neighborhood','/api/expand-node'],
            'similar_movies':['/similar-movies'], 'sql_search':['/sql-search'],
            'manual_entry':['/manual-entry'], 'knowledge_graph':['/knowledge-graph',
                '/api/knowledge-graph/search','/api/knowledge-graph/view','/api/knowledge-graph/suggestions'],
        }
        config=Path(self.temp_case.name)/'all-page-switches.yaml'
        for key,paths in routes.items():
            config.write_text('application_features:\n  '+features.LABELS[key]+': Disable\n')
            client=self.feature_app(config_file=config).test_client()
            for path in paths:
                with self.subTest(feature=key,path=path):
                    response=client.get(path)
                    if path=='/':
                        self.assertEqual(response.location,'/movie-search')
                        self.assertEqual(client.get(response.location).status_code,200)
                    else:self.assertEqual(response.status_code,404)
                    if path.startswith('/api/'):self.assertTrue(response.is_json)
            if key in ('manual_entry','sql_search'):
                self.assertEqual(client.post(paths[0]).status_code,404)
            landing=client.get('/',follow_redirects=True)
            for path in paths:
                if path not in ('/',) and not path.startswith('/api/'):
                    self.assertNotIn(('href="'+path+'"').encode(),landing.data)
        # Every application endpoint must have a switch or an explicit shared policy.
        covered=set(features.ENDPOINT_FEATURES)|{'static','actors_api'}
        self.assertTrue({rule.endpoint for rule in self.app.url_map.iter_rules()}<=covered)
        config.write_text('application_features:\n'+''.join('  '+label+': Disable\n' for label in features.LABELS.values()))
        off=self.feature_app(config_file=config).test_client()
        for path in [path for paths in routes.values() for path in paths]+['/api/actors']:
            self.assertEqual(off.get(path).status_code,404,path)
        with off.get('/static/style.css') as response:self.assertEqual(response.status_code,200)
        # A utility page can be the only enabled destination, without redirect loops.
        for key,path in [('knowledge_graph','/knowledge-graph'),('sql_search','/sql-search'),('manual_entry','/manual-entry')]:
            flags={key:False for key in features.LABELS};flags[key]=True
            client=self.feature_app(flags).test_client()
            response=client.get('/')
            self.assertEqual(response.location,path)
            self.assertEqual(client.get(path).status_code,200)

    def test_disabled_details_and_setup_have_no_indirect_links(self):
        from src import similarity
        similarity.build(self.path)
        app=self.feature_app({'movie_details':False,'setup':False})
        client=app.test_client()
        for path in ['/movie-search','/hidden-gems','/bombs','/source-differences','/similar-movies?movie_id=1','/six-degrees?start=10&end=12']:
            response=client.get(path)
            self.assertEqual(response.status_code,200)
            self.assertNotIn(b'href="/movie/',response.data)
            self.assertIn(b'data-movie-details="disabled"',response.data)
        client.get('/manual-entry')
        with client.session_transaction() as session:token=session['csrf']
        saved=client.post('/manual-entry',data={'csrf_token':token,'title':'No details redirect'})
        self.assertEqual(saved.location,'/manual-entry')
        self.assertIn(b'saved successfully',client.get(saved.location).data)
        app.config['DATABASE']=str(Path(self.temp_case.name)/'absent.db')
        response=client.get('/movie-search')
        self.assertEqual(response.status_code,503)
        self.assertNotIn(b'init-db',response.data)
        self.assertEqual(client.get('/setup').status_code,404)

    def test_degrees_to_builder_and_combined_sources(self):
        page=self.client.get('/six-degrees?start=10&end=12')
        self.assertIn(b'id="graph-explore-builder"',page.data)
        self.assertIn(b'target="_blank" rel="noopener"',page.data)
        disabled=self.feature_app({'knowledge_graph':False}).test_client()
        self.assertNotIn(b'id="graph-explore-builder"',disabled.get('/six-degrees?start=10&end=12').data)
        base='/api/knowledge-graph/'
        data=self.client.get(base+'view?source=both&node=movie:1&expand=movie:1').json
        self.assertEqual({n['data']['id'] for n in data['nodes']},{'movie:1','actor:10','actor:11','genre:18'})
        self.assertEqual(len({e['data']['id'] for e in data['edges']}),len(data['edges']))
        for edge in data['edges']:
            self.assertEqual({r['source'] for r in edge['data']['details']},{'movies','tmdb'})
        found=self.client.get(base+'search?source=both&kind=movie&q=TMDB+exclusive').json
        self.assertIn('movie:4',{r['id'] for r in found['results']})
        self.assertEqual(self.client.get(base+'search?source=both&min_budget=1').status_code,400)
        self.assertEqual(self.client.get(base+'suggestions?source=both&q=Same').status_code,200)
        self.assertEqual(self.client.get(base+'view?source=both&node=genre:18&expand=genre:18').status_code,200)

    def test_import_coverage_and_variants(self):
        with db.connection(self.path) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM films').fetchone()[0],4)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM film_values WHERE movie_id=2 AND source='movies'").fetchone()[0],2)
            self.assertEqual(json.loads(c.execute("SELECT value FROM catalog_meta WHERE key='report'").fetchone()[0])['sources']['movies']['movies_rejected'],1)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM cast_roles WHERE actor_id=10 AND movie_id=1 AND source='movies'").fetchone()[0],2)
            self.assertFalse(c.execute('PRAGMA foreign_key_check').fetchall())

    def test_pages_render_and_pagination(self):
        for url in ['/','/movie-search','/knowledge-graph','/similar-movies','/hidden-gems','/bombs','/source-differences','/source-differences?field=vote_average','/movie/1','/six-degrees','/six-degrees?start=10&end=12&depth=1']:
            with self.subTest(url=url):self.assertEqual(self.client.get(url).status_code,200)
        with db.connection(self.path) as c:
            c.executemany('INSERT INTO films(id,title) VALUES(?,?)',[(i,'Extra '+str(i)) for i in range(100,160)])
        response=self.client.get('/movie-search')
        self.assertIn(b'64 matches',response.data)
        self.assertIn(b'Next',response.data)

    def feature_app(self, flags=None, config_file=None):
        config=dict(TESTING=True,DATABASE=str(self.path),DATA_DIR=str(self.root),SECRET_KEY='test-secret',FEATURE_CONFIG=str(self.feature_config),FEATURES=flags or {})
        if config_file is not None:config['FEATURE_CONFIG']=config_file
        return create_app(config)

    def test_yaml_feature_configuration(self):
        config=Path(self.temp_case.name)/'features.yaml'
        config.write_text('application_features:\n  Movie Search: Disable\n')
        app=self.feature_app(config_file=config)
        client=app.test_client()
        self.assertEqual(client.get('/movie-search').status_code,404)
        self.assertEqual(client.get('/password').status_code,404)
        self.assertNotIn(b'>Movie Search</a>',client.get('/hidden-gems').data)
        self.assertIn(b'Bombed at the Box Office',client.get('/bombs').data)
        # A running process uses its startup snapshot until restarted.
        config.write_text('application_features:\n  Movie Search: Enable\n')
        self.assertEqual(client.get('/movie-search').status_code,404)
        self.assertEqual(self.feature_app(config_file=config).test_client().get('/').status_code,200)
        for text in ['application_features: [Movie Search]', 'application_features:\n  Movie Search: Maybe',
                     'application_features:\n  Movie Search: Enable\n  Movie Search: Disable',
                     'application_features:\n  Unknown Feature: Enable', 'other: {}', 'application_features: [']:
            config.write_text(text)
            with self.subTest(text=text),self.assertRaises(ValueError):self.feature_app(config_file=config)
        with self.assertRaises(ValueError):self.feature_app(config_file=config.with_name('missing.yaml'))


    def test_validation_and_same_cast_member(self):
        for val in ['abc','NaN','Infinity','-1','11']:
            self.assertEqual(self.client.get('/movie-search?min_rating='+val).status_code,400)
        self.assertEqual(self.client.get('/movie-search?min_rating=8&max_rating=7').status_code,400)
        self.assertEqual(self.client.get('/movie-search?min_budget=-1').status_code,400)
        self.assertEqual(self.client.get('/api/connections?start=10000&end=10').status_code,400)
        self.assertEqual(self.client.get('/movie-search?actor_id=10&character=Villain').status_code,200)
        self.assertIn(b'0 matches',self.client.get('/movie-search?actor_id=10&character=Villain').data)
        self.assertIn(b'1 matches',self.client.get('/movie-search?actor_id=10&character=Hero').data)
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
            c.execute("INSERT INTO films VALUES(23,'Sort fixture Absent')")
            f=validation.query(dict(title='Sort fixture',source='tmdb',sort_by='title',sort_order='asc'),'index',c)
            self.assertEqual([r['id'] for r in db.query_movies(c,'index',f)['rows']],[23,21,22,20])
        for url in ['/movie-search?sort_by=rating&sort_order=asc','/hidden-gems?sort_by=rating&sort_order=asc',
                    '/bombs?sort_by=budget&sort_order=asc']:
            page=self.client.get(url)
            self.assertEqual(page.status_code,200)
            self.assertIn(b'<label for="sort_by">Sort by</label>',page.data)
            self.assertIn(b'<option value="asc" selected>Ascending</option>',page.data)
            self.assertNotIn(b'<option value="net_loss_desc"',page.data)
        for url in ['/movie-search?sort_by=not-a-column','/movie-search?sort_order=DROP%20TABLE%20films','/bombs?sort_by=gem_score',
                    '/hidden-gems?sort_order=up','/movie-search?sort_order=']:
            self.assertEqual(self.client.get(url).status_code,400)

    def test_sort_pagination_and_legacy_urls(self):
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
        data=self.dashboard_payload(self.client.get('/movie-search'))
        self.assertEqual(data['defaults'],['movies','actors','gems','bombs'])
        metrics={m['id']:m for m in data['metrics']}
        self.assertEqual(metrics['movies']['value'],4)
        self.assertEqual(metrics['gems']['value'],1)
        self.assertEqual(metrics['average_rating']['value'],8.25)
        self.assertEqual(metrics['average_budget']['value'],10_000_000)
        self.assertEqual(metrics['total_revenue']['value'],5_000_000)
        tmdb=self.dashboard_payload(self.client.get('/movie-search?source=tmdb'))
        selected={m['id']:m for m in tmdb['metrics']}
        self.assertEqual(selected['average_rating']['value'],8.5)
        self.assertEqual(selected['average_budget']['value'],5_500_000)
        self.assertEqual(selected['total_revenue']['value'],7_000_000)
        self.assertIn('TMDB 5000',selected['average_rating']['scope'])
        self.assertIn('all sources',selected['movies']['scope'])
        empty=self.dashboard_payload(self.client.get('/movie-search?title=NotInFixture'))
        empty_metrics={m['id']:m for m in empty['metrics']}
        self.assertEqual(empty_metrics['matches']['display'],'0')
        self.assertEqual(empty_metrics['average_rating']['display'],'—')
        self.assertEqual(empty_metrics['shortfall']['display'],'$0')
        disabled=self.feature_app({'dashboard':False}).test_client()
        for path in ['/','/hidden-gems','/bombs']:
            self.assertNotIn(b'id="dashboard-data"',disabled.get(path).data)
        hidden=self.feature_app({'hidden_gems':False,'box_office':False}).test_client()
        flags_data=self.dashboard_payload(hidden.get('/movie-search'))
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
            result=db.query_movies(c,'index',validation.query({'title':"Apostrophe"},'index',c))
            self.assertEqual([p['id'] for p in result['rows'][0]['cast_preview']],[10,11])
            self.assertEqual(result['rows'][0]['genres'][0]['name'],'Drama')
        listing=self.client.get('/movie-search?title=No+known+budget')
        self.assertIn(b'class="source-peek"',listing.data)
        self.assertNotIn(b'Values differ: vote count',listing.data)
        comparison=self.client.get('/source-differences?title=No+known+budget&field=vote_count')
        self.assertIn(b'Values differ: vote count',comparison.data)
        self.assertIn(b'101 votes',comparison.data)


    def test_distance_statistics_exact_component_and_limits(self):
        # Chain reaches beyond six; movies are visited once even with cycles/duplicate roles.
        a={i:[] for i in range(1,10)};m={}
        for i in range(1,8):
            m[i]=[i,i+1];a[i].append(i);a[i+1].append(i)
        m[20]=[1,2];a[1].append(20);a[2].append(20)
        r=graph.distance_distribution(a,m,1,9)
        self.assertEqual(r['connected'],7)
        self.assertEqual(r['disconnected'],1)
        self.assertEqual(r['average'],4)
        self.assertEqual(r['maximum'],7)
        self.assertEqual(r['within_six'],6)
        self.assertEqual(r['beyond_six'],1)
        self.assertEqual(r['farthest_actor'],8)
        self.assertEqual(r['farthest_count'],1)
        self.assertEqual(r['farthest_path'][0],('actor',1))
        self.assertEqual(r['farthest_path'][-1],('actor',8))
        self.assertEqual(len(r['farthest_path']),15)
        tied=graph.distance_distribution({1:[1],2:[1],3:[1]},{1:[1,2,3]},1,3)
        self.assertEqual((tied['maximum'],tied['farthest_actor'],tied['farthest_count']),(1,2,2))
        self.assertEqual(sum(x['actors'] for x in r['distribution']),7)
        isolated=graph.distance_distribution(a,m,9,9)
        self.assertEqual((isolated['connected'],isolated['disconnected']),(0,8))
        self.assertIsNone(isolated['average']);self.assertIsNone(isolated['maximum'])
        interrupted=graph.distance_distribution(a,m,1,9,seconds=-1)
        self.assertEqual(interrupted['status'],'interrupted')
        for key in ('disconnected','average','connected'):self.assertIsNone(interrupted[key])

    def test_actor_statistics_endpoint_cache_sources_and_features(self):
        url='/api/actor-statistics?start=10'
        r=self.client.get(url)
        self.assertEqual(r.status_code,200)
        data=r.json
        self.assertEqual((data['connected'],data['disconnected'],data['average']),(2,0,1.5))
        self.assertEqual(data['distribution'],[dict(degrees=1,actors=1),dict(degrees=2,actors=1)])
        self.assertEqual(data['farthest_path'][-1]['label'],'Third Actor')
        self.assertEqual(len(data['farthest_path']),5)
        self.assertTrue(self.client.get(url).json['cached'])
        with db.connection(self.path) as c:
            c.execute("INSERT INTO people(id,name) VALUES(99,'Isolated')")
            c.execute("DELETE FROM cast_roles WHERE movie_id=2 AND actor_id=12 AND source='movies'")
            db.bump_version(c)
        revised=self.client.get(url+'&source=movies').json
        self.assertFalse(revised['cached'])
        self.assertEqual((revised['connected'],revised['disconnected']),(1,2))
        self.assertNotEqual(revised['catalog_version'],data['catalog_version'])
        self.assertEqual(self.client.get(url+'&source=tmdb').json['connected'],2)
        alone=self.client.get('/api/actor-statistics?start=99').json
        self.assertEqual((alone['connected'],alone['disconnected']),(0,3))
        self.assertIsNone(alone['average'])
        for args in ('','?start=NaN','?start=10000','?start=10&source=invalid'):
            self.assertEqual(self.client.get('/api/actor-statistics'+args).status_code,400)
        disabled=self.feature_app({'six_degrees':False}).test_client()
        self.assertEqual(disabled.get(url).status_code,404)
        no_cards=self.feature_app({'dashboard':False}).test_client().get('/six-degrees?start=10')
        self.assertNotIn(b'id="dashboard-data"',no_cards.data)
        self.assertIn(b'id="distance-chart"',no_cards.data)
        page=self.client.get('/six-degrees?start=10')
        self.assertEqual(self.dashboard_payload(page)['page'],'degrees')
        self.assertIn(b'distances.js',page.data)

    def test_difference_dashboard_full_set_and_vote_only(self):
        with db.connection(self.path) as c:
            for i in range(100,130):
                c.execute('INSERT INTO films(id,title) VALUES(?,?)',(i,'Vote only '+str(i)))
                for source,votes in [('movies',100),('tmdb',200)]:
                    c.execute('INSERT INTO film_values(movie_id,source,title,budget,revenue,vote_average,vote_count,signature) VALUES(?,?,?,?,?,?,?,?)',
                              (i,source,'Vote only '+str(i),1,2,8,votes,'test'))
        for page in (1,2):
            payload=self.dashboard_payload(self.client.get('/source-differences?page='+str(page)))
            metrics={m['id']:m['value'] for m in payload['metrics']}
            self.assertEqual((metrics['matches'],metrics['substantive'],metrics['votes_only']),(32,2,30))
            self.assertEqual(metrics['vote_average'],2)
        filtered=self.dashboard_payload(self.client.get('/source-differences?field=vote_average'))
        self.assertEqual({m['id']:m['value'] for m in filtered['metrics']}['votes_only'],0)
        empty=self.dashboard_payload(self.client.get('/source-differences?title=NotInFixture'))
        self.assertTrue(all(m['value']==0 for m in empty['metrics']))
        disabled=self.feature_app({'dashboard':False}).test_client()
        self.assertNotIn(b'id="dashboard-data"',disabled.get('/source-differences').data)

    def test_graph_paths_limits_and_invalidation(self):
        result=self.client.get('/api/connections?start=10&end=12').json
        self.assertEqual(result['status'],'found');self.assertEqual(result['degrees'],2)
        self.assertEqual([x['entity_id'] for x in result['path']],[10,1,11,2,12])
        self.assertEqual(self.client.get('/api/connections?start=10&end=10').json['status'],'same_actor')
        with db.connection(self.path) as c:
            c.execute("INSERT INTO people VALUES(99,'Isolated')")
            db.bump_version(c)
        self.assertEqual(self.client.get('/api/connections?start=10&end=99').json['status'],'no_path')
        with db.connection(self.path) as c:
            c.execute('DELETE FROM films WHERE id=1');db.bump_version(c)
        self.assertEqual(self.client.get('/api/connections?start=10&end=12').json['status'],'no_path')
        self.assertEqual(graph.shortest({1:[1]},{1:[1,2]},1,2,seconds=-1)[0],'interrupted')
        a={i:[] for i in range(1,9)};m={i:[i,i+1] for i in range(1,8)}
        for mid,actors in m.items():
            for actor in actors:a[actor].append(mid)
        self.assertEqual(graph.shortest(a,m,1,7)[0],'found')
        self.assertEqual(graph.shortest(a,m,1,8)[0],'no_path')

    def test_rebuild_backup_and_failure_rollback(self):
        with db.connection(self.path) as c:old=db.version(c)
        with self.assertRaises(ValueError):run_ingestion(self.root/'missing','both',db_path=self.path)
        with db.connection(self.path) as c:self.assertEqual(db.version(c),old)
        report=run_ingestion(self.root,'both',db_path=self.path)
        self.assertTrue(Path(report['backup']).exists())
        with db.connection(self.path) as c:
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
            c.executemany("INSERT INTO cast_roles(movie_id,actor_id,role,source) VALUES(1,?,'Crowd','movies')",[(i,) for i in range(1000,1400)])
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
        with db.connection(self.path) as c:
            c.execute('DELETE FROM films WHERE id=1');db.bump_version(c)
        self.assertEqual(self.client.get('/api/expand-node?node=movie:1').status_code,404)
        self.assertEqual(self.client.get('/api/expand-node?node=actor:10').json['total'],0)

    def test_incremental_expansion_is_bounded_and_source_specific(self):
        with db.connection(self.path) as c:
            c.executemany('INSERT INTO people VALUES(?,?)',[(i,'Extra '+str(i)) for i in range(1000,1040)])
            c.executemany("INSERT INTO cast_roles(movie_id,actor_id,role,source) VALUES(1,?,'Crowd','movies')",[(i,) for i in range(1000,1040)])
            db.bump_version(c)
        r=self.client.get('/api/expand-node?node=movie:1&source=movies').json
        self.assertEqual(len(r['nodes']),16);self.assertEqual(len(r['edges']),15)
        self.assertEqual(r['total'],42);self.assertTrue(r['has_more'])
        r=self.client.get('/api/expand-node?node=movie:1&source=tmdb').json
        self.assertEqual(r['total'],2)
        self.assertTrue(all('actor:1000'!=n['data']['id'] for n in r['nodes']))


    def test_transactions_close_commit_and_rollback(self):
        with db.connection(self.path) as c:conn=c;c.execute("INSERT INTO people VALUES(50,'Closed')")
        with self.assertRaises(sqlite3.ProgrammingError):conn.execute('SELECT 1')
        with self.assertRaises(RuntimeError):
            with db.connection(self.path) as c:
                conn=c;c.execute("INSERT INTO people VALUES(51,'Rollback')");raise RuntimeError()
        with self.assertRaises(sqlite3.ProgrammingError):conn.execute('SELECT 1')
        with db.connection(self.path) as c:self.assertFalse(c.execute('SELECT 1 FROM people WHERE id=51').fetchone())

    def test_removed_routes_and_minimal_schema(self):
        for url in ['/login','/register','/logout','/password','/my-searches','/my-searches/1/open',
                    '/my-searches/1','/imports','/movie/new','/movie/1/edit','/movie/1/delete',
                    '/movie/1/genres','/movie/1/cast/add','/movie/1/cast/remove','/source-record/1']:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code,404)
                self.assertEqual(self.client.post(url).status_code,404)
        with db.connection(self.path) as c:
            tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertEqual(tables,set(db.CATALOG_TABLES))
        for url in ['/','/movie/1','/six-degrees']:
            page=self.client.get(url)
            for label in [b'Log in',b'My Searches',b'Local override',b'Original rows and provenance',b'Admin actions']:
                self.assertNotIn(label,page.data)
        self.assertIn(b'Source Differences',self.client.get('/movie-search').data)

    def test_source_missing_values_and_constraints(self):
        with db.connection(self.path) as c:
            c.execute("UPDATE film_values SET revenue=NULL WHERE movie_id=3 AND source='tmdb'")
            c.execute("UPDATE film_values SET revenue=0 WHERE movie_id=3 AND source='movies'")
            f=validation.query({'title':'No known budget','field':'revenue'},'differences',c)
            self.assertEqual(db.difference_rows(c,f)['total'],1)
            for column,value in [('budget',-1),('revenue',-1),('vote_count',-1),('vote_average',11)]:
                with self.subTest(column=column),self.assertRaises(sqlite3.IntegrityError):
                    c.execute('UPDATE film_values SET '+column+'=? WHERE movie_id=3',(value,))

    def test_legacy_schema_migration_and_rollback(self):
        legacy=Path(self.temp_case.name)/'legacy.db'
        schema=(Path(__file__).parent/'fixtures'/'legacy_schema.sql').read_text()
        with db.connection(legacy) as c:
            c.executescript(schema)
            c.execute("INSERT INTO catalog_meta VALUES('version','legacy-version')")
            c.execute("INSERT INTO films VALUES(999,'Old catalog',1)")
            c.execute("INSERT INTO people VALUES(100,'Old actor')")
            c.execute("INSERT INTO cast_roles VALUES(999,100,'Old role','movies')")
            c.execute("INSERT INTO users(id,username,display_name,password_hash) VALUES(1,'old','Old','unused')")
            c.execute("INSERT INTO saved_queries(user_id,name,page_type,spec,catalog_version) VALUES(1,'Old save','index','{}','old')")
            c.execute("INSERT INTO edit_history(movie_id,user_id,action,details) VALUES(999,1,'edit','{}')")
        old_client=create_app(dict(TESTING=True,DATABASE=str(legacy),FEATURE_CONFIG=str(self.feature_config))).test_client()
        self.assertEqual(old_client.get('/').status_code,503)
        with self.assertRaises(ValueError):db.init_db(legacy)
        # Failure after dropping old tables must restore both old schema and data.
        stage=Path(self.temp_case.name)/'broken-stage.db'
        stage_catalog(stage,'both',self.root)
        with db.connection(stage) as c:c.execute('DROP TABLE cast_roles')
        with self.assertRaises(sqlite3.Error):activate(stage,legacy)
        with db.connection(legacy) as c:
            self.assertEqual(db.version(c),'legacy-version')
            self.assertEqual(c.execute('SELECT hidden FROM films WHERE id=999').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM saved_queries').fetchone()[0],1)
        report=run_ingestion(self.root,'both',db_path=legacy)
        with db.connection(report['backup']) as c:
            self.assertEqual(db.version(c),'legacy-version')
            self.assertEqual(c.execute('SELECT COUNT(*) FROM users').fetchone()[0],1)
        with db.connection(legacy) as c:
            self.assertEqual({r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")},set(db.CATALOG_TABLES))
            self.assertEqual(c.execute('SELECT COUNT(*) FROM films').fetchone()[0],4)
            self.assertFalse(c.execute('PRAGMA foreign_key_check').fetchall())
        client=create_app(dict(TESTING=True,DATABASE=str(legacy),FEATURE_CONFIG=str(self.feature_config))).test_client()
        self.assertEqual(client.get('/source-differences').status_code,200)

    def manual_post(self, **fields):
        self.client.get('/manual-entry')
        with self.client.session_transaction() as session:token=session['csrf']
        return self.client.post('/manual-entry', data={'csrf_token':token, **fields})

    def test_utility_menu_and_feature_switches(self):
        client=self.feature_app({'source_differences':False}).test_client()
        page=client.get('/movie-search').data
        self.assertIn(b'id="site-menu"',page)
        self.assertIn(b'Navigation menu',page)
        self.assertIn(b'Source Differences <small>Disabled</small>',page)
        self.assertNotIn(b'href="/source-differences"',page)
        for url in ['/sql-search','/manual-entry']:
            self.assertEqual(client.get(url).status_code,200)
        self.assertEqual(page.count(b'href="/sql-search"'),1)
        disabled=self.feature_app({'sql_search':False,'manual_entry':False}).test_client()
        for url in ['/sql-search','/manual-entry']:
            self.assertEqual(disabled.get(url).status_code,404)
            self.assertEqual(disabled.post(url).status_code,404)

    def test_sql_search_read_queries_and_rendering(self):
        for sql in [example['sql'] for example in EXAMPLES] + ['SELECT COUNT(*) AS movies FROM films',
                    'WITH selected AS (SELECT * FROM films) SELECT title FROM selected ORDER BY id',
                    'SELECT f.title,p.name FROM films f JOIN cast_roles cr ON cr.movie_id=f.id JOIN people p ON p.id=cr.actor_id',
                    "SELECT NULL AS a, '<script>alert(1)</script>' AS a"]:
            with self.subTest(sql=sql):
                response=self.client.post('/sql-search',data={'sql':sql})
                self.assertEqual(response.status_code,200)
                self.assertIn(b'Results',response.data)
        self.assertIn(b'&lt;script&gt;',response.data)
        self.assertNotIn(b'<script>alert(1)</script>',response.data)
        response=self.client.post('/sql-search',data={'sql':'WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<510) SELECT x FROM n'})
        self.assertIn(b'500 rows shown',response.data)
        self.assertIn(b'More rows available',response.data)
        self.assertEqual(self.client.post('/sql-search',data={'sql':'SELECT * FROM nonexistent'}).status_code,400)

    def test_sql_search_cannot_write_or_attach(self):
        with db.connection(self.path) as c:before=db.version(c)
        attached=Path(self.temp_case.name)/'forbidden.db'
        for sql in ["INSERT INTO films(id,title) VALUES(999,'Injected')", 'DELETE FROM films',
                    "UPDATE films SET title='Injected'", 'DROP TABLE films', 'CREATE TABLE injected(id)',
                    'PRAGMA user_version=999', 'PRAGMA query_only=OFF',
                    "ATTACH DATABASE '"+str(attached)+"' AS injected", 'BEGIN',
                    'SELECT 1; DELETE FROM films', "SELECT load_extension('anything')", 'EXPLAIN DELETE FROM films']:
            with self.subTest(sql=sql):
                self.assertEqual(self.client.post('/sql-search',data={'sql':sql}).status_code,400)
        self.assertFalse(attached.exists())
        with db.connection(self.path) as c:
            self.assertEqual(db.version(c),before)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM films').fetchone()[0],4)
            self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0],0)

    def test_sql_search_times_out(self):
        response=self.client.post('/sql-search',data={'sql':'WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n) SELECT SUM(x) FROM n'})
        self.assertEqual(response.status_code,400)
        self.assertIn(b'interrupted',response.data)

    def test_manual_entry_movie_cast_genres_and_graph(self):
        with db.connection(self.path) as c:before=db.version(c)
        response=self.manual_post(title="Manual's Movie",budget='100',revenue='200',vote_average='8.5',vote_count='100',
                                  actor_id=['10',''],actor_name=['','New Actor'],role=['Hero','Narrator'],genre_ids=['18'])
        self.assertEqual(response.status_code,303)
        with db.connection(self.path) as c:
            mid=c.execute("SELECT movie_id FROM film_values WHERE source='manual'").fetchone()[0]
            self.assertLess(mid,0)
            aid=c.execute("SELECT id FROM people WHERE name='New Actor'").fetchone()[0]
            self.assertLess(aid,0)
            self.assertNotEqual(db.version(c),before)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0],7)
            self.assertFalse(c.execute('PRAGMA foreign_key_check').fetchall())
        self.assertIn(b'Manual entries',self.client.get(response.location).data)
        self.assertIn(b'Manual&#39;s Movie',self.client.get('/movie-search?source=manual&min_rating=8').data)
        result=self.client.get(f'/api/connections?start=10&end={aid}&source=manual').json
        self.assertEqual((result['status'],result['degrees']),('found',1))
        self.assertIn(b"1 matches",self.client.get('/movie-search?source=manual&genre_id=18&min_rating=0').data)

    def test_manual_values_preserve_existing_sources(self):
        with db.connection(self.path) as c:original=[tuple(r) for r in c.execute('SELECT * FROM film_values WHERE movie_id=1')]
        response=self.manual_post(movie_id='1',title='My title',vote_average='9')
        self.assertEqual(response.status_code,303)
        with db.connection(self.path) as c:
            self.assertEqual([tuple(r) for r in c.execute("SELECT * FROM film_values WHERE movie_id=1 AND source!='manual'")],original)
            manual=dict(c.execute("SELECT * FROM film_values WHERE movie_id=1 AND source='manual'").fetchone())
            self.assertIsNone(manual['budget'])
            self.assertEqual(c.execute('SELECT title FROM films WHERE id=1').fetchone()[0],"Apostrophe's Movie")
        self.assertIn(b'My title',self.client.get('/source-differences').data)
        self.assertEqual(self.manual_post(movie_id='1',title='Duplicate').status_code,400)

    def test_manual_entry_rejects_invalid_data_without_partial_writes(self):
        with db.connection(self.path) as c:before=db.version(c)
        for fields in [dict(title=''),dict(title='Bad',budget='-1'),dict(title='Bad',vote_average='11'),
                       dict(title='Bad',vote_count='NaN'),dict(title='Bad',movie_id='999999'),
                       dict(title='Bad',genre_ids=['9999']),
                       dict(title='Bad',actor_id=['99999'],actor_name=[''],role=['Role']),
                       dict(title='Bad',actor_id=['10'],actor_name=['Both'],role=['Role'])]:
            with self.subTest(fields=fields):self.assertEqual(self.manual_post(**fields).status_code,400)
        self.assertEqual(self.client.post('/manual-entry',data={'title':'No token'}).status_code,400)
        self.assertEqual(self.client.post('/manual-entry',data={'csrf_token':'é','title':'Bad token'}).status_code,400)
        with db.connection(self.path) as c:
            self.assertEqual(db.version(c),before)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM films').fetchone()[0],4)
            self.assertFalse(c.execute("SELECT 1 FROM film_values WHERE source='manual'").fetchone())

    def test_factory_does_not_initialize_database(self):
        path=Path(self.temp_case.name)/'nonexistent.db'
        app=create_app(dict(TESTING=True,DATABASE=str(path),SECRET_KEY='test'))
        self.assertFalse(path.exists());self.assertEqual(app.test_client().get('/').status_code,503)
        self.assertFalse(path.exists())

if __name__=='__main__':unittest.main()
