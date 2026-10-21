-- ============================================================================
-- Film Reel-ational Data - Relational Database Schema (SQLite)
-- ============================================================================
-- Note: Foreign key enforcement must be enabled per connection in SQLite:
-- PRAGMA foreign_keys = ON;

PRAGMA foreign_keys = ON;

-- 1. Movies Table
CREATE TABLE IF NOT EXISTS Movies (
    movie_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    budget INTEGER NOT NULL DEFAULT 0 CHECK (budget >= 0),
    revenue INTEGER NOT NULL DEFAULT 0 CHECK (revenue >= 0),
    vote_average REAL DEFAULT 0.0 CHECK (vote_average >= 0 AND vote_average <= 10),
    vote_count INTEGER DEFAULT 0 CHECK (vote_count >= 0)
);

-- 2. Actors Table
CREATE TABLE IF NOT EXISTS Actors (
    actor_id INTEGER PRIMARY KEY,
    actor_name TEXT NOT NULL
);

-- 3. Movie_Cast Table (Junction table linking Movies and Actors with character role)
CREATE TABLE IF NOT EXISTS Movie_Cast (
    movie_id INTEGER,
    actor_id INTEGER,
    character_name TEXT,
    PRIMARY KEY (movie_id, actor_id),
    FOREIGN KEY (movie_id) REFERENCES Movies(movie_id) ON DELETE CASCADE,
    FOREIGN KEY (actor_id) REFERENCES Actors(actor_id) ON DELETE CASCADE
);

-- 4. Genre_Types Lookup Table (Stores unique genre IDs and names for 3NF normalization)
CREATE TABLE IF NOT EXISTS Genre_Types (
    genre_id INTEGER PRIMARY KEY,
    genre_name TEXT NOT NULL UNIQUE
);

-- 5. Genres Table (Junction table linking Movies and Genre_Types)
CREATE TABLE IF NOT EXISTS Genres (
    movie_id INTEGER,
    genre_id INTEGER,
    PRIMARY KEY (movie_id, genre_id),
    FOREIGN KEY (movie_id) REFERENCES Movies(movie_id) ON DELETE CASCADE,
    FOREIGN KEY (genre_id) REFERENCES Genre_Types(genre_id) ON DELETE CASCADE
);

-- Indexes for fast multi-table searches and analytical queries
CREATE INDEX IF NOT EXISTS idx_movies_title ON Movies(title);
CREATE INDEX IF NOT EXISTS idx_movies_rating ON Movies(vote_average, vote_count);
CREATE INDEX IF NOT EXISTS idx_movies_box_office ON Movies(budget, revenue);
CREATE INDEX IF NOT EXISTS idx_actors_name ON Actors(actor_name);
CREATE INDEX IF NOT EXISTS idx_movie_cast_actor ON Movie_Cast(actor_id);
CREATE INDEX IF NOT EXISTS idx_genres_genre_id ON Genres(genre_id);
