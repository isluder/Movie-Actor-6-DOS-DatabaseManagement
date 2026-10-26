# Application

See the repository [README](../README.md) for setup, schema, sources, and tests.

- `app.py`: catalog HTML/JSON routes, manual entry, and setup/rebuild CLI commands.
- `database.py` / `schema.sql`: transactions, seven-table schema, source-aware queries.
- `ingest_data.py` / `sample_data.json`: validated imports, backup/migration, demo fixture.
- `sql_search.py`: bounded read-only SQL execution and editable query examples.
- `validation.py`: query and graph request validation.
- `features.py` / `../config.yaml`: startup-loaded feature switches.
- `graph.py`: breadth-first paths, bounded neighborhoods, and actor distances.
- `dashboard.py`: source-aware statistics and customizable card metadata.
- `templates/` / `static/`: interface and locally bundled graph library.

Inputs live under `../CSV-Files/`. Databases and backups are ignored by Git.
Importing a Python module never rebuilds the catalog.
