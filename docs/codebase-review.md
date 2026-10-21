> Historical pre-upgrade review. Current behavior and verification are documented in [implementation.md](implementation.md).

# Integration and code review

## How the contributions fit

Isaac's `prototyping.ipynb` reads both datasets into pandas, saves a SQLite table
per CSV, exports schemas, and inspects list/dict fields inside text columns.
`hidden_tables.md` provides evidence for splitting cast and genres into tables.

Andrew supplied a complete Flask app, including its database layer and importer.
His two TMDB CSVs are byte-for-byte identical to Isaac's. His importer already
performs the normalization suggested by Isaac's inspection. Use the normalized
app as the running application; retain the original notebook and reports as
exploration/design evidence. There is no need to merge raw databases or rewrite
the app around them. Pass Isaac's CSV folder to `--data-dir` to reuse those files.
The larger Movies Dataset is also supported. Ratings, crew, and keywords are
currently unused by the app.

## How the code works

1. The browser requests a URL such as `/?actor=Cillian+Murphy`.
2. `app.py` reads its query parameters and calls `database.search_movies()`.
3. `database.py` constructs a parameterized SQLite query. User values use `?`
   placeholders; sorting expressions come from a fixed allowlist.
4. `EXISTS` filters movies by actor/role/genre; joins and
   `GROUP_CONCAT(DISTINCT ...)` collect names for the displayed movie rows.
5. Rows become dictionaries passed to Jinja templates. Page templates extend
   `base.html`; `static/style.css` supplies the appearance.
6. Flask returns complete HTML. POST forms change the database and redirect to
   a GET page, with a flash message explaining the result.

This is a server-rendered app, with no separate React app or REST API to connect.
The small script in `add_movie.html` adds cast input rows.

| Table | Meaning | Key |
|---|---|---|
| `Movies` | Movie attributes | `movie_id` |
| `Actors` | Actor identity/name | `actor_id` |
| `Movie_Cast` | Actor's role in a movie | `(movie_id, actor_id)` |
| `Genre_Types` | Genre identifier/name | `genre_id` |
| `Genres` | A movie's genre membership | `(movie_id, genre_id)` |

Junction tables express many-to-many relationships. Each connection enables
foreign-key enforcement. Deleting a movie cascades to its cast/genre links;
shared actor and genre definitions remain. The cast primary key permits only
one stored role string per actor/movie pair; repeated roles replace earlier ones.

`ingest_data.py` streams CSV rows, parses list fields with `json.loads()` or
`ast.literal_eval()`, and inserts normalized entity/link rows. The same file
contains a large hard-coded sample dataset and optional downloading code.
`schema.sql` defines the actual constraints and indexes.

## Prepared relocation

- Move Andrew's entire folder to `src/`, retaining its inputs and database.
- Preserve Isaac's notebook, raw databases, reports, environment check, and Git
  history at the root.
- Add Flask to root requirements; keep the small runtime-only requirements file
  under `src/`.
- Replace the placeholder root README with setup/data/layout instructions.
- Add `run-app.bash` using the existing container setup.

Andrew's paths are relative to `__file__`, so `python src/app.py` continues to find
its schema, database, data, templates, and stylesheet. Application behavior is
unchanged; the issues below are findings rather than silent relocation changes.

## Data findings

The supplied database contains 4,817 movies, 19,091 actors, 44,959 cast links,
20 genre types, and 12,198 genre links. Integrity and foreign-key checks pass.
It includes recent demo films absent from the original TMDB 5000 dataset.

A fresh import of Isaac's TMDB CSVs with `max_cast=10` produces 4,803 movies,
19,063 actors, 44,927 cast links, and 12,160 genre links. Forty-three movies have
no cast, matching the source's empty cast arrays. The raw source contains
106,257 cast entries: the cap discards much of this coverage. The separate sample
database contains 32 movies, 109 actors, and 114 cast links.

## Cleanup priorities

### 1. Make imports predictable

Imports use `INSERT OR REPLACE` for Movies. Replacing a parent row triggers
`ON DELETE CASCADE`, deleting old cast/genre links before reinserting new ones.
Importing without credits can therefore remove cast links. Unmatched existing
movies remain, which explains why the supplied database mixes demo and CSV rows.

Choose explicit import semantics: build a fresh database and replace the working
copy after validation, or deliberately upsert/synchronize rows in a transaction.
Keep sample data separate and record provenance. Configure one selected CSV
source so the CLI and web Reload button use the same folder.

### 2. Fix validation and relationship semantics

- Search calls `float()` directly on rating parameters. Both
  `/?min_rating=abc` and `/?max_rating=abc` raise `ValueError` and produce a server
  error. Share numeric validation across forms/filters, including rejection of
  non-finite numbers.
- Actor and character filters use separate `EXISTS` clauses. Robert Downey Jr.
  plus Pepper matches the Iron Man movies even though Pepper is another actor's
  role. If the desired meaning is this actor playing this role, put both
  predicates in one cast subquery; otherwise clarify the independent meaning.
- Select existing actors by ID. Case-insensitive name lookup can conflate
  distinct people who share a name.
- Titles are embedded in inline JavaScript confirmation strings. Apostrophes can
  break the script after HTML entity decoding. Use data attributes and a shared
  event listener, or JavaScript-context encoding.

### 3. Close connections explicitly

`with sqlite3.connect(...) as conn` commits or rolls back but does not itself
close the connection. Introduce a closing context manager that preserves rollback
behavior, or use one Flask connection per request closed in teardown.

### 4. Standardize analytics

Dashboard gems use rating >= 7.5 and 50–5,000 votes. The gems page defaults to
>= 7.4, 50–4,500 votes, and budget <= $35M. Centralize the definitions so counts
agree. Search returns at most 100 rows; analyses return at most 50. Box-office
totals summarize the returned 50, rather than all qualifying movies. Add
pagination and label each summary's scope.

Revenue minus production budget is a simple comparison rather than measured
studio profit. Label the arithmetic explicitly and account for zero values that
may represent missing budget/revenue data.

### 5. Implement six degrees if it remains in scope

There is no actor-connection search in this app. Its current relational model
already supports it. Breadth-first search can alternate actor/movie links and
record predecessors to display actor → shared movie → actor. A recursive SQL
approach is another option. Choose according to the assignment's SQL/Python
expectations. Import complete casts first: the default cap can create missing
paths and misleading degrees of separation.

### 6. Simplify structure after behavior is stable

Keep the three Python modules for now. Extract the sample fixture into a separate
file; share repeated numeric parsing and actor lookup helpers; move inline CSS
and JavaScript to static files; factor repeated template markup into macros.

After unifying CSV configuration, remove duplicate `src/data/` CSVs and keep one
source under `CSV-Files/`. Split runtime requirements from notebook tooling.
Introduce a package/app factory later if import-time initialization or testing
becomes awkward. For use beyond a local class demo, configure the secret key,
disable debug mode, and add CSRF protection to write forms.

## Verification on disposable copies

- Search, actor/genre filters, bombs, gems, add form, movie detail, and stylesheet
  requests returned HTTP 200.
- Created/edited/deleted a test movie, added/removed cast, and verified cascading
  deletion of cast/genre links.
- Imported Isaac's TMDB CSVs into a fresh database and checked counts, SQLite
  integrity, and foreign keys; separately seeded the 32-movie sample database.
- Reproduced invalid-rating failures, independent actor/character matching, and
  cast deletion caused by replacing a parent movie.

Original databases and datasets were unchanged. The container launcher was syntax
checked; a container build/run was not performed.
