# Film Reel-ational Data

Andrew and Isaac's Flask + SQLite Database Management project. Search movies,
compare values from two datasets, and explore actor–movie connections through a
six-degrees graph. No account is required.

## Run locally

From the repository root:

```bash
python -m pip install -r requirements.txt
python src/ingest_data.py rebuild --dataset both --confirm
python -m flask --app src.app:create_app run --port 5001
```

Open <http://127.0.0.1:5001>. Rebuild once for the simplified schema, including
when upgrading an existing database. Each rebuild validates a staged catalog,
backs up the old database in `src/backups/`, and replaces the schema and data in
one transaction. Failed staging or activation leaves the previous catalog intact.
Restart any running server after upgrading. Importing Python modules never builds
a catalog, and missing data never silently falls back to the demo.

## Seven-table schema

See [src/schema.sql](src/schema.sql) for formatted definitions and constraints.

| Table | Purpose |
|---|---|
| `films` | Movie identity and display title |
| `people` | Actor identity and canonical name |
| `cast_roles` | Movie–actor links, characters, source, and credit order |
| `catalog_genres` | Genre identities and names |
| `film_genres` | Movie–genre links by source |
| `film_values` | Each source's title, budget, revenue, rating, and vote count |
| `catalog_meta` | Current catalog version and one import summary |

`film_values` keeps the numerical fields outside `films` so both datasets' values
remain available for Source Differences. Exact duplicate values collapse; conflicting
records within the same source remain separate variants. Multiple character roles
per actor/movie are retained. Actor names use the first imported name for each
TMDB ID. Movie search and cast/genre filters browse the combined catalog; the
numerical source selector controls ratings and financial values. The graph has a
separate source selector for its cast network.

Accounts, saved searches, web catalog editing/imports, local overrides, hiding,
edit history, raw-row archives, file hashes, and import-history tables have been
removed. Original CSVs remain under `CSV-Files/`. Old accounts and local edits are
available only in the pre-upgrade backup. Manual Entry uses a signed form token; no account is required.

## Data sources and comparison

Canonical inputs:

```text
CSV-Files/
  TMDB 5000 Movie Dataset/
    tmdb_5000_movies.csv
    tmdb_5000_credits.csv
  The Movies Dataset/
    movies_metadata.csv
    credits.csv
```

The importer performs no downloads. Both datasets use TMDB movie/actor IDs. Source
Differences compares titles, budgets, revenues, ratings, and vote counts, with
field filters and counts over the complete matching set. Movie details also show
source-specific values, genres, and cast roles.

Numerical queries default to The Movies Dataset. All numerical filters and arithmetic
use the chosen source together. Missing records and ambiguous same-source variants
are excluded from numerical filtering and aggregates, with coverage counts shown.
Invalid/missing numbers become NULL; source zeros remain stored. Zero budget or
revenue means unknown for financial eligibility.

Hidden Gems defaults to rating ≥7.4, 50–4,500 votes, and known budget ≤$35M. Its
score is `rating * (1 + (1 - votes / (max_votes + 1)) * 0.25)`, a discovery heuristic.
Box-office shortfalls require known revenue below known production budget, with
a default minimum budget of $10M. Revenue minus production budget does not measure
studio profit. Sorting and summary statistics cover all matches before pagination.

## Graph and dashboards

Six Degrees finds shortest paths within six shared-film steps using the complete
selected cast network. Voice roles count; shared credits do not establish personal
contact. Rendering caps of 300 nodes and 1,000 edges do not limit path search.
Double-click graph nodes to expand neighbors in batches of 15. Source labels and
all roles remain available on edges. Depth controls, textual paths, actor suggestions,
and actor distance statistics remain supported.

Dashboard cards can be customized and reset. Card preferences stay in browser
storage per page. These preferences do not require accounts or database tables.

## Utility menu, SQL Search, and Manual Entry

The top-right ≡ menu contains Movie Search, Source Differences, SQL Search,
Manual Entry, and the Light/Dark mode button. Disabled features appear as disabled
menu items. Hidden Gems, box-office searches, and Six Degrees remain visible tabs.
Theme choice persists in browser storage.

SQL Search accepts a single read-only query, including joins and CTEs. Example
buttons load editable queries for ratings, shortfalls, actor credits, source
differences, genres, and manual entries; they do not execute automatically.
A table reference lists the actual schema. Queries use a read-only SQLite connection
with an authorizer that rejects writes, schema changes, PRAGMAs, and database
attachments. Results show at most 500 rows, cell text is shortened to 2,000
characters, and queries have a two-second execution limit.

Manual Entry creates a movie with an allocated negative ID, or adds separate
manual-source values to an existing movie ID. Optional cast rows can reference
existing actor IDs or create distinct new actors; genres come from the catalog's
list. Blank numeric fields remain unknown. All fields validate before the entry
is committed in one transaction. Imported values stay intact. Select Manual entries
for numerical searches or its cast network, or use Combined sources for graph
connections. Catalog rebuilds replace manual entries, with a pre-rebuild backup.

## Configuration

`config.yaml` controls Movie Search, Hidden Gems, Bombed at the Box Office, Source
Differences, Six Degrees, Interactive Graph, Dashboard Statistics, and SQL Previews.
SQL Search and Manual Entry also have independent switches. Set Enable/Disable
and restart. Unknown names, duplicate
keys, invalid values, and missing configuration files stop startup with an error.
Omitted known switches default to enabled. Disabling Interactive Graph retains a
textual six-degrees path; disabling Six Degrees disables the interactive graph too.
Set `MOVIE_CONFIG_FILE` to select another configuration file.

## Validate, rebuild, and recover

```bash
# Validate the complete input without changing the active database:
python src/ingest_data.py validate --dataset both

# Rebuild and migrate, with a pre-rebuild backup:
python src/ingest_data.py rebuild --dataset both --confirm

# Small isolated demo database:
python src/ingest_data.py rebuild --dataset demo --db /tmp/movie-demo.db --confirm
```

Selections are `both`, `movies`, `tmdb`, and `demo`. `--data-dir` selects the parent
of the two dataset directories; `--db` selects the output. `--max-cast N` explicitly
creates an incomplete catalog, labeled in the import summary. Full imports check
movie identity and role coverage, foreign keys, and SQLite integrity. The summary
counts rejected and warning rows without retaining their raw contents.

To undo the schema upgrade, stop the server, restore the matching older code, and
copy the chosen database backup over `src/movies.db`. Older backups require their
older code because their schemas differ.

## Tests

```bash
python -m unittest discover -s tests -v
node tests/test_graph_ui.cjs
node tests/test_dashboard_ui.cjs
node tests/test_distances_ui.cjs
```

Python tests cover imports, source differences, source-coherent analytics, sorting,
pagination, graph traversal/expansion, feature switches, removed routes, SQL
constraints, legacy-schema migration, backup contents, and transactional rollback.
JavaScript tests exercise graph events, dashboard customization, and actor distance
controls headlessly.
