# Application

See the repository [README](../README.md) for current setup, accounts, data sources,
import/backup behavior, analytical definitions, graph controls, and tests.

- `app.py`: application factory, HTML/JSON routes, authentication, saved searches, CLI.
- `database.py` / `schema.sql`: closed transactions, source-aware queries, schema.
- `ingest_data.py` / `sample_data.json`: staged imports and isolated demo fixture.
- `validation.py`: shared filter/form validation.
- `features.py` / `../config.yaml`: validated feature switches, including accounts
  and password changes; restart the app after editing the YAML.
- `graph.py`: deterministic breadth-first search and bounded graph neighborhoods.
- `dashboard.py`: source-aware statistics and customizable card metadata.
- `templates/` / `static/`: server-rendered interface and locally bundled graph library.

Inputs live only under `../CSV-Files/`. Working data, account signing secrets,
and backups are ignored by Git. Importing a Python module never rebuilds the catalog.
