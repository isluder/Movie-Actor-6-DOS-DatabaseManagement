# Film Reel-ational Data

Andrew and Isaac's Flask + SQLite Database Management project. Browse movies,
compare preserved dataset values, save personal searches, and explore actor–movie
connections through a six-degrees graph.

## Run locally

From the repository root:

```bash
python -m pip install -r requirements.txt
python -m flask --app src.app:create_app init-db
python -m flask --app src.app:create_app create-admin YOUR_USERNAME
python src/ingest_data.py rebuild --dataset both --confirm
python -m flask --app src.app:create_app run --port 5001
```

Open [the app](http://127.0.0.1:5001). Admin creation prompts for a password; no
shared default password exists. If the catalog is already imported, skip its
rebuild. A missing database displays setup instructions and never seeds itself.

Ordinary users can register, log in, change passwords, and manage private saved
searches. Admins manage catalog edits and imports. Use `reset-password USERNAME`
in the same Flask CLI for local password recovery. Passwords require 12–256
characters and are stored as salted scrypt hashes. Secret signing material comes
from `MOVIE_SECRET_KEY` or an ignored, mode-0600 `src/.session-secret` file.
Keep that file private and persistent. The server targets local/classroom use.

## Feature configuration

Edit `config.yaml` in the repository root to enable or disable application features:

```yaml
application_features:
  Movie Search: Enable
  Hidden Gems: Enable
  Bombed at the Box Office: Enable
  Accounts: Enable
  Registration: Enable
  Password Changes: Enable
```

The supplied file lists every supported switch, including Six Degrees, Interactive
Graph, Source Differences, Saved Searches, Dashboard Statistics, SQL Previews,
Source Provenance, Catalog Editing, and Catalog Imports. All default to Enable;
use Disable to turn one off. Restart the app after editing. Unknown names, invalid
values, duplicate keys, and missing configuration files stop startup with an error.
Known settings omitted from a custom file retain their enabled defaults.

Disabled features disappear from navigation and controls; direct requests return
404. If Movie Search is disabled, `/` redirects to the first enabled query page.
Disabling Accounts also disables registration, password changes, saved searches,
catalog editing, and web imports. Disabling Registration alone still permits
existing accounts to log in. Password Changes controls the signed-in password form;
password hashing and login checks always remain in force. CLI administrator creation,
password reset, and rebuild commands remain available for setup and recovery.

Disabling Interactive Graph retains Six Degrees with a textual shortest path and
disables neighborhood/expansion endpoints. Saved queries for disabled pages remain
stored and can be renamed or deleted, but cannot be run or have filters updated until
the page is re-enabled. Feature switches never grant admin permissions or erase data.

Local runs resolve `config.yaml` relative to the repository, independently of the
working directory. Set `MOVIE_CONFIG_FILE` to use another file. The Docker launcher
mounts this same workspace at `/app`, so it uses the same YAML; no Dockerfile edits
are needed. Do not store passwords or session secrets in the YAML.

## Data and source semantics

Canonical CSV inputs:

```text
CSV-Files/
  TMDB 5000 Movie Dataset/
    tmdb_5000_movies.csv
    tmdb_5000_credits.csv
  The Movies Dataset/
    movies_metadata.csv
    credits.csv
```

The runtime uses no duplicate `src/data/` inputs and performs no downloads.
Ratings, crew, keywords, and MovieLens linking files remain available for research
but do not add movie identities or co-star edges to this application. Cast edges
mean shared film credits, including voice roles; they do not prove personal contact.

The verified combined catalog has **45,641 movies**, **206,730 actors**, and
**562,552 distinct actor–movie pairs**. The app retains **668,297 source-labeled
roles**. TMDB has 106,257 roles; The Movies Dataset has 562,040. No valid parsed
roles were dropped. Three malformed metadata IDs are rejected and preserved;
30 duplicate metadata rows collapse into source variants, including two movies
with ambiguous attributes within The Movies Dataset. Empty casts in the source
remain empty: full import does not mean complete real-world filmography.

Movie and actor identities use TMDB IDs. Source records retain raw CSV row
values, parsed values, hashes, original row numbers, import date, and validation
status. Collection dates are unknown unless supplied by source metadata. Both
source ratings and their corresponding vote counts are shown together. Source
Differences is an inspection view, not a resolution queue.

Numerical queries default to The Movies Dataset. Select another source explicitly;
all predicates and arithmetic use the same coherent record. Without numerical
filters the catalog still browses the full union. Missing selected-source records
and ambiguous same-source variants are excluded from numerical filters and
aggregates, with counts shown. Imported zeros remain preserved; zero budget or
revenue is treated as unknown for financial eligibility. Local numerical overrides
are source-specific and visibly labeled. Local additions use negative IDs and
require the Local additions source for numerical queries. Hiding source cast roles
preserves the originals while excluding those roles from search and graph traversal.

Hidden Gems and dashboard counts use rating ≥7.4, 50–4,500 votes, and known budget
≤$35M. Gem score is `rating * (1 + (1 - votes / (max_votes + 1)) * 0.25)`, a discovery
heuristic. Box-office shortfalls require known revenue below known production
budget, default minimum budget $10M. Revenue minus production budget does not
measure studio profit. Summary totals cover all matches, independently of pagination.

## Validate, rebuild, and recover

```bash
# Complete staging import and integrity/coverage checks, without changing the app:
python src/ingest_data.py validate --dataset both

# Rebuild with complete casts (default):
python src/ingest_data.py rebuild --dataset both --confirm

# Other explicit selections: tmdb, movies, demo.
# --data-dir selects a parent containing the two documented dataset directories.
# --db chooses a working SQLite file; --max-cast N explicitly creates an incomplete catalog.
```

The admin Imports page uses the same importer and configured input path. It
requires typing REBUILD and creates a timestamped backup in `src/backups/` before
transactional catalog replacement. Rebuild resets local additions, overrides,
hidden movies, cast suppressions, and local edit history. Accounts and saved
queries survive. The import report distinguishes rows, identities, duplicate
variants, rejected rows, empty casts, pair coverage, and role coverage. Failed
staging or activation keeps the previous catalog active.

To restore, stop the server and copy the desired backup over `src/movies.db`.
For example, `cp src/backups/CHOSEN_BACKUP.db src/movies.db`. A full backup restore
also restores accounts and saved queries to their backup state. Preserve the
signing secret separately. Original pre-upgrade database backups are retained.

## Searches and six degrees

The front page has four colored statistics cards; Hidden Gems and Bombed at the
Box Office have three cards each. Click any card to choose a different statistic,
preview its definition, and apply it. Reset cards restores the defaults. Choices
are saved per page in this browser, including for guests; they do not change other
users' dashboards or saved queries. Blocking browser storage still permits temporary
customization. Cards distinguish whole-catalog counts from the selected source's
numbers and the current results. Result statistics cover every qualifying page,
not just the rows shown. The Dashboard Statistics feature switch controls these cards.

Movie rows show compact ratings and financial figures with genres and a short cast
preview in original source credit order. Source records expand on demand, and
vote-count-only differences no longer show warning badges in ordinary browsing.
All original values remain available in movie details and Source Differences.

Movie Search, Hidden Gems, and Bombed at the Box Office have separate **Sort by**
and **Order** controls. Each listed field supports Ascending or Descending. Unknown
numerical values appear last in either direction; ties use movie ID for stable
pagination. Sorting applies to the complete matching set before pagination. Older
URLs and saved searches with combined options such as `net_loss_desc` still work;
new saved searches store the field and direction separately.

Every query page offers Save or update this search. My Searches supports notes,
favorites, rename, deletion, and opening a search to adjust its filters. Saved
specifications are validated and scoped to their owner. They rerun against the
current catalog and announce catalog changes; they are not frozen snapshots.

Six Degrees uses actor IDs, a combined or selected-source cast network, and
breadth-first traversal of the bipartite graph. One actor → movie → actor step
counts as one degree. The shortest path searches up to six degrees over the
complete selected network. A time-limited search reports interrupted, not no path.
The neighborhood slider ranges from 0 (path only) to 3 co-star degrees around the
path. Display limits are 300 nodes and 1,000 edges and never restrict path search.
Double-click an actor to reveal up to 15 movie neighbors; double-click a movie to
reveal up to 15 cast members. Repeat for the next batch. Existing nodes and the
highlighted path stay in place; expansions honor the selected cast source and local
relationship suppressions. Path only clears extra nodes. The slider remains
available for whole-layer expansion, but local expansion is easier to read. Labels
appear on the path, selected nodes, and hovered nodes. Gold marks the path, circles
actors, and diamonds movies. Hover for details, click to pin, use the Show more
button as a keyboard-accessible expansion alternative, and Fit graph to fit the
viewport. Manual expansion state is temporary; saved queries retain endpoints,
source, and slider depth. A textual
path remains available. Cytoscape.js 3.33.0 and its MIT license are served locally.

JSON read endpoints: `/api/actors?q=NAME`, `/api/connections?start=ID&end=ID&source=both`,
`/api/neighborhood?start=ID&end=ID&source=both&depth=0`, and
`/api/expand-node?node=actor:ID&source=both&offset=0&limit=15`. Expansion accepts
`actor:ID` or `movie:ID`, returns one adjacent layer, and checks `catalog_version`
when supplied to prevent expanding a stale catalog view. Responses identify catalog
version, explicit search status, degrees, path, graph elements, and truncation.

## Development and containers

```bash
python -m unittest discover -s tests -v
node tests/test_graph_ui.cjs
node tests/test_dashboard_ui.cjs
bash run-app.bash
```

`requirements.txt` includes the pinned runtime requirements under `src/`.
`requirements-notebook.txt` preserves the original exploratory environment;
`requirements-dev.txt` includes runtime dependencies, with standard-library tests.
The app container uses the Dockerfile's runtime target; `run.bash` uses its separate
notebook target for the original pandas/SQLite environment check. Container images
must be built on a compatible platform; local full-catalog verification does not
establish a successful container build.

The original root notebook and schema/inspection reports remain research artifacts.
The generated `movies_dataset.db` and `tmdb_5000.db` exploration databases were
removed during cleanup; rerun the import cells in `prototyping.ipynb` to regenerate
them from the retained CSVs before running its database-inspection sections. These
databases are separate from the active app catalog in `src/movies.db`.
The updated
`src/prototype_ingestion.ipynb` has read-only source-aware examples; its original
version is preserved under `docs/historical/`. `docs/codebase-review.md` records the
pre-upgrade review; see `docs/implementation.md` for current verification.
