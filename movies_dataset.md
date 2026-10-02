# movies_dataset.db schema

## credits

```sql
CREATE TABLE "credits" (
"cast" TEXT,
  "crew" TEXT,
  "id" INTEGER
);
```

## keywords

```sql
CREATE TABLE "keywords" (
"id" INTEGER,
  "keywords" TEXT
);
```

## links

```sql
CREATE TABLE "links" (
"movieId" INTEGER,
  "imdbId" INTEGER,
  "tmdbId" REAL
);
```

## links_small

```sql
CREATE TABLE "links_small" (
"movieId" INTEGER,
  "imdbId" INTEGER,
  "tmdbId" REAL
);
```

## movies_metadata

```sql
CREATE TABLE "movies_metadata" (
"adult" TEXT,
  "belongs_to_collection" TEXT,
  "budget" TEXT,
  "genres" TEXT,
  "homepage" TEXT,
  "id" TEXT,
  "imdb_id" TEXT,
  "original_language" TEXT,
  "original_title" TEXT,
  "overview" TEXT,
  "popularity" TEXT,
  "poster_path" TEXT,
  "production_companies" TEXT,
  "production_countries" TEXT,
  "release_date" TEXT,
  "revenue" REAL,
  "runtime" REAL,
  "spoken_languages" TEXT,
  "status" TEXT,
  "tagline" TEXT,
  "title" TEXT,
  "video" INTEGER,
  "vote_average" REAL,
  "vote_count" REAL
);
```

## ratings

```sql
CREATE TABLE "ratings" (
"userId" INTEGER,
  "movieId" INTEGER,
  "rating" REAL,
  "timestamp" INTEGER
);
```

## ratings_small

```sql
CREATE TABLE "ratings_small" (
"userId" INTEGER,
  "movieId" INTEGER,
  "rating" REAL,
  "timestamp" INTEGER
);
```

