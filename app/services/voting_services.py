from app.models import db, GameNominations, GameVotes, Player, GameNight, Game, OwnedBy, GameNightNominationsVotes

def nominate_game(game_night_id, user_id, game_id):
    """Handles nomination of a game for an upcoming game night."""
    current_player = Player.query.filter_by(game_night_id=game_night_id, people_id=user_id).first()

    if not current_player:
        return False, "User is not a player in this game night."

    player_id = current_player.id

    if not game_id:
        return False, "You must select a game to nominate."
    
    existing_nomination = GameNominations.query.filter_by(game_night_id=game_night_id, game_id=game_id).first()
    if existing_nomination and existing_nomination.player_id != player_id:
        return False, "This game has already been nominated by another player."
    
    GameVotes.query.filter_by(game_night_id=game_night_id, player_id=player_id).delete()
    nomination = GameNominations.query.filter_by(game_night_id=game_night_id, player_id=player_id).first()
    
    if nomination:
        nomination.game_id = game_id
        message = "Your nomination has been updated, and your votes have been cleared."
    else:
        new_nomination = GameNominations(game_night_id=game_night_id, player_id=player_id, game_id=game_id)
        db.session.add(new_nomination)
        message = "Your nomination has been submitted, and any previous votes have been cleared."
    
    db.session.commit()
    return True, message

def vote_game(game_night_id, user_id, votes_dict):
    """Handles voting for nominated games in a game night."""
    current_player = Player.query.filter_by(game_night_id=game_night_id, people_id=user_id).first()

    if not current_player:
        return False, "User is not a player in this game night."

    player_id = current_player.id

    used_ranks = set()
    for game_id, rank in votes_dict.items():
        if rank is not None:
            if rank in used_ranks:
                return False, f"Rank {rank} is already used for another game. Each rank can only be assigned once."
            used_ranks.add(rank)
    
    for game_id, rank in votes_dict.items():
        existing_vote = GameVotes.query.filter_by(
            game_night_id=game_night_id,
            player_id=player_id,
            game_id=game_id
        ).first()
        
        if rank is None:
            if existing_vote:
                db.session.delete(existing_vote)
        else:
            if existing_vote:
                existing_vote.rank = rank
            else:
                new_vote = GameVotes(
                    game_night_id=game_night_id,
                    player_id=player_id,
                    game_id=game_id,
                    rank=rank
                )
                db.session.add(new_vote)
    
    db.session.commit()
    return True, "Your votes have been updated successfully."

def get_nominate_game_page_context(game_night_id, current_user_id):
    """Fetch all data needed to render the nominate a game page."""

    game_night = GameNight.query.get_or_404(game_night_id)

    # Eligible games
    eligible_games = get_eligible_games_for_nomination(game_night_id)

    # User's existing nomination
    current_player = Player.query.filter_by(game_night_id=game_night_id, people_id=current_user_id).first()
    user_nomination_id = None
    if current_player:
        nomination = GameNominations.query.filter_by(game_night_id=game_night_id, player_id=current_player.id).first()
        if nomination:
            user_nomination_id = nomination.game_id

    return {
        "eligible_games": eligible_games,
        "game_night": game_night,
        "user_nomination_id": user_nomination_id,
    }

def get_eligible_games_for_nomination(game_night_id):
    """Fetch games user can nominate."""
    game_night = GameNight.query.get_or_404(game_night_id)
    player_ids = [player.people_id for player in game_night.players]

    nominated_game_ids = {
        n.game_id for n in GameNightNominationsVotes.query.filter_by(game_night_id=game_night_id).all()
    }

    eligible_games = db.session.query(Game).join(OwnedBy).filter(
        OwnedBy.person_id.in_(player_ids),
        ~Game.id.in_(nominated_game_ids)
    ).order_by(Game.name).all()

    return eligible_games
