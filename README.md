# Movie-Actor-6-DOS-DatabaseManagement

Andrew and Isaac's Database Management course project. The Flask app is in `src/`;
the original exploration notebook and raw-dataset reports remain at the root.

## Run locally

From the repository root, with your virtual environment activated:

```bash
python -m pip install -r src/requirements.txt
python src/app.py
```

Open http://127.0.0.1:5000. If macOS is already using port 5000:

```bash
python -m flask --app src/app.py run --port 5001
```

`src/requirements.txt` installs the Flask runtime. The root `requirements.txt`
retains the existing notebook environment and includes Flask.

## Layout

| Path | Purpose |
|---|---|
| `src/app.py` | Flask routes, forms, and HTML rendering |
| `src/database.py` | SQLite connections, queries, and CRUD |
| `src/ingest_data.py` | CSV parsing and normalized database population |
| `src/schema.sql` | Tables, constraints, foreign keys, and indexes |
| `src/templates/`, `src/static/` | Jinja HTML and CSS |
| `src/data/` | Andrew's TMDB CSV inputs, ignored by Git |
| `src/movies.db` | Working app database, ignored by Git |
| `src/prototype_ingestion.ipynb` | Andrew's ingestion/query demonstration |
| `prototyping.ipynb` | Isaac's raw-data and nested-field exploration |
| `CSV-Files/` | Existing raw CSVs, ignored by Git |
| `movies_dataset.db`, `tmdb_5000.db` | Raw SQLite copies, ignored by Git |
| `docs/codebase-review.md` | Explanation, findings, and cleanup priorities |

The app implements movie/actor/character/genre searches, movie/cast editing,
box-office comparisons, and hidden-gem discovery. Six-degrees search is not yet
implemented.

## Data workflow

Isaac's notebook preserves raw CSV structure, including cast/genres stored as
text. Andrew's importer expands those fields into `Movies`, `Actors`,
`Movie_Cast`, `Genre_Types`, and `Genres`. The app needs that normalized schema;
pointing it at a raw database will not work. Rerunning the raw-database notebook
is unnecessary for the app.

Import directly from Isaac's existing CSV folder:

```bash
python src/ingest_data.py --data-dir "CSV-Files/TMDB 5000 Movie Dataset"
```

Or use Andrew's existing `src/data/` CSVs:

```bash
python src/ingest_data.py
```

To select the larger dataset:

```bash
python src/ingest_data.py --data-dir "CSV-Files/The Movies Dataset"
```

Back up `src/movies.db` before importing. Imports replace overlapping movies and
rebuild their links, but retain unrelated existing movies. The supplied database
contains 4,817 movies, mixing TMDB 5000 and demo records. A fresh TMDB 5000 import
contains 4,803 movies. By default, imports keep at most 10 cast members per movie;
increase `--max-cast` for broader coverage.

This command **deletes and recreates** the working database with 32 demo movies:

```bash
python src/ingest_data.py --sample
```

If the working database is missing or empty, app startup imports `src/data/`
CSVs or seeds demo data if CSVs are absent. The web Reload Data button also uses
`src/data/`; a CLI `--data-dir` selection is not saved for subsequent reloads.

## Container

With the Docker-compatible runtime running:

```bash
bash run-app.bash
```

This uses the existing Dockerfile, mounts the repository to preserve database
changes, and publishes http://127.0.0.1:5000. The original `bash run.bash` still
performs the pandas/SQLite environment check. The Flask server is intended for
local course development and demonstration.
