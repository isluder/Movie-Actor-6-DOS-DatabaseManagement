"""
Flask Web Application for 'Film Reel-ational Data' (Database Management Project).

Implements the October 26th Milestone & Demo features:
- Multi-table relational search across Movies, Actors, Movie_Cast, and Genres
- Full CRUD operations: Add, Edit, and Delete Movies, Genres, and Cast roles
- 'Bombed at the Box Office' financial flop analyzer
- 'Hidden Gems' underrated film discovery engine
"""

import os
from flask import Flask, flash, redirect, render_template, request, url_for

import database as db
from ingest_data import DATA_DIR, run_ingestion

app = Flask(__name__)
app.secret_key = "film-reel-ational-data-secret-key"

# Ensure database exists and is populated on startup
if not os.path.exists(db.DB_PATH):
    run_ingestion(force_sample=False)
else:
    db.init_db()
    stats = db.get_dashboard_stats()
    if stats["movie_count"] == 0:
        run_ingestion(force_sample=False)


@app.template_filter("currency")
def currency_filter(value):
    """Format integer dollar amounts as $123,456,789."""
    try:
        val = int(value)
        if val < 0:
            return f"-${abs(val):,}"
        return f"${val:,}"
    except (ValueError, TypeError):
        return "$0"


@app.route("/")
def index():
    """Main dashboard & Multi-Table Search across Movies, Actors, Movie_Cast, and Genres."""
    title_query = request.args.get("title", "").strip()
    actor_query = request.args.get("actor", "").strip()
    character_query = request.args.get("character", "").strip()
    genre_id_raw = request.args.get("genre_id", "").strip()
    min_rating_raw = request.args.get("min_rating", "").strip()
    max_rating_raw = request.args.get("max_rating", "").strip()
    min_budget_raw = request.args.get("min_budget", "").strip()
    sort_by = request.args.get("sort_by", "vote_average_desc")

    genre_id = int(genre_id_raw) if genre_id_raw.isdigit() else None
    min_rating = float(min_rating_raw) if min_rating_raw else None
    max_rating = float(max_rating_raw) if max_rating_raw else None
    min_budget = int(min_budget_raw) if min_budget_raw.isdigit() else None

    movies, executed_sql = db.search_movies(
        title_query=title_query,
        actor_query=actor_query,
        character_query=character_query,
        genre_id=genre_id,
        min_rating=min_rating,
        max_rating=max_rating,
        min_budget=min_budget,
        sort_by=sort_by,
    )

    stats = db.get_dashboard_stats()
    genres = db.get_all_genres()

    return render_template(
        "index.html",
        movies=movies,
        stats=stats,
        genres=genres,
        executed_sql=executed_sql,
        filters={
            "title": title_query,
            "actor": actor_query,
            "character": character_query,
            "genre_id": genre_id,
            "min_rating": min_rating_raw,
            "max_rating": max_rating_raw,
            "min_budget": min_budget_raw,
            "sort_by": sort_by,
        },
    )


@app.route("/movie/<int:movie_id>")
def movie_detail(movie_id: int):
    """Display full movie details, cast list, genres, and edit/delete controls."""
    movie = db.get_movie_details(movie_id)
    if not movie:
        flash(f"Movie with ID {movie_id} was not found.", "error")
        return redirect(url_for("index"))

    all_genres = db.get_all_genres()
    all_actors = db.get_all_actors()
    return render_template(
        "movie_detail.html",
        movie=movie,
        all_genres=all_genres,
        all_actors=all_actors,
    )


@app.route("/movie/new", methods=["GET", "POST"])
def add_movie_route():
    """Create a new movie along with its genre associations and initial cast roles."""
    all_genres = db.get_all_genres()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        if not title:
            flash("Movie title is required.", "error")
            return redirect(url_for("add_movie_route"))

        try:
            budget = max(0, int(request.form.get("budget", 0) or 0))
            revenue = max(0, int(request.form.get("revenue", 0) or 0))
            vote_average = min(10.0, max(0.0, float(request.form.get("vote_average", 0.0) or 0.0)))
            vote_count = max(0, int(request.form.get("vote_count", 0) or 0))
        except ValueError:
            flash("Invalid numeric values for budget, revenue, or rating.", "error")
            return redirect(url_for("add_movie_route"))

        genre_ids = [int(g) for g in request.form.getlist("genre_ids") if g.isdigit()]

        actor_names = request.form.getlist("actor_name[]")
        character_names = request.form.getlist("character_name[]")
        cast_entries = list(zip(actor_names, character_names))

        try:
            new_id = db.add_movie(
                title=title,
                budget=budget,
                revenue=revenue,
                vote_average=vote_average,
                vote_count=vote_count,
                genre_ids=genre_ids,
                cast_entries=cast_entries,
            )
            flash(f"Successfully added '{title}' (ID: {new_id}) to the database!", "success")
            return redirect(url_for("movie_detail", movie_id=new_id))
        except Exception as e:
            flash(f"Database error while adding movie: {e}", "error")
            return redirect(url_for("add_movie_route"))

    return render_template("add_movie.html", all_genres=all_genres)


@app.route("/movie/<int:movie_id>/edit", methods=["POST"])
def edit_movie_route(movie_id: int):
    """Update movie attributes and genre links."""
    title = request.form.get("title", "").strip()
    if not title:
        flash("Movie title cannot be empty.", "error")
        return redirect(url_for("movie_detail", movie_id=movie_id))

    try:
        budget = max(0, int(request.form.get("budget", 0) or 0))
        revenue = max(0, int(request.form.get("revenue", 0) or 0))
        vote_average = min(10.0, max(0.0, float(request.form.get("vote_average", 0.0) or 0.0)))
        vote_count = max(0, int(request.form.get("vote_count", 0) or 0))
    except ValueError:
        flash("Invalid number format in movie edit form.", "error")
        return redirect(url_for("movie_detail", movie_id=movie_id))

    genre_ids = [int(g) for g in request.form.getlist("genre_ids") if g.isdigit()]

    try:
        updated = db.update_movie(
            movie_id=movie_id,
            title=title,
            budget=budget,
            revenue=revenue,
            vote_average=vote_average,
            vote_count=vote_count,
            genre_ids=genre_ids,
        )
        if updated:
            flash(f"Updated '{title}' successfully.", "success")
        else:
            flash("Movie not found.", "error")
    except Exception as e:
        flash(f"Failed to update movie: {e}", "error")

    return redirect(url_for("movie_detail", movie_id=movie_id))


@app.route("/movie/<int:movie_id>/delete", methods=["POST"])
def delete_movie_route(movie_id: int):
    """Delete a movie and cascade-delete its Movie_Cast and Genres records."""
    movie = db.get_movie_details(movie_id)
    title = movie["title"] if movie else f"ID {movie_id}"
    if db.delete_movie(movie_id):
        flash(
            f"Deleted '{title}' (and cascaded deletion to Movie_Cast and Genres).",
            "success",
        )
    else:
        flash("Movie could not be found to delete.", "error")
    return redirect(url_for("index"))


@app.route("/movie/<int:movie_id>/cast/add", methods=["POST"])
def add_cast_route(movie_id: int):
    """Add or update an actor's role in Movie_Cast for a movie."""
    actor_name = request.form.get("actor_name", "").strip()
    character_name = request.form.get("character_name", "").strip()
    if not actor_name:
        flash("Actor name is required to add a cast member.", "error")
    else:
        db.add_or_update_cast_member(movie_id, actor_name, character_name)
        flash(f"Added/updated {actor_name} as '{character_name or 'Uncredited'}'.", "success")
    return redirect(url_for("movie_detail", movie_id=movie_id))


@app.route("/movie/<int:movie_id>/cast/<int:actor_id>/remove", methods=["POST"])
def remove_cast_route(movie_id: int, actor_id: int):
    """Remove a cast member from a movie."""
    if db.remove_cast_member(movie_id, actor_id):
        flash("Removed cast member from movie.", "success")
    else:
        flash("Cast member entry was not found.", "error")
    return redirect(url_for("movie_detail", movie_id=movie_id))


@app.route("/bombs")
def box_office_bombs():
    """'Bombed at the Box Office' feature view."""
    min_budget_raw = request.args.get("min_budget", "10000000").strip()
    genre_id_raw = request.args.get("genre_id", "").strip()
    sort_by = request.args.get("sort_by", "net_loss_desc")

    min_budget = int(min_budget_raw) if min_budget_raw.isdigit() else 10_000_000
    genre_id = int(genre_id_raw) if genre_id_raw.isdigit() else None

    bombs, executed_sql = db.get_box_office_bombs(
        min_budget=min_budget,
        genre_id=genre_id,
        sort_by=sort_by,
    )
    genres = db.get_all_genres()

    total_losses = sum(b["net_loss"] for b in bombs)
    avg_roi = round(sum(b["roi_percent"] for b in bombs) / len(bombs), 1) if bombs else 0.0

    return render_template(
        "bombs.html",
        bombs=bombs,
        genres=genres,
        executed_sql=executed_sql,
        total_losses=total_losses,
        avg_roi=avg_roi,
        filters={
            "min_budget": min_budget,
            "genre_id": genre_id,
            "sort_by": sort_by,
        },
    )


@app.route("/hidden-gems")
def hidden_gems():
    """'Hidden Gems' feature view."""
    min_rating_raw = request.args.get("min_rating", "7.4").strip()
    min_votes_raw = request.args.get("min_votes", "50").strip()
    max_votes_raw = request.args.get("max_votes", "4500").strip()
    max_budget_raw = request.args.get("max_budget", "35000000").strip()
    genre_id_raw = request.args.get("genre_id", "").strip()
    sort_by = request.args.get("sort_by", "gem_score_desc")

    try:
        min_rating = float(min_rating_raw)
    except ValueError:
        min_rating = 7.4

    min_votes = int(min_votes_raw) if min_votes_raw.isdigit() else 50
    max_votes = int(max_votes_raw) if max_votes_raw.isdigit() else 4500
    max_budget = int(max_budget_raw) if max_budget_raw.isdigit() else None
    genre_id = int(genre_id_raw) if genre_id_raw.isdigit() else None

    gems, executed_sql = db.get_hidden_gems(
        min_rating=min_rating,
        min_votes=min_votes,
        max_votes=max_votes,
        max_budget=max_budget,
        genre_id=genre_id,
        sort_by=sort_by,
    )
    genres = db.get_all_genres()

    return render_template(
        "hidden_gems.html",
        gems=gems,
        genres=genres,
        executed_sql=executed_sql,
        filters={
            "min_rating": min_rating,
            "min_votes": min_votes,
            "max_votes": max_votes,
            "max_budget": max_budget_raw,
            "genre_id": genre_id,
            "sort_by": sort_by,
        },
    )


@app.route("/reload-data", methods=["POST"])
def reload_data_route():
    """Allow re-seeding sample data or ingesting CSVs from ./data via the UI."""
    mode = request.form.get("mode", "auto")
    counts = run_ingestion(data_dir=DATA_DIR, force_sample=(mode == "sample"))
    flash(
        f"Database reloaded: {counts['movies']} movies, {counts['actors']} actors, "
        f"{counts['cast_links']} cast roles, and {counts['genres']} genre links.",
        "success",
    )
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
