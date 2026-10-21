"""
Data Ingestion & Local-to-Global Schema Mapping Script for Film Reel-ational Data.

Supports:
1. Kaggle 'TMDB 5000 Movies' (tmdb_5000_movies.csv + tmdb_5000_credits.csv)
2. Kaggle 'The Movies Dataset' (movies_metadata.csv + credits.csv)
3. Built-in Curated Real TMDB Sample Dataset (--sample or automatic fallback) so
   the application can be tested and demoed immediately without waiting on large CSVs.

Usage:
    python ingest_data.py                  # Auto-detects CSVs in ./data or seeds sample data
    python ingest_data.py --sample         # Resets and seeds curated real-movie sample dataset
    python ingest_data.py --data-dir ./data --max-cast 10
"""

import argparse
import ast
import csv
import json
import os
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from database import DB_PATH, get_connection, init_db

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def parse_json_or_literal(raw_value: str) -> List[Dict[str, Any]]:
    """
    Safely parse JSON or Python-literal list of dicts stored inside Kaggle CSV columns
    (e.g., genres and cast columns in movies_metadata.csv, credits.csv, tmdb_5000_*.csv).
    """
    if not raw_value or not raw_value.strip():
        return []
    try:
        parsed = json.loads(raw_value)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        try:
            parsed = ast.literal_eval(raw_value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []


def safe_int(val: Any, default: int = 0) -> int:
    try:
        return max(0, int(float(val)))
    except (ValueError, TypeError):
        return default


def safe_float(val: Any, default: float = 0.0) -> float:
    try:
        v = float(val)
        return min(10.0, max(0.0, v))
    except (ValueError, TypeError):
        return default


def ingest_tmdb_5000(
    movies_csv: str, credits_csv: Optional[str], max_cast: int = 12, db_path: str = DB_PATH
) -> Dict[str, int]:
    """
    Ingest Kaggle 'TMDB 5000 Movies' dataset into the global SQLite schema.
    Local Schema:
      - tmdb_5000_movies.csv: id, title, original_title, budget, revenue, genres, vote_average, vote_count
      - tmdb_5000_credits.csv: movie_id, title, cast, crew
    """
    init_db(db_path)
    counts = {"movies": 0, "genres": 0, "actors": 0, "cast_links": 0}

    with get_connection(db_path) as conn:
        cur = conn.cursor()
        with open(movies_csv, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                movie_id = safe_int(row.get("id"), -1)
                title = (row.get("title") or row.get("original_title") or "").strip()
                if movie_id <= 0 or not title:
                    continue

                budget = safe_int(row.get("budget"), 0)
                revenue = safe_int(row.get("revenue"), 0)
                vote_average = safe_float(row.get("vote_average"), 0.0)
                vote_count = safe_int(row.get("vote_count"), 0)

                cur.execute(
                    """
                    INSERT OR REPLACE INTO Movies
                    (movie_id, title, budget, revenue, vote_average, vote_count)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (movie_id, title, budget, revenue, vote_average, vote_count),
                )
                counts["movies"] += 1

                for g in parse_json_or_literal(row.get("genres", "")):
                    gid = safe_int(g.get("id"), -1)
                    gname = (g.get("name") or "").strip()
                    if gid > 0 and gname:
                        cur.execute(
                            "INSERT OR IGNORE INTO Genre_Types (genre_id, genre_name) VALUES (?, ?)",
                            (gid, gname),
                        )
                        cur.execute(
                            "INSERT OR IGNORE INTO Genres (movie_id, genre_id) VALUES (?, ?)",
                            (movie_id, gid),
                        )
                        counts["genres"] += 1

        if credits_csv and os.path.exists(credits_csv):
            with open(credits_csv, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    movie_id = safe_int(row.get("movie_id") or row.get("id"), -1)
                    if movie_id <= 0:
                        continue
                    cast_list = parse_json_or_literal(row.get("cast", ""))
                    for member in cast_list[:max_cast]:
                        actor_id = safe_int(member.get("id"), -1)
                        actor_name = (member.get("name") or "").strip()
                        character_name = (member.get("character") or "Unknown Role").strip()
                        if actor_id > 0 and actor_name:
                            cur.execute(
                                "INSERT OR IGNORE INTO Actors (actor_id, actor_name) VALUES (?, ?)",
                                (actor_id, actor_name),
                            )
                            cur.execute(
                                """
                                INSERT OR REPLACE INTO Movie_Cast (movie_id, actor_id, character_name)
                                VALUES (?, ?, ?)
                                """,
                                (movie_id, actor_id, character_name),
                            )
                            counts["cast_links"] += 1

        conn.commit()
        counts["actors"] = conn.execute("SELECT COUNT(*) FROM Actors").fetchone()[0]
    return counts


def ingest_the_movies_dataset(
    metadata_csv: str, credits_csv: Optional[str], max_cast: int = 10, db_path: str = DB_PATH
) -> Dict[str, int]:
    """
    Ingest Kaggle 'The Movies Dataset' (movies_metadata.csv + credits.csv) into the global SQLite schema.
    """
    init_db(db_path)
    counts = {"movies": 0, "genres": 0, "actors": 0, "cast_links": 0}
    valid_movie_ids = set()

    with get_connection(db_path) as conn:
        cur = conn.cursor()
        with open(metadata_csv, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                movie_id = safe_int(row.get("id"), -1)
                title = (row.get("title") or row.get("original_title") or "").strip()
                if movie_id <= 0 or not title:
                    continue

                budget = safe_int(row.get("budget"), 0)
                revenue = safe_int(row.get("revenue"), 0)
                vote_average = safe_float(row.get("vote_average"), 0.0)
                vote_count = safe_int(row.get("vote_count"), 0)

                cur.execute(
                    """
                    INSERT OR REPLACE INTO Movies
                    (movie_id, title, budget, revenue, vote_average, vote_count)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (movie_id, title, budget, revenue, vote_average, vote_count),
                )
                valid_movie_ids.add(movie_id)
                counts["movies"] += 1

                for g in parse_json_or_literal(row.get("genres", "")):
                    gid = safe_int(g.get("id"), -1)
                    gname = (g.get("name") or "").strip()
                    if gid > 0 and gname:
                        cur.execute(
                            "INSERT OR IGNORE INTO Genre_Types (genre_id, genre_name) VALUES (?, ?)",
                            (gid, gname),
                        )
                        cur.execute(
                            "INSERT OR IGNORE INTO Genres (movie_id, genre_id) VALUES (?, ?)",
                            (movie_id, gid),
                        )
                        counts["genres"] += 1

        if credits_csv and os.path.exists(credits_csv):
            with open(credits_csv, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    movie_id = safe_int(row.get("id"), -1)
                    if movie_id not in valid_movie_ids:
                        continue
                    cast_list = parse_json_or_literal(row.get("cast", ""))
                    for member in cast_list[:max_cast]:
                        actor_id = safe_int(member.get("id"), -1)
                        actor_name = (member.get("name") or "").strip()
                        character_name = (member.get("character") or "Unknown Role").strip()
                        if actor_id > 0 and actor_name:
                            cur.execute(
                                "INSERT OR IGNORE INTO Actors (actor_id, actor_name) VALUES (?, ?)",
                                (actor_id, actor_name),
                            )
                            cur.execute(
                                """
                                INSERT OR REPLACE INTO Movie_Cast (movie_id, actor_id, character_name)
                                VALUES (?, ?, ?)
                                """,
                                (movie_id, actor_id, character_name),
                            )
                            counts["cast_links"] += 1

        conn.commit()
        counts["actors"] = conn.execute("SELECT COUNT(*) FROM Actors").fetchone()[0]
    return counts


def seed_sample_data(db_path: str = DB_PATH, reset: bool = True) -> Dict[str, int]:
    """
    Seed the database with real TMDB movie records covering:
    1. Iconic Blockbusters & Award Winners
    2. Famous Box Office Bombs (for the 'Bombed at the Box Office' feature)
    3. Critically Acclaimed Hidden Gems (for the 'Hidden Gems' feature)
    """
    if reset and os.path.exists(db_path):
        os.remove(db_path)
    init_db(db_path)

    genre_types = [
        (28, "Action"),
        (12, "Adventure"),
        (16, "Animation"),
        (35, "Comedy"),
        (80, "Crime"),
        (18, "Drama"),
        (10751, "Family"),
        (14, "Fantasy"),
        (36, "History"),
        (27, "Horror"),
        (10402, "Music"),
        (9648, "Mystery"),
        (10749, "Romance"),
        (878, "Science Fiction"),
        (53, "Thriller"),
        (37, "Western"),
    ]

    # Real TMDB movies: (movie_id, title, budget, revenue, vote_average, vote_count, genre_ids, [(actor_id, actor_name, character_name)])
    sample_movies = [
        # --- Major Blockbusters & Classics ---
        (
            19995, "Avatar", 237_000_000, 2_923_706_026, 7.6, 29850,
            [28, 12, 14, 878],
            [
                (65731, "Sam Worthington", "Jake Sully"),
                (8691, "Zoe Saldana", "Neytiri"),
                (10205, "Sigourney Weaver", "Dr. Grace Augustine"),
                (32747, "Stephen Lang", "Colonel Miles Quaritch"),
            ],
        ),
        (
            155, "The Dark Knight", 185_000_000, 1_004_558_444, 8.5, 31200,
            [28, 80, 18, 53],
            [
                (3894, "Christian Bale", "Bruce Wayne / Batman"),
                (1810, "Heath Ledger", "Joker"),
                (6383, "Aaron Eckhart", "Harvey Dent / Two-Face"),
                (3895, "Michael Caine", "Alfred Pennyworth"),
                (64, "Gary Oldman", "James Gordon"),
            ],
        ),
        (
            27205, "Inception", 160_000_000, 836_836_967, 8.4, 34900,
            [28, 12, 878],
            [
                (6193, "Leonardo DiCaprio", "Dom Cobb"),
                (24045, "Joseph Gordon-Levitt", "Arthur"),
                (27578, "Elliot Page", "Ariadne"),
                (2524, "Tom Hardy", "Eames"),
                (2037, "Cillian Murphy", "Robert Fischer"),
            ],
        ),
        (
            157336, "Interstellar", 165_000_000, 701_729_206, 8.4, 33100,
            [12, 18, 878],
            [
                (10297, "Matthew McConaughey", "Joseph Cooper"),
                (1813, "Anne Hathaway", "Dr. Amelia Brand"),
                (83002, "Jessica Chastain", "Murphy 'Murph' Cooper"),
                (3895, "Michael Caine", "Professor Brand"),
                (1892, "Matt Damon", "Dr. Mann"),
            ],
        ),
        (
            496243, "Parasite", 11_363_000, 257_591_776, 8.5, 17200,
            [35, 18, 53],
            [
                (20738, "Song Kang-ho", "Kim Ki-taek"),
                (115290, "Lee Sun-kyun", "Park Dong-ik"),
                (556435, "Cho Yeo-jeong", "Choi Yeon-교"),
                (1255881, "Choi Woo-shik", "Kim Ki-woo"),
            ],
        ),
        (
            545611, "Everything Everywhere All at Once", 25_000_000, 143_400_000, 7.8, 6100,
            [28, 12, 35, 878],
            [
                (1620, "Michelle Yeoh", "Evelyn Wang"),
                (690, "Ke Huy Quan", "Waymond Wang"),
                (1459219, "Stephanie Hsu", "Joy Wang / Jobu Tupaki"),
                (8944, "Jamie Lee Curtis", "Deirdre Beaubeirdre"),
            ],
        ),
        (
            244786, "Whiplash", 3_300_000, 49_000_000, 8.4, 14300,
            [18, 10402],
            [
                (996701, "Miles Teller", "Andrew Neiman"),
                (18999, "J.K. Simmons", "Terence Fletcher"),
                (539, "Paul Reiser", "Jim Neiman"),
            ],
        ),
        (
            872585, "Oppenheimer", 100_000_000, 957_000_000, 8.1, 8200,
            [18, 36],
            [
                (2037, "Cillian Murphy", "J. Robert Oppenheimer"),
                (5081, "Emily Blunt", "Kitty Oppenheimer"),
                (1892, "Matt Damon", "Leslie Groves"),
                (3223, "Robert Downey Jr.", "Lewis Strauss"),
            ],
        ),
        (
            693134, "Dune: Part Two", 190_000_000, 711_844_358, 8.3, 5400,
            [12, 878],
            [
                (1190668, "Timothée Chalamet", "Paul Atreides"),
                (505710, "Zendaya", "Chani"),
                (933238, "Rebecca Ferguson", "Lady Jessica"),
                (3810, "Javier Bardem", "Stilgar"),
            ],
        ),

        # --- Famous Box Office Bombs ("Bombed at the Box Office" Feature) ---
        (
            49529, "John Carter", 260_000_000, 284_139_100, 6.3, 5350,
            [28, 12, 878],
            [
                (60900, "Taylor Kitsch", "John Carter"),
                (21044, "Lynn Collins", "Dejah Thoris"),
                (5293, "Willem Dafoe", "Tars Tarkas"),
                (17288, "Mark Strong", "Matai Shang"),
            ],
        ),
        (
            57201, "The Lone Ranger", 255_000_000, 89_289_910, 6.1, 5780,
            [28, 12, 37],
            [
                (85, "Johnny Depp", "Tonto"),
                (53807, "Armie Hammer", "John Reid / The Lone Ranger"),
                (1283, "Helena Bonham Carter", "Red Harrington"),
                (2955, "William Fichtner", "Butch Cavendish"),
            ],
        ),
        (
            50321, "Mars Needs Moms", 150_000_000, 38_992_758, 5.7, 620,
            [12, 16, 10751, 878],
            [
                (13922, "Seth Green", "Milo (motion capture)"),
                (3234, "Joan Cusack", "Mom (voice)"),
                (59401, "Dan Fogler", "Gribble (voice)"),
            ],
        ),
        (
            1408, "Cutthroat Island", 98_000_000, 10_017_322, 5.8, 510,
            [28, 12],
            [
                (16935, "Geena Davis", "Morgan Adams"),
                (8654, "Matthew Modine", "William Shaw"),
                (8924, "Frank Langella", "Dawg Brown"),
            ],
        ),
        (
            64686, "47 Ronin", 175_000_000, 151_783_839, 6.2, 3650,
            [28, 12, 14],
            [
                (6384, "Keanu Reeves", "Kai"),
                (9195, "Hiroyuki Sanada", "Oishi"),
                (10738, "Tadanobu Asano", "Lord Kira"),
                (46364, "Rinko Kikuchi", "Witch"),
            ],
        ),
        (
            1911, "The 13th Warrior", 160_000_000, 61_698_899, 6.6, 1780,
            [28, 12, 36],
            [
                (3131, "Antonio Banderas", "Ahmad ibn Fadlan"),
                (6200, "Vladimir Kulich", "Buliwyf"),
                (1789, "Omar Sharif", "Melchior"),
            ],
        ),
        (
            428078, "Mortal Engines", 100_000_000, 83_672_673, 6.1, 4520,
            [12, 878],
            [
                (1360281, "Hera Hilmar", "Hester Shaw"),
                (113922, "Robert Sheehan", "Tom Natsworthy"),
                (1331, "Hugo Weaving", "Thaddeus Valentine"),
                (32747, "Stephen Lang", "Shrike"),
            ],
        ),
        (
            9016, "Treasure Planet", 140_000_000, 109_578_115, 7.5, 3980,
            [12, 16, 10751, 878],
            [
                (24045, "Joseph Gordon-Levitt", "Jim Hawkins (voice)"),
                (6198, "Brian Murray", "John Silver (voice)"),
                (7056, "Emma Thompson", "Captain Amelia (voice)"),
            ],
        ),
        (
            76757, "Jupiter Ascending", 176_000_000, 183_987_723, 5.5, 6500,
            [28, 12, 878],
            [
                (18973, "Mila Kunis", "Jupiter Jones"),
                (38673, "Channing Tatum", "Caine Wise"),
                (8767, "Eddie Redmayne", "Balem Abrasax"),
                (48, "Sean Bean", "Stinger Apini"),
            ],
        ),
        (
            49524, "R.I.P.D.", 130_000_000, 78_324_220, 5.8, 3920,
            [28, 35, 80, 14],
            [
                (1229, "Jeff Bridges", "Roy Pulsipher"),
                (10859, "Ryan Reynolds", "Nick Walker"),
                (4724, "Kevin Bacon", "Bobby Hayes"),
            ],
        ),
        (
            11692, "The Adventures of Pluto Nash", 100_000_000, 7_103_973, 4.4, 420,
            [28, 35, 878],
            [
                (776, "Eddie Murphy", "Pluto Nash"),
                (5916, "Rosario Dawson", "Dina Lake"),
                (532, "Randy Quaid", "Bruno"),
            ],
        ),
        (
            10045, "Stealth", 135_000_000, 76_932_872, 5.4, 980,
            [28, 12, 878, 53],
            [
                (2039, "Josh Lucas", "Lt. Ben Gannon"),
                (10860, "Jessica Biel", "Lt. Kara Wade"),
                (134, "Jamie Foxx", "Lt. Henry Purcell"),
            ],
        ),

        # --- Critically Acclaimed Hidden Gems ("Hidden Gems" Feature) ---
        (
            17431, "Moon", 5_000_000, 9_760_104, 7.6, 4250,
            [18, 878],
            [
                (6807, "Sam Rockwell", "Sam Bell"),
                (1979, "Kevin Spacey", "GERTY (voice)"),
                (55470, "Dominique McElligott", "Tess Bell"),
            ],
        ),
        (
            220289, "Coherence", 50_000, 102_617, 7.5, 2650,
            [9648, 878, 53],
            [
                (1181313, "Emily Baldoni", "Em"),
                (62861, "Maury Sterling", "Kevin"),
                (35596, "Nicholas Brendon", "Mike"),
            ],
        ),
        (
            369557, "Sing Street", 4_000_000, 13_600_000, 7.9, 2180,
            [35, 18, 10402, 10749],
            [
                (1521571, "Ferdia Walsh-Peelo", "Conor 'Cosmo' Lawlor"),
                (1464650, "Lucy Boynton", "Raphina"),
                (73385, "Jack Reynor", "Brendan Lawlor"),
                (2983, "Aidan Gillen", "Robert Lawlor"),
            ],
        ),
        (
            371645, "Hunt for the Wilderpeople", 2_500_000, 23_200_000, 7.7, 2050,
            [12, 35, 18],
            [
                (4783, "Sam Neill", "Uncle Hec"),
                (1560244, "Julian Dennison", "Ricky Baker"),
                (34892, "Taika Waititi", "Minister"),
            ],
        ),
        (
            500664, "Upgrade", 3_000_000, 16_700_000, 7.5, 3850,
            [28, 27, 878, 53],
            [
                (85034, "Logan Marshall-Green", "Grey Trace"),
                (1371379, "Betty Gabriel", "Detective Cortez"),
                (1473284, "Harrison Gilbertson", "Eron Keen"),
            ],
        ),
        (
            169813, "Short Term 12", 1_000_000, 1_613_644, 7.8, 1520,
            [18],
            [
                (60073, "Brie Larson", "Grace"),
                (589652, "John Gallagher Jr.", "Mason"),
                (1206337, "Kaitlyn Dever", "Jayden"),
                (1265629, "LaKeith Stanfield", "Marcus"),
            ],
        ),
        (
            14784, "The Fall", 30_000_000, 3_669_465, 7.7, 1340,
            [12, 18, 14],
            [
                (72095, "Lee Pace", "Roy Walker / The Black Bandit"),
                (80352, "Catinca Untaru", "Alexandria"),
                (15854, "Justine Waddell", "Nurse Evelyn"),
            ],
        ),
        (
            417644, "Leave No Trace", 6_000_000, 7_700_000, 7.5, 1190,
            [18],
            [
                (11107, "Ben Foster", "Will"),
                (1658932, "Thomasin McKenzie", "Tom"),
                (58563, "Dale Dickey", "Dale"),
            ],
        ),
        (
            84332, "Safety Not Guaranteed", 750_000, 4_400_000, 7.4, 1490,
            [35, 18, 10749, 878],
            [
                (89185, "Aubrey Plaza", "Darius Britt"),
                (45407, "Mark Duplass", "Kenneth Calloway"),
                (12799, "Jake Johnson", "Jeff Schwensen"),
            ],
        ),
        (
            807196, "Boiling Point", 850_000, 1_200_000, 7.6, 890,
            [18, 53],
            [
                (1118, "Stephen Graham", "Andy Jones"),
                (1366558, "Vinette Robinson", "Carly"),
                (142516, "Jason Flemyng", "Alastair Skye"),
            ],
        ),
        (
            290098, "The Handmaiden", 8_800_000, 38_600_000, 8.2, 3420,
            [18, 9648, 10749, 53],
            [
                (115295, "Kim Min-hee", "Lady Hideko"),
                (1614392, "Kim Tae-ri", "Sook-hee"),
                (83024, "Ha Jung-woo", "Count Fujiwara"),
            ],
        ),
    ]

    with get_connection(db_path) as conn:
        cur = conn.cursor()
        for gid, gname in genre_types:
            cur.execute(
                "INSERT OR IGNORE INTO Genre_Types (genre_id, genre_name) VALUES (?, ?)",
                (gid, gname),
            )

        for (
            movie_id,
            title,
            budget,
            revenue,
            vote_average,
            vote_count,
            gids,
            cast_members,
        ) in sample_movies:
            cur.execute(
                """
                INSERT OR REPLACE INTO Movies
                (movie_id, title, budget, revenue, vote_average, vote_count)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (movie_id, title, budget, revenue, vote_average, vote_count),
            )

            for gid in gids:
                cur.execute(
                    "INSERT OR IGNORE INTO Genres (movie_id, genre_id) VALUES (?, ?)",
                    (movie_id, gid),
                )

            for actor_id, actor_name, character_name in cast_members:
                cur.execute(
                    "INSERT OR IGNORE INTO Actors (actor_id, actor_name) VALUES (?, ?)",
                    (actor_id, actor_name),
                )
                cur.execute(
                    """
                    INSERT OR REPLACE INTO Movie_Cast (movie_id, actor_id, character_name)
                    VALUES (?, ?, ?)
                    """,
                    (movie_id, actor_id, character_name),
                )

        conn.commit()
        return {
            "movies": conn.execute("SELECT COUNT(*) FROM Movies").fetchone()[0],
            "genres": conn.execute("SELECT COUNT(*) FROM Genres").fetchone()[0],
            "actors": conn.execute("SELECT COUNT(*) FROM Actors").fetchone()[0],
            "cast_links": conn.execute("SELECT COUNT(*) FROM Movie_Cast").fetchone()[0],
        }


def download_tmdb_5000(data_dir: str = DATA_DIR) -> bool:
    """Download TMDB 5000 CSV files into data_dir if not already present."""
    import urllib.request

    os.makedirs(data_dir, exist_ok=True)
    files = {
        os.path.join(data_dir, "tmdb_5000_movies.csv"): (
            "https://raw.githubusercontent.com/missvicki/TMDb-movie-data/master/tmdb_5000_movies.csv"
        ),
        os.path.join(data_dir, "tmdb_5000_credits.csv"): (
            "https://raw.githubusercontent.com/missvicki/TMDb-movie-data/master/tmdb_5000_credits.csv"
        ),
    }
    try:
        for dest, url in files.items():
            if not os.path.exists(dest):
                print(f"[INFO] Downloading {os.path.basename(dest)}...")
                urllib.request.urlretrieve(url, dest)
                print(f"[INFO] Saved {dest} ({os.path.getsize(dest):,} bytes)")
        return True
    except Exception as e:
        print(f"[WARN] Could not auto-download TMDB 5000 CSVs: {e}")
        return False


def run_ingestion(
    data_dir: str = DATA_DIR,
    force_sample: bool = False,
    max_cast: int = 10,
    auto_download: bool = False,
) -> Dict[str, int]:
    """
    Detect Kaggle CSV files in data_dir and ingest them into SQLite,
    or seed sample data if force_sample=True or no CSVs are present.
    """
    if force_sample:
        print("[INFO] Seeding curated real TMDB sample dataset into movies.db...")
        counts = seed_sample_data(reset=True)
        print(f"[DONE] Seeded {counts['movies']} movies, {counts['actors']} actors, "
              f"{counts['cast_links']} cast roles, and {counts['genres']} genre links.")
        return counts

    tmdb_movies = os.path.join(data_dir, "tmdb_5000_movies.csv")
    tmdb_credits = os.path.join(data_dir, "tmdb_5000_credits.csv")
    meta_movies = os.path.join(data_dir, "movies_metadata.csv")
    meta_credits = os.path.join(data_dir, "credits.csv")

    if auto_download and not os.path.exists(tmdb_movies) and not os.path.exists(meta_movies):
        download_tmdb_5000(data_dir)

    if os.path.exists(tmdb_movies):
        print(f"[INFO] Found Kaggle TMDB 5000 dataset in {data_dir}. Ingesting...")
        counts = ingest_tmdb_5000(tmdb_movies, tmdb_credits, max_cast=max_cast)
        print(f"[DONE] Ingested {counts['movies']} movies, {counts['actors']} actors, "
              f"{counts['cast_links']} cast roles, and {counts['genres']} genre links.")
        return counts

    if os.path.exists(meta_movies):
        print(f"[INFO] Found Kaggle 'The Movies Dataset' in {data_dir}. Ingesting...")
        counts = ingest_the_movies_dataset(meta_movies, meta_credits, max_cast=max_cast)
        print(f"[DONE] Ingested {counts['movies']} movies, {counts['actors']} actors, "
              f"{counts['cast_links']} cast roles, and {counts['genres']} genre links.")
        return counts

    print(f"[INFO] No Kaggle CSV files found in '{data_dir}'.")
    print("[INFO] Seeding built-in curated TMDB dataset so you can run and test immediately!")
    counts = seed_sample_data(reset=True)
    print(f"[DONE] Seeded {counts['movies']} movies, {counts['actors']} actors, "
          f"{counts['cast_links']} cast roles, and {counts['genres']} genre links.")
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest Kaggle Movie CSVs or seed sample data into SQLite.")
    parser.add_argument("--data-dir", default=DATA_DIR, help="Directory containing Kaggle CSV files")
    parser.add_argument("--sample", action="store_true", help="Reset DB and load curated TMDB sample dataset")
    parser.add_argument("--download", action="store_true", help="Automatically download TMDB 5000 CSVs if missing")
    parser.add_argument("--max-cast", type=int, default=10, help="Max cast members to import per movie")
    args = parser.parse_args()

    os.makedirs(args.data_dir, exist_ok=True)
    run_ingestion(
        data_dir=args.data_dir,
        force_sample=args.sample,
        max_cast=args.max_cast,
        auto_download=args.download,
    )
