# Historical implementation notes

These notes describe the application before the seven-table simplification.
For the current implementation, setup, schema, and tests, see [README](../README.md).

# Implementation and verification — October 21, 2026

The app now uses explicit catalog imports, preserved source records, private saved
searches, and a bipartite six-degrees graph. See the root README for operational
instructions and analytical definitions. The earlier codebase review is historical.

## Delivered behavior

- Movie/actor identity is separate from source values; every original CSV row is
  retained with parsed values, validation status, source hash, and line number.
- Complete casts from both datasets, multiple roles, actor-name aliases, source
  variants, and source-aware numerical predicates are retained. Invalid values
  remain inspectable; financial unknowns do not silently become profits/losses.
- Source Differences compares records without modifying them. Local admin edits
  are recorded separately; imported cast roles can be locally hidden/restored.
- Rebuild stages and validates data, locks catalog activation against other writers,
  snapshots the previous database, and replaces catalog tables transactionally.
  Accounts and saves persist. Startup and imports of Python modules never seed data.
- Registration, login/logout, password change/reset, administrator CLI creation,
  scrypt password hashes, session invalidation, CSRF, ownership checks, and basic
  failed-login throttling are implemented.
- Each query page supports named private saves, notes, favorites, replay, and filter
  updates through the normal page controls. Changed catalogs are disclosed.
- Numerical validation is shared; actor and character predicates match the same
  cast member. Pagination and all-match aggregates replace fixed result caps.
- Six-degrees BFS runs over the complete selected actor/movie network, independently
  of visualization limits. Cache keys include catalog version and selected source.
  Read requests use a consistent SQLite transaction snapshot.
- Cytoscape.js 3.33.0 is pinned and served locally with its license. The graph has
  a depth 0–3 slider, highlighted path, visible trimming notice, hover details,
  click-to-pin details, fit/zoom/pan, and an accessible textual path.

## Catalog verified from the downloaded CSVs

| Item | Verified count |
|---|---:|
| Distinct movie identities | 45,641 |
| Actors | 206,730 |
| Distinct actor–movie pairs | 562,552 |
| Source-labeled roles | 668,297 |
| The Movies Dataset valid IDs | 45,433 |
| TMDB 5000 valid IDs | 4,803 |
| Overlapping movie IDs | 4,595 |
| Rejected metadata-ID rows | 3 |
| Duplicate metadata rows beyond distinct IDs | 30 |
| Movies with ambiguous attributes within The Movies Dataset | 2 |
| Missing valid parsed roles after import | 0 |

The importer compares actual movie ID sets and role sets to the source-derived
expectations, not just row counts. SQLite integrity and foreign-key checks pass.
`catalog-coverage.json` contains the complete import report. Original legacy
catalog backups remain in the ignored `src/backups/` directory. Accounts have no
default credentials: create the initial administrator through the documented CLI.

## Checks performed

`python3 -m unittest discover -s tests -v`: **16 tests pass**, including:

- ID/role coverage, duplicate variants, malformed-row preservation, and empty casts;
- default analytical agreement, source coherence, same-actor role matching,
  numerical validation, unknown IDs, and pagination;
- hashed credentials, CSRF, admin permissions, login throttling, private saves,
  saved-setting updates/replay, and password-change session invalidation;
- deterministic shortest paths, six-degree boundaries, interrupted searches,
  graph limits independent of path length, and cache invalidation;
- local relationship suppression/restoration and preserved source originals;
- backup contents, account/save persistence across rebuilds, failed staging, and
  rollback after activation has begun;
- commit/rollback/close behavior and a factory that does not initialize a database.

JavaScript syntax checks (`node --check`), Python compilation, and launcher syntax
checks (`bash -n`) pass. The full-catalog search, analyses, differences, movie detail,
and graph endpoints return HTTP 200. Timings from one local test-client run are in
`full-catalog-timings.json`; these are smoke-check measurements, not load-test claims.

Browser verification confirmed the source-aware catalog layout, Tom Hanks → Apollo
13 → Kevin Bacon, slider expansion, the trimming notice, and pinned Kevin Bacon
details. A screenshot is saved in `screenshots/six-degrees.png`.

## Limits

The source files include empty/missing credits and historical snapshots; complete
import does not establish a complete real-world collaboration network. Paths are
limited to six degrees, and time-interrupted searches report interruption explicitly.
The combined graph identifies relationships from either dataset, with provenance.

The Docker daemon was unavailable, so no container image build/run was verified.
The runtime and notebook targets are separated and launcher syntax was checked.
The account system targets local/classroom use; public hosting/email recovery and
multi-worker deployment hardening are outside this version.

## Incremental double-click expansion

Double-clicking a node now loads immediate neighbors in batches of up to 15:
actor → movies, or movie → cast. Repeating the gesture pages through remaining
neighbors without duplicating existing graph elements or overwriting highlighted
path attributes. New nodes are positioned near the selected node; existing node
positions and the viewport are preserved. A Path only button clears expansions.
Labels are limited to the path, selection, and hover to reduce visual clutter.
An expansion button in the details panel provides the same action via keyboard.

The read-only `/api/expand-node` endpoint validates node kind/ID, source, offset,
limit (1–15), catalog version, hidden movie status, and relationship suppressions.
The frontend enforces the existing 300-node/1,000-edge limits. Resetting the graph
or moving the slider invalidates outstanding expansion responses.

Verification: 16 Python tests pass, including incremental actor/movie expansion,
source selection, role provenance, pagination, hidden movies, and stale-version
rejection. `node tests/test_graph_ui.cjs` uses the real bundled Cytoscape library
headlessly to exercise double-tap events, actor/movie expansion, repeat paging,
path/duplicate preservation, unchanged existing positions, and stale-response
rejection after reset. Full-catalog endpoint smoke checks returned at most 15
neighbors per request. The application remained stopped during this change;
no new browser/server session was started for these checks.

## Feature switches and workspace cleanup

`config.yaml` lists the application's feature switches, all initially enabled.
`src/features.py` validates the YAML at startup; the Flask factory enforces the
switches on routes, JSON endpoints, navigation, saved-query replay, and controls.
Accounts, registration, password changes, and saved searches are separate switches;
disabling accounts also disables dependent web features. Password hashing, CSRF,
and authorization are always enforced on enabled features. Admin recovery/setup
commands remain available through the CLI. A graph-disabled Six Degrees page
retains a server-rendered textual path. The box-office page and dashboard now use
the label “Bombed at the Box Office.”

Cleanup removed generated caches, macOS metadata, the disposable environment-check
database, the empty former CSV directory, both generated root exploration databases,
and one byte-identical backup. The active catalog, two distinct legacy backups,
original notebooks/reports, downloaded CSVs, signing secret, and virtual environment
are retained. The notebook can regenerate the exploration databases from the CSVs.

Verification after feature configuration: **19 Python tests pass**, including YAML
validation, disabled route/API enforcement, account dependencies, password and
registration switches, textual-path fallback, and saved queries for disabled pages.
The headless graph interaction tests also pass. No server was started.

## Separate sort field and direction

Movie Search, Hidden Gems, and Bombed at the Box Office now use separate Sort by
and Order controls. Every listed field supports ascending and descending order;
labels use readable metric names. The shared sorting macro and allowlisted server
validation replace page-specific combined options. Production-budget shortfall
sorts by a positive shortfall amount, so descending shows the greatest shortfall.
Unknown metrics stay last in both directions, and movie IDs resolve ties for
stable pagination. Title sorting includes movies absent from the selected source.

Existing combined sort values are normalized when opening bookmarks or saved
queries. New saves retain field and direction independently. Tests use their own
feature configuration so local YAML preferences do not affect authentication checks.

Verification: **21 Python tests pass**. Sorting checks cover every available field
in both directions, missing metrics, title ordering, tied pagination, invalid sort
inputs, legacy saved searches, and new saved field/direction settings. Full-catalog
smoke checks passed on all three sortable pages. No server was started or restarted.

## Customizable dashboard and compact results

Movie Search has four colored statistic cards; Hidden Gems and Bombed at the Box
Office each have three. Clicking a card opens an accessible dialog to choose its
metric and preview the definition. Choices persist in browser storage per page;
guest use, restoring defaults, unavailable storage, and stale settings are handled.
The Dashboard Statistics feature switch hides cards on all three pages.

Cards disclose catalog/source/result scope. Matching totals, mean known ratings
and budgets, combined known revenue, production shortfalls, and mean revenue-minus-
budget ratios are computed across complete results before pagination. They use
coherent selected-source values and exclude ambiguous/unknown metrics as appropriate.
The default Hidden Gems definition remains unchanged.

Compact result rows display genres, a three-person cast preview in original source
credit order, ratings, and financial columns. Detailed source records are collapsed
by default. Ordinary views omit vote-count-only difference badges; the explicit
comparison page retains them and all originals remain available.

Verification: 24 Python tests and the dashboard JavaScript interaction tests pass.
Tests cover source coherence, unknown values, all-page totals, feature switches,
hidden cast roles, source-record availability, customization persistence, updated
values after filtering, resets, stale preferences, and unavailable browser storage.
Browser verification on a temporary local preview confirmed card customization and
reload persistence. The existing app server was left running without interruption;
restart it to load the updated Python code and templates.

## Connection distribution and comparison dashboard

Added full-filter, full-set comparison cards, including vote-only counts and
per-field counts. Six Degrees now loads an exact connected-component distance
histogram asynchronously for its From actor and selected cast source. It counts
all catalog identities in the unreachable denominator, excludes self/unreachable
actors from the mean, reports distances beyond six separately, and shows a full
shortest route to a deterministic farthest actor with the number of actors tied.
BFS traverses movie casts without generating actor cliques. Bounded version-keyed
summary caching, interruption semantics, and stale browser-response rejection are
covered by tests; existing graph search and display bounds are unchanged.

Full-catalog observation: Tom Hanks, combined network, reaches 199,871 other
actors; 6,858 are unreachable, mean distance 2.6713, maximum eight (24 tied),
49 reachable actors beyond six. One deterministic farthest actor is Abbas
Kiarostami. Initial calculation including adjacency load was ~2.3s, traversal
~0.17s. Cached repeats were below a millisecond in a local direct call.

Verification: 27 Python tests and dashboard, graph, and distance JavaScript checks
pass. Browser preview verified live statistics, comparison customization, the
distance chart, and the eight-degree farthest route. Screenshots are retained in
`docs/screenshots/difference-statistics.png` and `distance-distribution.png`.
