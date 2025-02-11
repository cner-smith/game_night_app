# blueprints/game_night.py

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.models import db, GameNight, Player, Game, GameNightGame, Result, OwnedBy, GameNominations, GameVotes
from app.utils import admin_required, game_night_access_required, flash_if_no_action, determine_top_places
from sqlalchemy.orm import joinedload
from sqlalchemy import func, and_, case
from datetime import datetime

game_night_bp = Blueprint("game_night", __name__)

@game_night_bp.route("/game_night/start", methods=["GET", "POST"])
@login_required
@admin_required
@flash_if_no_action("Please provide the required data to start a game night.", "error")
def start_game_night():
    """Create a new game night."""
    if request.method == "POST":
        date_str = request.form.get("date")
        notes = request.form.get("notes")
        attendees_ids = request.form.getlist("attendees")

        try:
            date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            flash("Invalid date format. Please use YYYY-MM-DD.", "error")
            return redirect(url_for("game_night.start_game_night"))

        game_night = GameNight(date=date, notes=notes)
        db.session.add(game_night)
        db.session.commit()

        for person_id in attendees_ids:
            player = Player(game_night_id=game_night.id, people_id=person_id)
            db.session.add(player)
        db.session.commit()

        flash("Game night started successfully.", "success")
        return redirect(url_for("main.index"))

    people = Person.query.order_by(Person.first_name, Person.last_name).all()
    return render_template("start_game_night.html", people=people)


@game_night_bp.route("/game_night/<int:game_night_id>")
@login_required
@game_night_access_required
def view_game_night(game_night_id):
    """View the details of a specific game night."""
    game_night = GameNight.query.get_or_404(game_night_id)

    # Fetch and sort players alphabetically
    players = sorted(
        Player.query.filter_by(game_night_id=game_night.id)
        .options(joinedload(Player.person))  # Ensure `person` is loaded
        .all(),
        key=lambda p: (p.person.last_name, p.person.first_name)
    )

    # Fetch game night games with results
    game_night_games = (
        GameNightGame.query
        .filter_by(game_night_id=game_night.id)
        .options(joinedload(GameNightGame.results).joinedload(Result.player).joinedload(Player.person))
        .all()
    )

    # Sort results by position and score
    for game_night_game in game_night_games:
        game_night_game.results.sort(key=lambda r: (r.position, -(r.score or 0)))

    # Check if results are logged for any games
    results_logged = db.session.query(Result).filter(
        Result.game_night_game_id.in_([gng.id for gng in game_night.game_night_games])
    ).first() if game_night.game_night_games else None

    # Fetch the current user's player record for this game night
    current_player = Player.query.filter_by(game_night_id=game_night_id, people_id=current_user.id).first()

    # Fetch the user's game nomination
    user_nomination = None
    if current_player:
        user_nomination = GameNominations.query.filter_by(
            game_night_id=game_night_id,
            player_id=current_player.id
        ).first()

    # Fetch the user's votes
    user_votes = {}
    if current_player:
        user_votes_query = GameVotes.query.filter_by(
            game_night_id=game_night_id,
            player_id=current_player.id
        ).all()
        user_votes = {vote.game_id: vote.rank for vote in user_votes_query}

    # Query nominations with vote scores
    nominations_query = db.session.query(
        GameNominations,
        func.sum(
            case(
                (GameVotes.rank == 1, 3),  # Rank 1 contributes 3 points
                (GameVotes.rank == 2, 2),  # Rank 2 contributes 2 points
                (GameVotes.rank == 3, 1),  # Rank 3 contributes 1 point
                else_=0
            )
        ).label('vote_score')
    ).outerjoin(
        GameVotes,
        and_(
            GameNominations.game_id == GameVotes.game_id,
            GameVotes.game_night_id == game_night_id
        )
    ).filter(
        GameNominations.game_night_id == game_night_id
    ).group_by(
        GameNominations.id,  # Include non-aggregated fields in GROUP BY
        GameNominations.game_night_id,
        GameNominations.player_id,
        GameNominations.game_id
    ).all()

    # Query games that have votes but no nominations
    games_with_votes_query = db.session.query(
        GameVotes.game_id,
        func.sum(
            case(
                (GameVotes.rank == 1, 3),
                (GameVotes.rank == 2, 2),
                (GameVotes.rank == 3, 1),
                else_=0
            )
        ).label('vote_score')
    ).filter(
        GameVotes.game_night_id == game_night_id
    ).group_by(
        GameVotes.game_id
    ).all()

    # Merge nominations and games with votes, avoiding duplicates
    nominations_dict = {n.game_id: (n, score) for n, score in nominations_query}
    for game_id, vote_score in games_with_votes_query:
        if game_id not in nominations_dict:
            game = db.session.query(Game).filter_by(id=game_id).first()
            dummy_nomination = GameNominations(game_night_id=game_night_id, game=game)
            nominations_dict[game_id] = (dummy_nomination, vote_score)

    # Sort nominations by vote score (descending), then game name (alphabetically)
    nominations = sorted(
        nominations_dict.values(),
        key=lambda x: (-x[1], x[0].game.name)
    )

    # Determine top places if results are logged
    top_places = None
    if results_logged:
        raw_places = determine_top_places(game_night_id)
        top_places = [
            (place, [Player.query.get(player_id) for player_id in players if Player.query.get(player_id) is not None])
            for place, players in raw_places if players
        ][:3]

    # Get eligible games for nomination
    eligible_games = db.session.query(Game).join(
        OwnedBy, Game.id == OwnedBy.game_id
    ).filter(
        db.or_(
            OwnedBy.person_id == current_user.id,
            OwnedBy.person_id.in_([player.people_id for player in players])
        ),
        ~Game.id.in_({nomination.game_id for nomination, _ in nominations})
    ).order_by(Game.name).all()

    return render_template(
        "view_game_night.html",
        game_night=game_night,
        players=players,
        game_night_games=game_night_games,
        nominations=nominations,
        eligible_games=eligible_games,
        user_nomination=user_nomination,
        user_votes=user_votes,
        top_places=top_places,
    )

@game_night_bp.route("/game_night/<int:game_night_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_game_night(game_night_id):
    """Edit an existing game night."""
    game_night = GameNight.query.get_or_404(game_night_id)

    if request.method == "POST":
        date_str = request.form.get("date")
        notes = request.form.get("notes")
        attendees_ids = request.form.getlist("attendees")

        try:
            date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            flash("Invalid date format. Please use YYYY-MM-DD.", "error")
            return redirect(url_for("game_night.edit_game_night", game_night_id=game_night_id))

        game_night.date = date
        game_night.notes = notes
        db.session.commit()

        current_attendees = {p.people_id for p in game_night.players}
        new_attendees = set(map(int, attendees_ids))

        for person_id in new_attendees - current_attendees:
            db.session.add(Player(game_night_id=game_night.id, people_id=person_id))

        Player.query.filter(Player.game_night_id == game_night.id, Player.people_id.notin_(new_attendees)).delete()

        db.session.commit()
        flash("Game night updated successfully.", "success")
        return redirect(url_for("game_night.view_game_night", game_night_id=game_night_id))

    people = Person.query.order_by(Person.first_name, Person.last_name).all()
    current_attendees = {p.people_id for p in game_night.players}
    return render_template("edit_game_night.html", game_night=game_night, people=people, current_attendees=current_attendees)


@game_night_bp.route("/game_night/<int:game_night_id>/add_game", methods=["GET", "POST"])
@login_required
@admin_required
def add_game_to_night(game_night_id):
    """Add a game to a game night."""
    game_night = GameNight.query.get_or_404(game_night_id)

    if request.method == "POST":
        game_id = request.form.get("game_id")
        round_number = request.form.get("round")

        if not game_id or not round_number:
            flash("Please select a game and round number.", "error")
            return redirect(url_for("game_night.add_game_to_night", game_night_id=game_night_id))

        game_night_game = GameNightGame(game_night_id=game_night.id, game_id=game_id, round=int(round_number))
        db.session.add(game_night_game)
        db.session.commit()

        flash("Game added to game night.", "success")
        return redirect(url_for("game_night.view_game_night", game_night_id=game_night_id))

    games = Game.query.all()
    return render_template("add_game_to_night.html", game_night=game_night, games=games)


@game_night_bp.route("/game_night/<int:game_night_id>/remove_game/<int:game_id>", methods=["POST"])
@login_required
@admin_required
def remove_game_from_night(game_night_id, game_id):
    """Remove a game from a game night."""
    game_night_game = GameNightGame.query.filter_by(game_night_id=game_night_id, game_id=game_id).first()

    if game_night_game:
        db.session.delete(game_night_game)
        db.session.commit()
        flash("Game removed from game night.", "success")
    else:
        flash("Game not found in this game night.", "error")

    return redirect(url_for("game_night.view_game_night", game_night_id=game_night_id))


@game_night_bp.route("/game_night/<int:game_night_id>/log_results/<int:game_night_game_id>", methods=["GET", "POST"])
@login_required
@admin_required
def log_results(game_night_id, game_night_game_id):
    """Log results for a game night game."""
    game_night_game = GameNightGame.query.get_or_404(game_night_game_id)

    if request.method == "POST":
        for player in game_night_game.game_night.players:
            score = request.form.get(f"score_{player.id}")
            position = request.form.get(f"position_{player.id}")

            if score or position:
                result = Result.query.filter_by(game_night_game_id=game_night_game_id, player_id=player.id).first()
                if not result:
                    result = Result(game_night_game_id=game_night_game_id, player_id=player.id)
                    db.session.add(result)

                result.score = int(score) if score else None
                result.position = int(position) if position else None

        db.session.commit()
        flash("Results logged successfully.", "success")
        return redirect(url_for("game_night.view_game_night", game_night_id=game_night_id))

    players = game_night_game.game_night.players
    existing_results = {r.player_id: r for r in game_night_game.results}
    return render_template("log_results.html", game_night_game=game_night_game, players=players, existing_results=existing_results)

@game_night_bp.route('/game_night/<int:game_night_id>/toggle_results', methods=['POST'])
@login_required
@admin_required
def toggle_results(game_night_id):
    game_night = GameNight.query.get_or_404(game_night_id)
    if game_night.final:
        game_night.final = False
        flash('Results have been reopened.', 'success')
    else:
        game_night.final = True
        flash('Results have been finalized.', 'success')
    db.session.commit()
    return redirect(url_for('game_night.view_game_night', game_night_id=game_night_id))

@game_night_bp.route('/game_night/<int:game_night_id>/toggle_voting', methods=['POST'])
@login_required
@admin_required
def toggle_voting(game_night_id):
    game_night = GameNight.query.get_or_404(game_night_id)
    if game_night.closed:
        game_night.closed = False
        flash('Voting has been reopened.', 'success')
    else:
        game_night.closed = True
        flash('Voting has been closed.', 'success')
    db.session.commit()
    return redirect(url_for('game_night.view_game_night', game_night_id=game_night_id))