PRAGMA foreign_keys = ON;

-- Movie and actor identities use TMDB IDs shared by both datasets.
CREATE TABLE IF NOT EXISTS films (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);

-- Keep source values separate so differences can be inspected without merging.
-- NULL means missing/invalid. Imported zeros are preserved as supplied.
-- A signature collapses exact duplicates, while retaining conflicting variants.
CREATE TABLE IF NOT EXISTS film_values (
    id INTEGER PRIMARY KEY,
    movie_id INTEGER NOT NULL REFERENCES films(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    budget INTEGER CHECK (budget >= 0),
    revenue INTEGER CHECK (revenue >= 0),
    vote_average REAL CHECK (vote_average BETWEEN 0 AND 10),
    vote_count INTEGER CHECK (vote_count >= 0),
    signature TEXT NOT NULL,
    UNIQUE (movie_id, source, signature)
);

-- An actor can play several characters in one film, in either source.
CREATE TABLE IF NOT EXISTS cast_roles (
    movie_id INTEGER NOT NULL REFERENCES films(id) ON DELETE CASCADE,
    actor_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    source TEXT NOT NULL,
    credit_order INTEGER NOT NULL DEFAULT 0 CHECK (credit_order >= 0),
    PRIMARY KEY (movie_id, actor_id, role, source)
);

CREATE TABLE IF NOT EXISTS catalog_genres (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS film_genres (
    movie_id INTEGER NOT NULL REFERENCES films(id) ON DELETE CASCADE,
    genre_id INTEGER NOT NULL REFERENCES catalog_genres(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    PRIMARY KEY (movie_id, genre_id, source)
);

-- Current catalog version and one import summary, used for graph cache updates.
CREATE TABLE IF NOT EXISTS catalog_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS cast_by_actor ON cast_roles(actor_id, movie_id, source);
CREATE INDEX IF NOT EXISTS cast_by_movie ON cast_roles(movie_id, source, actor_id);
CREATE INDEX IF NOT EXISTS values_by_source ON film_values(source, movie_id);
CREATE INDEX IF NOT EXISTS genres_by_genre ON film_genres(genre_id, movie_id);
CREATE INDEX IF NOT EXISTS people_by_name ON people(name COLLATE NOCASE);
