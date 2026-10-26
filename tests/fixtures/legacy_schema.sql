PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS catalog_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS import_runs(id TEXT PRIMARY KEY, imported_at TEXT NOT NULL, selection TEXT NOT NULL, report TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS source_files(id INTEGER PRIMARY KEY,source TEXT NOT NULL,kind TEXT NOT NULL,path TEXT NOT NULL,sha256 TEXT NOT NULL,run_id TEXT NOT NULL REFERENCES import_runs(id));
CREATE TABLE IF NOT EXISTS films(id INTEGER PRIMARY KEY,title TEXT NOT NULL,hidden INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS people(id INTEGER PRIMARY KEY,name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS source_records(id INTEGER PRIMARY KEY,file_id INTEGER NOT NULL REFERENCES source_files(id),row_number INTEGER NOT NULL,movie_id INTEGER,raw TEXT NOT NULL,parsed TEXT,status TEXT NOT NULL,reason TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS film_values(id INTEGER PRIMARY KEY,movie_id INTEGER NOT NULL REFERENCES films(id),source TEXT NOT NULL,title TEXT NOT NULL,budget INTEGER,revenue INTEGER,vote_average REAL,vote_count INTEGER,signature TEXT NOT NULL,record_id INTEGER REFERENCES source_records(id),UNIQUE(movie_id,source,signature));
CREATE TABLE IF NOT EXISTS actor_names(actor_id INTEGER NOT NULL REFERENCES people(id),source TEXT NOT NULL,name TEXT NOT NULL,PRIMARY KEY(actor_id,source,name));
CREATE TABLE IF NOT EXISTS cast_roles(movie_id INTEGER NOT NULL REFERENCES films(id),actor_id INTEGER NOT NULL REFERENCES people(id),role TEXT NOT NULL,source TEXT NOT NULL,PRIMARY KEY(movie_id,actor_id,role,source));
CREATE TABLE IF NOT EXISTS catalog_genres(id INTEGER PRIMARY KEY,name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS film_genres(movie_id INTEGER NOT NULL REFERENCES films(id),genre_id INTEGER NOT NULL REFERENCES catalog_genres(id),source TEXT NOT NULL,PRIMARY KEY(movie_id,genre_id,source));
CREATE TABLE IF NOT EXISTS local_overrides(movie_id INTEGER NOT NULL REFERENCES films(id),source TEXT NOT NULL,title TEXT NOT NULL,budget INTEGER NOT NULL,revenue INTEGER NOT NULL,vote_average REAL NOT NULL,vote_count INTEGER NOT NULL,PRIMARY KEY(movie_id,source));
CREATE TABLE IF NOT EXISTS edit_history(id INTEGER PRIMARY KEY,movie_id INTEGER NOT NULL,user_id INTEGER NOT NULL,action TEXT NOT NULL,details TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT NOT NULL COLLATE NOCASE UNIQUE,display_name TEXT NOT NULL,password_hash TEXT NOT NULL,is_admin INTEGER NOT NULL DEFAULT 0,session_version INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS saved_queries(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),name TEXT NOT NULL,note TEXT NOT NULL DEFAULT '',page_type TEXT NOT NULL,spec TEXT NOT NULL,catalog_version TEXT NOT NULL,favorite INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS login_attempts(key TEXT PRIMARY KEY,failures INTEGER NOT NULL,last_attempt REAL NOT NULL);
CREATE INDEX IF NOT EXISTS cast_by_actor ON cast_roles(actor_id,movie_id,source);
CREATE INDEX IF NOT EXISTS cast_by_movie ON cast_roles(movie_id,source,actor_id);
CREATE INDEX IF NOT EXISTS values_by_source ON film_values(source,movie_id);
CREATE INDEX IF NOT EXISTS records_by_movie ON source_records(movie_id,file_id);
CREATE INDEX IF NOT EXISTS genres_by_genre ON film_genres(genre_id,movie_id);
CREATE INDEX IF NOT EXISTS people_by_name ON people(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS aliases_by_name ON actor_names(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS saves_by_user ON saved_queries(user_id,page_type);
CREATE VIEW IF NOT EXISTS source_metrics AS
 SELECT movie_id,source,MIN(title) title,MIN(budget) budget,MIN(revenue) revenue,
 MIN(vote_average) vote_average,MIN(vote_count) vote_count,COUNT(*) variants
 FROM film_values GROUP BY movie_id,source;
-- Local suppression preserves the immutable imported relationship and its provenance.
CREATE TABLE IF NOT EXISTS cast_suppressions(movie_id INTEGER NOT NULL REFERENCES films(id),actor_id INTEGER NOT NULL REFERENCES people(id),role TEXT NOT NULL,source TEXT NOT NULL,PRIMARY KEY(movie_id,actor_id,role,source));
