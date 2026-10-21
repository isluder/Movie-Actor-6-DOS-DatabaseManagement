# 🎬 Film Reel-ational Data

**Database Management Project** — SQLite + Python (Flask)  
**Team Members:** Andrew & Isaac

---

## 🚀 Quick Start (Ready for October 26th Demo)

The database (`movies.db`) is already initialized and pre-seeded with curated real TMDB movie records (including major blockbusters, famous box office bombs, and critically acclaimed hidden gems).

### 1. Start the Flask Web Application
```powershell
python app.py
```
Then open **[http://127.0.0.1:5000](http://127.0.0.1:5000)** in your browser.

---

## 📦 Loading Full Kaggle CSV Datasets (Optional)

To load the full Kaggle datasets instead of the built-in sample dataset, place any of the following CSV files into the `data/` folder:
- **Option A (TMDB 5000 Movies):** `data/tmdb_5000_movies.csv` and `data/tmdb_5000_credits.csv`
- **Option B (The Movies Dataset):** `data/movies_metadata.csv` and `data/credits.csv`

Then run:
```powershell
python ingest_data.py
```
To reset back to the curated sample dataset at any time:
```powershell
python ingest_data.py --sample
```

---

## 🗄️ Relational Schema Notes (Corrections to Proposal Draft)

In [schema.sql](schema.sql), we implemented your relational schema and fixed a few minor SQL syntax issues from the proposal draft:
1. Added missing commas in `Actors`, `Movie_Cast`, and `Genres`.
2. Added a 3NF lookup table `Genre_Types (genre_id PRIMARY KEY, genre_name UNIQUE)` so that `Genres (movie_id, genre_id)` has a valid foreign key target (`FOREIGN KEY (genre_id) REFERENCES Genre_Types(genre_id) ON DELETE CASCADE`) and stores human-readable genre names without redundancy.
3. Enabled `PRAGMA foreign_keys = ON;` on every SQLite connection in [database.py](database.py) so `ON DELETE CASCADE` is actively enforced when deleting movies.
