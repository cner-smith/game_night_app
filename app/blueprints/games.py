# blueprints/games.py

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from app.models import db, Game, OwnedBy, Wishlist, Player, Result, GameNight, GameNightGame, GamesIndex
from app.utils import flash_if_no_action
from sqlalchemy import func
from fetch_bgg_data import fetch_game_details, parse_game_details

games_bp = Blueprint("games", __name__)

@games_bp.route("/games", methods=["GET"])
@login_required
def games_index():
    """Displays all available games, filtering by user ownership or player owners."""

    name_filter = request.args.get("name", "").strip()
    players_filter = request.args.get("players", type=int)
    playtime_filter = request.args.get("playtime", type=int)
    
    # Fetch games where the current user owns or an owner is assigned
    query = GamesIndex.query.filter(
        db.or_(
            GamesIndex.owner_id == current_user.id,
            GamesIndex.player_owner.is_(True)  # Check if the player is an owner
        )
    )

    # Apply optional filters
    if name_filter:
        query = query.filter(GamesIndex.game_name.ilike(f"%{name_filter}%"))
    if players_filter is not None:
        query = query.filter(
            GamesIndex.min_players <= players_filter,
            GamesIndex.max_players >= players_filter
        )
    if playtime_filter is not None:
        query = query.filter(GamesIndex.playtime <= playtime_filter)

    games = query.order_by(GamesIndex.game_name).all()

    # No need to compute ownership separately; the SQL view handles it
    games_with_ownership = [{"game": game, "user_owns_game": game.user_owns_game} for game in games]

    return render_template("games_index.html", games=games_with_ownership)

@games_bp.route("/game/add", methods=["GET", "POST"])
@login_required
def add_game():
    """Allows users to add a game manually or via BoardGameGeek API."""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        bgg_id = request.form.get("bgg_id", "").strip()

        try:
            bgg_id = int(bgg_id) if bgg_id else None
        except ValueError:
            flash("BGG ID must be an integer.", "error")
            return redirect(url_for("games.add_game"))

        default_name = "Unnamed Game"

        game_details = {
            "name": name or default_name,
            "description": None,
            "min_players": None,
            "max_players": None,
            "playtime": None,
            "image_url": None
        }

        if bgg_id:
            xml_data = fetch_game_details(bgg_id)
            if xml_data:
                try:
                    details = parse_game_details(xml_data)
                    game_details.update(details)
                    if not name:
                        name = details.get("name", default_name)
                except Exception as e:
                    flash(f"Failed to fetch details from BoardGameGeek: {e}", "error")
                    current_app.logger.error(f"Error fetching BGG details: {e}")

        game = None
        if bgg_id:
            game = Game.query.filter_by(bgg_id=bgg_id).first()
        if not game:
            game = Game.query.filter(func.lower(Game.name) == func.lower(name)).first()

        if game:
            flash(f'Game "{game.name}" already exists.', "info")
        else:
            game = Game(
                name=game_details["name"],
                bgg_id=bgg_id,
                description=game_details.get("description"),
                min_players=game_details.get("min_players"),
                max_players=game_details.get("max_players"),
                playtime=game_details.get("playtime"),
                image_url=game_details.get("image_url")
            )
            db.session.add(game)
            db.session.commit()
            flash(f'Game "{game.name}" added to the database.', "success")

        ownership = OwnedBy.query.filter_by(game_id=game.id, person_id=current_user.id).first()
        if not ownership:
            ownership = OwnedBy(game_id=game.id, person_id=current_user.id)
            db.session.add(ownership)
            db.session.commit()
            flash(f'Game "{game.name}" linked to your account.', "success")

        return redirect(url_for("games.add_game"))

    return render_template("add_game.html")


@games_bp.route("/game/<int:game_id>")
@login_required
def view_game(game_id):
    """Displays details of a specific game along with leaderboard and game nights."""
    game = Game.query.get_or_404(game_id)

    leaderboard = (
        db.session.query(Player, func.count(Result.id).label("wins"))
        .join(Result)
        .join(GameNightGame)
        .filter(GameNightGame.game_id == game_id, Result.position == 1)
        .group_by(Player.id)
        .order_by(func.count(Result.id).desc())
        .limit(3)
        .all()
    )

    game_nights = (
        GameNight.query
        .join(GameNightGame)
        .filter(GameNightGame.game_id == game_id)
        .order_by(GameNight.date.desc())
        .all()
    )

    return render_template("view_game.html", game=game, leaderboard=leaderboard, game_nights=game_nights)


@games_bp.route("/game/<int:game_id>/claim", methods=["POST"])
@login_required
def claim_game(game_id):
    """Allows a user to claim ownership of a game."""
    game = Game.query.get_or_404(game_id)

    ownership = OwnedBy.query.filter_by(game_id=game.id, person_id=current_user.id).first()
    if not ownership:
        ownership = OwnedBy(game_id=game.id, person_id=current_user.id)
        db.session.add(ownership)

        wishlist_entry = Wishlist.query.filter_by(game_id=game_id, person_id=current_user.id).first()
        if wishlist_entry:
            db.session.delete(wishlist_entry)

        db.session.commit()
        flash(f'You now own "{game.name}".', "success")
    else:
        flash(f"You already own {game.name}.", "info")

    return redirect(url_for("games.games_index"))


@games_bp.route("/game/<int:game_id>/remove_ownership", methods=["POST"])
@login_required
def remove_ownership(game_id):
    """Allows a user to remove a game from their owned list."""
    ownership = OwnedBy.query.filter_by(game_id=game_id, person_id=current_user.id).first()
    if ownership:
        db.session.delete(ownership)
        db.session.commit()
        flash("Game ownership removed.", "success")
    else:
        flash("You do not own this game.", "info")

    return redirect(url_for("games.games_index"))


@games_bp.route("/wishlist", methods=["GET"])
@login_required
def wishlist():
    """Displays the user's wishlist."""
    wishlist_games = (
        Game.query
        .join(Wishlist)
        .filter(Wishlist.person_id == current_user.id)
        .order_by(Game.name)
        .all()
    )

    return render_template("wishlist.html", games=wishlist_games)


@games_bp.route("/wishlist/add", methods=["GET", "POST"])
@login_required
def add_to_wishlist():
    """Adds a game to the user's wishlist."""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        bgg_id = request.form.get("bgg_id", "").strip()

        game = Game.query.filter(func.lower(Game.name) == func.lower(name)).first()
        if game:
            existing_entry = Wishlist.query.filter_by(game_id=game.id, person_id=current_user.id).first()
            if not existing_entry:
                wishlist_entry = Wishlist(game_id=game.id, person_id=current_user.id)
                db.session.add(wishlist_entry)
                db.session.commit()
                flash(f'Game "{game.name}" added to your wishlist.', "success")
            else:
                flash("Game is already in your wishlist.", "info")

        return redirect(url_for("games.wishlist"))

    return render_template("add_to_wishlist.html")


@games_bp.route("/wishlist/remove/<int:game_id>", methods=["POST"])
@login_required
def remove_from_wishlist(game_id):
    """Removes a game from the user's wishlist."""
    Wishlist.query.filter_by(game_id=game_id, person_id=current_user.id).delete()
    db.session.commit()
    flash("Game removed from your wishlist.", "success")

    return redirect(url_for("games.wishlist"))

@games_bp.route("/wishlist/claim_and_remove/<int:game_id>", methods=["POST"])
@login_required
def claim_and_remove(game_id):
    """Claims a game and removes it from the user's wishlist."""
    game = Game.query.get_or_404(game_id)
    
    ownership = OwnedBy.query.filter_by(game_id=game.id, person_id=current_user.id).first()
    if not ownership:
        new_ownership = OwnedBy(game_id=game.id, person_id=current_user.id)
        db.session.add(new_ownership)
        flash(f'You now own "{game.name}".', "success")
    
    wishlist_entry = Wishlist.query.filter_by(game_id=game.id, person_id=current_user.id).first()
    if wishlist_entry:
        db.session.delete(wishlist_entry)
        flash(f'"{game.name}" removed from your wishlist.', "success")
    
    db.session.commit()
    return redirect(url_for("games.wishlist"))