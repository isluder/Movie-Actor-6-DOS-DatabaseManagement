"""Explicit, validated imports. No network downloads or implicit sample fallback."""
import argparse
import ast
from collections import Counter
from datetime import datetime, timezone
import csv
import json
import math
from pathlib import Path
import tempfile
import uuid

try:
    from . import database as db
except ImportError:
    import database as db

DATA_DIR = db.BASE_DIR.parent / 'CSV-Files'
DATASETS = {'tmdb': ('TMDB 5000 Movie Dataset','tmdb_5000_movies.csv','tmdb_5000_credits.csv'),
            'movies': ('The Movies Dataset','movies_metadata.csv','credits.csv')}


def parse_json_or_literal(raw):
    if not raw or not raw.strip():return []
    try:value=json.loads(raw)
    except (ValueError,TypeError):value=ast.literal_eval(raw)
    if not isinstance(value,list) or any(not isinstance(x,dict) for x in value):
        raise ValueError('Expected a list of objects')
    return value


def number(value, integer=False, maximum=None):
    if value is None or str(value).strip() in ('','nan','NaN'):return None
    try:
        n=float(value)
        if not math.isfinite(n) or n<0 or (maximum is not None and n>maximum) or (integer and (not n.is_integer() or n>9223372036854775807)):
            return None
        return int(n) if integer else n
    except (TypeError,ValueError,OverflowError):return None


def identity(value):
    s=str(value or '').strip()
    if not s.isdecimal():raise ValueError('Invalid positive TMDB ID')
    n=int(s)
    if n<=0 or n>9223372036854775807:raise ValueError('Invalid positive TMDB ID')
    return n


def import_source(c,source,movies_path,credits_path,max_cast,report):
    expected=set(); actual_pairs=set(); expected_roles=set(); source_counts=Counter(); variants={}
    csv.field_size_limit(16*1024*1024)
    for kind,path in [('movies',movies_path),('credits',credits_path)]:
        with path.open(encoding='utf-8-sig',newline='') as stream:
            reader=csv.DictReader(stream)
            required={'id','title','budget','revenue','vote_average','vote_count','genres'} if kind=='movies' else {'cast', 'movie_id' if source=='tmdb' else 'id'}
            if not required.issubset(reader.fieldnames or []):raise ValueError(f'{path}: missing headers {sorted(required-set(reader.fieldnames or []))}')
            for row in reader:
                source_counts[kind+'_rows']+=1
                try:
                    mid=identity(row.get('id') if kind=='movies' or source!='tmdb' else row.get('movie_id'))
                except ValueError:
                    source_counts[kind+'_rejected']+=1;continue
                if kind=='movies':
                    title=(row.get('title') or row.get('original_title') or '').strip()
                    if not title:
                        source_counts['movies_rejected']+=1;continue
                    values={'title':title,'budget':number(row.get('budget'),True),'revenue':number(row.get('revenue'),True),
                            'vote_average':number(row.get('vote_average'),maximum=10),'vote_count':number(row.get('vote_count'),True)}
                    warnings=[key+' missing or invalid' for key,val in values.items() if val is None]
                    try:genres=parse_json_or_literal(row.get('genres',''))
                    except (ValueError,SyntaxError,TypeError):genres=[];warnings.append('Invalid genres')
                    source_counts['warning_rows']+=bool(warnings)
                    signature=json.dumps(values,sort_keys=True,ensure_ascii=False)
                    expected.add(mid);source_counts['movies_valid_rows']+=1
                    variants.setdefault(mid,set()).add(signature)
                    c.execute('INSERT OR IGNORE INTO films(id,title) VALUES(?,?)',(mid,title))
                    c.execute('''INSERT OR IGNORE INTO film_values(movie_id,source,title,budget,revenue,vote_average,vote_count,signature)
                        VALUES(?,?,?,?,?,?,?,?)''',(mid,source,*values.values(),signature))
                    for g in genres:
                        try:gid=identity(g.get('id'));name=str(g.get('name') or '').strip();assert name
                        except (ValueError,AssertionError):continue
                        c.execute('INSERT OR IGNORE INTO catalog_genres VALUES(?,?)',(gid,name))
                        c.execute('INSERT OR IGNORE INTO film_genres VALUES(?,?,?)',(mid,gid,source))
                else:
                    if mid not in expected:
                        source_counts['credits_rejected']+=1;continue
                    try:cast=parse_json_or_literal(row.get('cast',''))
                    except (ValueError,SyntaxError,TypeError):
                        source_counts['credits_rejected']+=1;continue
                    warnings=[]
                    if not cast:source_counts['empty_cast_rows']+=1
                    for index,a in enumerate(cast):
                        try:aid=identity(a.get('id'));name=str(a.get('name') or '').strip();assert name
                        except (ValueError,AssertionError):warnings.append(f'Invalid actor at index {index}');continue
                        role=str(a.get('character') or 'Unknown role').strip() or 'Unknown role'
                        expected_roles.add((mid,aid,role))
                        if max_cast is not None and index>=max_cast:continue
                        c.execute('INSERT OR IGNORE INTO people VALUES(?,?)',(aid,name))
                        c.execute('INSERT OR IGNORE INTO cast_roles VALUES(?,?,?,?,?)',(mid,aid,role,source,index))
                        actual_pairs.add((mid,aid))
                    source_counts['warning_rows']+=bool(warnings)
    actual={r[0] for r in c.execute('SELECT DISTINCT movie_id FROM film_values WHERE source=?',(source,))}
    if actual!=expected:raise ValueError('Movie ID coverage mismatch: '+source)
    imported_roles={tuple(r) for r in c.execute('SELECT movie_id,actor_id,role FROM cast_roles WHERE source=?',(source,))}
    if max_cast is None and imported_roles!=expected_roles:raise ValueError('Role coverage mismatch: '+source)
    source_counts.update(unique_movie_ids=len(expected),duplicate_rows=source_counts['movies_valid_rows']-len(expected),
                         ambiguous_movie_ids=sum(len(v)>1 for v in variants.values()),source_roles=len(expected_roles),
                         imported_roles=len(imported_roles),missing_roles=len(expected_roles-imported_roles),
                         source_cast_pairs=len({(m,a) for m,a,_ in expected_roles}),imported_cast_pairs=len(actual_pairs))
    source_counts['movies_without_imported_cast']=len(expected-{m for m,a in actual_pairs})
    report['sources'][source]=dict(source_counts)
    return expected


def stage_catalog(path, selection='both', data_dir=DATA_DIR, max_cast=None):
    if selection not in ('both','tmdb','movies','demo'):raise ValueError('Unknown dataset selection')
    if max_cast is not None and max_cast<1:raise ValueError('Cast cap must be positive')
    selected=['movies','tmdb'] if selection=='both' else [selection]
    paths={}
    if selection!='demo':
        for source in selected:
            folder,movie,credit=DATASETS[source];paths[source]=(Path(data_dir)/folder/movie,Path(data_dir)/folder/credit)
            for p in paths[source]:
                if not p.is_file():raise ValueError('Required CSV missing: '+str(p))
    db.init_db(path)
    run_id=uuid.uuid4().hex
    report={'version':run_id,'selection':selection,'cast_complete':max_cast is None,'cast_cap':max_cast,'sources':{}}
    with db.connection(path) as c:
        sets=[]
        if selection=='demo':
            fixture=json.loads((db.BASE_DIR/'sample_data.json').read_text())
            with tempfile.TemporaryDirectory() as temp:
                mp=Path(temp)/'movies.csv';cp=Path(temp)/'credits.csv'
                genres=dict(fixture['catalog_genres'])
                with mp.open('w',newline='') as mf,cp.open('w',newline='') as cf:
                    mw=csv.DictWriter(mf,fieldnames=['id','title','budget','revenue','vote_average','vote_count','genres']);mw.writeheader()
                    cw=csv.DictWriter(cf,fieldnames=['id','cast']);cw.writeheader()
                    for mid,title,budget,revenue,rating,votes,gids,cast in fixture['sample_movies']:
                        mw.writerow(dict(id=mid,title=title,budget=budget,revenue=revenue,vote_average=rating,vote_count=votes,genres=json.dumps([dict(id=g,name=genres[g]) for g in gids])))
                        cw.writerow(dict(id=mid,cast=json.dumps([dict(id=a,name=n,character=r) for a,n,r in cast])))
                sets.append(import_source(c,'demo',mp,cp,max_cast,report))
        else:
            for source in selected:
                print(f'Importing {source} metadata and complete credits…',flush=True)
                sets.append(import_source(c,source,*paths[source],max_cast,report))
        expected=set.union(*sets)
        actual={r[0] for r in c.execute('SELECT id FROM films')}
        if actual!=expected:raise ValueError('Combined catalog ID coverage failed')
        if c.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('Foreign key check failed')
        report['movies']=len(actual)
        report['overlap']=len(set.intersection(*sets)) if len(sets)>1 else 0
        report['actors']=c.execute('SELECT COUNT(*) FROM people').fetchone()[0]
        report['cast_pairs']=c.execute('SELECT COUNT(*) FROM (SELECT DISTINCT movie_id,actor_id FROM cast_roles)').fetchone()[0]
        report['roles']=c.execute('SELECT COUNT(*) FROM cast_roles').fetchone()[0]
        report['genre_links']=c.execute('SELECT COUNT(*) FROM film_genres').fetchone()[0]
        c.executemany('INSERT INTO catalog_meta VALUES(?,?)',[('version',run_id),('report',json.dumps(report)),('schema_version',db.SCHEMA_VERSION)])
    with db.connection(path) as c:
        if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Integrity check failed')
    return report


def activate(stage, target):
    """Back up the old database and replace its schema/data in one transaction."""
    target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    backup_dir=target.parent/'backups';backup_dir.mkdir(exist_ok=True)
    backup=backup_dir/(target.stem+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.db')
    # Child tables come first so old schemas with foreign keys can also migrate.
    obsolete = ['saved_queries','login_attempts','users','cast_suppressions','edit_history',
                'local_overrides','film_genres','cast_roles','actor_names','film_values',
                'source_records','source_files','catalog_genres','people','films',
                'import_runs','catalog_meta','Movie_Cast','Genres','Genre_Types','Actors','Movies']
    with db.connection(target) as c:
        c.execute('ATTACH DATABASE ? AS staged',(str(stage),))
        c.execute('BEGIN IMMEDIATE')
        with db.connection(target) as origin,db.connection(backup) as destination:
            origin.backup(destination)
        c.execute('DROP VIEW IF EXISTS main.source_metrics')
        for table in obsolete:c.execute('DROP TABLE IF EXISTS main.'+table)
        # executescript commits implicitly: execute statements separately to keep
        # both the schema migration and all inserts inside the rollback boundary.
        for statement in (db.BASE_DIR/'schema.sql').read_text().split(';'):
            if statement.strip():c.execute(statement)
        for table in reversed(db.CATALOG_TABLES):
            c.execute('INSERT INTO main.'+table+' SELECT * FROM staged.'+table)
        if c.execute('PRAGMA main.foreign_key_check').fetchone():raise ValueError('Activated catalog failed foreign key validation')
    return str(backup)


def run_ingestion(data_dir=DATA_DIR,selection='both',max_cast=None,db_path=db.DB_PATH,dry_run=False):
    with tempfile.TemporaryDirectory(prefix='movie-import-') as temp:
        stage=Path(temp)/'stage.db'
        report=stage_catalog(stage,selection,data_dir,max_cast)
        if not dry_run:report['backup']=activate(stage,db_path)
        return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['validate','rebuild'])
    parser.add_argument('--dataset',choices=['both','tmdb','movies','demo'],default='both')
    parser.add_argument('--data-dir',type=Path,default=DATA_DIR)
    parser.add_argument('--db',default=db.DB_PATH)
    parser.add_argument('--max-cast',type=int)
    parser.add_argument('--confirm',action='store_true',help='Confirm the catalog will be backed up and replaced')
    args=parser.parse_args()
    if args.command=='rebuild' and not args.confirm:parser.error('Rebuild replaces the catalog; supply --confirm')
    try:print(json.dumps(run_ingestion(args.data_dir,args.dataset,args.max_cast,args.db,args.command=='validate'),indent=2))
    except (ValueError,OSError) as e:parser.exit(1,str(e)+'\n')
