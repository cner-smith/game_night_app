# blueprints/voting.py

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.models import db, GameNight, Game, GameNominations, GameVotes, Player
from app.utils import game_night_access_required, flash_if_no_action

voting_bp = Blueprint("voting", __name__)

@voting_bp.route("/game_night/<int:game_night_id>/nominate", methods=["POST"])
@login_required
@game_night_access_required
def nominate_game(game_night_id):
    """Allows a player to nominate a game for an upcoming game night."""
    game_id = request.form.get("game_id")
    if not game_id:
        flash("You must select a game to nominate.", "error")
        return redirect(url_for("game_night.view_game_night", game_night_id=game_night_id))

    # Get the current player for this game night
    player = Player.query.filter_by(game_night_id=game_night_id, people_id=current_user.id).first()
    if not player:
        flash("You are not part of this game night.", "error")
        return redirect(url_for("game_night.view_game_night", game_night_id=game_night_id))

    # Check if the game is already nominated by another player
    existing_nomination = GameNominations.query.filter_by(game_night_id=game_night_id, game_id=game_id).first()
    if existing_nomination and existing_nomination.player_id != player.id:
        flash("This game has already been nominated by another player.", "error")
        return redirect(url_for("game_night.view_game_night", game_night_id=game_night_id))

    # Remove any votes the player has cast
    GameVotes.query.filter_by(game_night_id=game_night_id, player_id=player.id).delete()

    # Check if the player already has a nomination
    nomination = GameNominations.query.filter_by(game_night_id=game_night_id, player_id=player.id).first()

    if nomination:
        # Update the existing nomination
        nomination.game_id = game_id
        flash("Your nomination has been updated, and your votes have been cleared.", "success")
    else:
        # Create a new nomination
        new_nomination = GameNominations(game_night_id=game_night_id, player_id=player.id, game_id=game_id)
        db.session.add(new_nomination)
        flash("Your nomination has been submitted, and any previous votes have been cleared.", "success")

    db.session.commit()
    return redirect(url_for("game_night.view_game_night", game_night_id=game_night_id))


@voting_bp.route("/game_night/<int:game_night_id>/vote", methods=["POST"])
@login_required
@game_night_access_required
@flash_if_no_action("No votes were submitted. Please rank at least one game.", "error")
def vote_game(game_night_id):
    """Allows a player to vote for nominated games in a game night."""
    current_player = Player.query.filter_by(
        game_night_id=game_night_id, 
        people_id=current_user.id
    ).first()

    # Fetch and process votes
    votes_dict = {}
    for key, value in request.form.items():
        if key.startswith("votes[") and key.endswith("]"):
            game_id = int(key[6:-1])  # Extract game_id from 'votes[game_id]'
            if value.strip():  # If a rank is provided (not empty)
                try:
                    votes_dict[game_id] = int(value)
                except ValueError:
                    continue
            else:
                votes_dict[game_id] = None  # "No Vote" selected

    # Ensure no duplicate ranks
    used_ranks = set()
    for game_id, rank in votes_dict.items():
        if rank is not None:
            if rank in used_ranks:
                flash(f"Rank {rank} is already used for another game. Each rank can only be assigned once.", "error")
                return redirect(url_for("game_night.view_game_night", game_night_id=game_night_id))
            used_ranks.add(rank)

    # Process the votes
    for game_id, rank in votes_dict.items():
        existing_vote = GameVotes.query.filter_by(
            game_night_id=game_night_id,
            player_id=current_player.id,
            game_id=game_id
        ).first()

        if rank is None:  # "No Vote" selected: delete the vote if it exists
            if existing_vote:
                db.session.delete(existing_vote)
        else:  # Update or create the vote
            if existing_vote:
                existing_vote.rank = rank  # Update rank
            else:
                new_vote = GameVotes(
                    game_night_id=game_night_id,
                    player_id=current_player.id,
                    game_id=game_id,
                    rank=rank
                )
                db.session.add(new_vote)

    db.session.commit()
    flash("Your votes have been updated successfully.", "success")
    return redirect(url_for("game_night.view_game_night", game_night_id=game_night_id))
