# Film Reel-ational Data

Andrew and Isaac's Flask + SQLite Database Management project. Search movies,
compare values from two datasets, find similar movies, and explore actor–movie
connections through a six-degrees graph. Build a free-form knowledge graph in
your browser. No account is required.

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
Double-click graph nodes to expand neighbors in batches of 15. The “Explore in
Knowledge Graph Builder” control opens the current visible graph (including
expansions), source selection, and selected node in a new tab. It is hidden when
the builder is disabled. Source labels and
all roles remain available on edges. Depth controls, textual paths, actor suggestions,
and actor distance statistics remain supported.

Dashboard cards can be customized and reset. Card preferences stay in browser
storage per page. These preferences do not require accounts or database tables.

## Utility menu, SQL Search, and Manual Entry

The home page introduces the catalog and links to the enabled features. Movie
Search is at `/movie-search`; old root URLs with search parameters redirect there.
The top-right ≡ menu contains Home, Build your own knowledge graph, Movie Search,
Source Differences, SQL Search, Manual Entry, and the Light/Dark mode button. Disabled features appear as disabled
menu items. Hidden Gems, box-office searches, Six Degrees, and Similar Movies
are visible tabs.
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

## Similar Movies and your own knowledge graph

Similar Movies searches by title, then ranks the other movies by cosine similarity.
It uses small, sparse TF–IDF vectors of actor IDs, title words (including source
variants), and genre IDs. Each available feature group is normalized to equal
weight; the combined vector is normalized again. Duplicate source credits and
roles do not increase an actor's weight. Results explain their shared features.
Scores describe metadata overlap, not plot semantics or recommendation confidence.
No model download or new Python dependency is required.

The full index is built only by an explicit command, never during page loads:

```bash
# Read-only timing estimate from up to 1,500 movies:
python -m flask --app src.app:create_app build-similarity-index --benchmark
# Build the complete catalog index:
python -m flask --app src.app:create_app build-similarity-index
```

The compressed index sits beside the database as `*.db.similarity.json.gz` and
is excluded from Git. It publishes atomically. Rebuild it after a catalog rebuild
or Manual Entry: the page refuses an index from an older catalog version.

Build your own knowledge graph is a read-only visual explorer of the database.
Search Movie, Actor, or Genre labels. Movie term searches include source titles,
cast names, character roles, and genre names. The search and role text fields
suggest matching catalog values after two characters, with a short typing delay.
Suggestions respect the current source and filters; you can also enter your own
terms. Add individual results or a page of
20 records; relationships between visible records connect automatically.
Double-click a movie to expand its cast/genres, an actor to expand their movies,
or a genre to expand its movies. Each expansion adds up to 20 unseen neighbors.

Choose cast-credit edges, movie–genre edges, or both, and optionally match character
or role text on cast edges. A source selector supports one dataset or Combined sources for relationships.
Financial filters require a single dataset, keeping numerical values separate. Genre, budget, and revenue filters constrain searches
and expansion; applying filters also removes disqualified movies from the canvas.
Unknown/zero financial values and ambiguous same-source variants do not pass
financial filters. Selecting a movie still shows all its source-specific values.
Changing the source clears the canvas to start a consistent new exploration.

Drag nodes, arrange or fit the graph, adjust node/edge text size, inspect source
and role details, remove items from the canvas, or export displayed records and
positions as JSON. A text list and Expand button provide an alternative to canvas
interaction. The display holds up to 300 nodes and 1,000 edges. Catalog version
checks reject expansion after a catalog change. No catalog tables are modified;
the free-form editor and fabricated relationships have been replaced by catalog
records and actual relationships. The canvas is session-only; export keeps a copy.

## Configuration

Every application page has a switch under `application_features` in `config.yaml`:
Home Page, Movie Search, Movie Details, Hidden Gems, Bombed at the Box Office,
Source Differences, Six Degrees, SQL Search, Manual Entry, Similar Movies,
Build your own knowledge graph, and Setup Page. Interactive Graph, Dashboard
Statistics, and SQL Previews control components within those pages.

Set `Enable` or `Disable`, then restart Flask. Disabled pages and their associated
APIs return 404, and their links are removed or marked disabled. If Home Page is
disabled, `/` redirects to the first enabled landing page, including utilities.
If no landing pages are enabled, `/` returns 404. Disabling Movie Details retains
movie labels and source values in searches/graphs without links to the detail page;
Manual Entry still saves and returns to its form. With Setup Page disabled, an
unavailable catalog shows a generic 503 message instead of setup instructions.

Unknown names, duplicate keys, invalid values, and missing configuration files stop
startup with an error. Omitted known switches default to enabled. Disabling
Interactive Graph retains a textual six-degrees path; disabling Six Degrees disables
the interactive graph too. The separate knowledge graph explorer has its own switch.
Actor suggestions are shared by Movie Search and Six Degrees and are disabled when
both are disabled. Set `MOVIE_CONFIG_FILE` to select another configuration file.

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
node tests/test_knowledge_graph_ui.cjs
```

Python tests cover imports, source differences, source-coherent analytics, sorting,
pagination, graph traversal/expansion, feature switches, removed routes, SQL
constraints, legacy-schema migration, backup contents, and transactional rollback.
JavaScript tests exercise graph events, dashboard customization, and actor distance
controls, and catalog graph search, expansion, filters, text sizing, source details, and
stale responses headlessly. Similarity
tests cover source deduplication, ranking, sample benchmarking, and stale indexes.
