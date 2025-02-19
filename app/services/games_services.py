from app.models import db, Game, OwnedBy, Wishlist, Player, Result, GameNight, GameNightGame, GamesIndex
from sqlalchemy import func
from fetch_bgg_data import fetch_game_details, parse_game_details

def get_filtered_games(user_id, name_filter, players_filter, playtime_filter):
    """Retrieve filtered games based on user preferences."""
    query = GamesIndex.query.filter(
        db.or_(GamesIndex.owner_id == user_id, GamesIndex.player_owner.is_(True))
    )
    
    if name_filter:
        query = query.filter(GamesIndex.game_name.ilike(f"%{name_filter}%"))
    if players_filter is not None:
        query = query.filter(GamesIndex.min_players <= players_filter, GamesIndex.max_players >= players_filter)
    if playtime_filter is not None:
        query = query.filter(GamesIndex.playtime <= playtime_filter)
    
    games = query.order_by(GamesIndex.game_name).all()
    return [{"game": game, "user_owns_game": game.user_owns_game} for game in games]

def add_game(user_id, name, bgg_id):
    """Add a game manually or fetch details from BoardGameGeek."""
    try:
        bgg_id = int(bgg_id) if bgg_id else None
    except ValueError:
        return False, "BGG ID must be an integer."
    
    game = None
    if bgg_id:
        game = Game.query.filter_by(bgg_id=bgg_id).first()
    if not game:
        game = Game.query.filter(func.lower(Game.name) == func.lower(name)).first()
    
    if game:
        return False, f'Game "{game.name}" already exists.'
    
    game_details = {
        "name": name or "Unnamed Game",
        "description": None,
        "min_players": None,
        "max_players": None,
        "playtime": None,
        "image_url": None
    }
    
    if bgg_id:
        xml_data = fetch_game_details(bgg_id)
        if xml_data:
            details = parse_game_details(xml_data)
            game_details.update(details)
            if not name:
                name = details.get("name", "Unnamed Game")
    
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
    
    ownership = OwnedBy.query.filter_by(game_id=game.id, person_id=user_id).first()
    if not ownership:
        ownership = OwnedBy(game_id=game.id, person_id=user_id)
        db.session.add(ownership)
        db.session.commit()
    
    return True, f'Game "{game.name}" added and linked to your account.'

def get_game_details(game_id):
    """Retrieve details of a game, including leaderboard and game nights."""
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
    game_nights = GameNight.query.join(GameNightGame).filter(GameNightGame.game_id == game_id).order_by(GameNight.date.desc()).all()
    return game, leaderboard, game_nights

def claim_game(user_id, game_id):
    """Allows a user to claim ownership of a game."""
    game = Game.query.get_or_404(game_id)
    ownership = OwnedBy.query.filter_by(game_id=game.id, person_id=user_id).first()
    
    if not ownership:
        ownership = OwnedBy(game_id=game.id, person_id=user_id)
        db.session.add(ownership)
        
        wishlist_entry = Wishlist.query.filter_by(game_id=game_id, person_id=user_id).first()
        if wishlist_entry:
            db.session.delete(wishlist_entry)
        
        db.session.commit()
        return True, f'You now own "{game.name}".'
    
    return False, f'You already own {game.name}.'

def remove_ownership(user_id, game_id):
    """Allows a user to remove a game from their owned list."""
    ownership = OwnedBy.query.filter_by(game_id=game_id, person_id=user_id).first()
    if ownership:
        db.session.delete(ownership)
        db.session.commit()
        return True, "Game ownership removed."
    return False, "You do not own this game."

def get_wishlist(user_id):
    """Displays the user's wishlist."""
    return Game.query.join(Wishlist).filter(Wishlist.person_id == user_id).order_by(Game.name).all()

def add_to_wishlist(user_id, name, bgg_id):
    """Adds a game to the user's wishlist."""
    game = Game.query.filter(func.lower(Game.name) == func.lower(name)).first()
    if game:
        existing_entry = Wishlist.query.filter_by(game_id=game.id, person_id=user_id).first()
        if not existing_entry:
            wishlist_entry = Wishlist(game_id=game.id, person_id=user_id)
            db.session.add(wishlist_entry)
            db.session.commit()
            return True, f'Game "{game.name}" added to your wishlist.'
        return False, "Game is already in your wishlist."
    return False, "Game not found."

def remove_from_wishlist(user_id, game_id):
    """Removes a game from the user's wishlist."""
    Wishlist.query.filter_by(game_id=game_id, person_id=user_id).delete()
    db.session.commit()
    return True, "Game removed from your wishlist."

def claim_and_remove(user_id, game_id):
    """Claims a game and removes it from the user's wishlist."""
    game = Game.query.get_or_404(game_id)
    ownership = OwnedBy.query.filter_by(game_id=game.id, person_id=user_id).first()
    if not ownership:
        new_ownership = OwnedBy(game_id=game.id, person_id=user_id)
        db.session.add(new_ownership)
    
    wishlist_entry = Wishlist.query.filter_by(game_id=game.id, person_id=user_id).first()
    if wishlist_entry:
        db.session.delete(wishlist_entry)
    
    db.session.commit()
    return True, f'You now own "{game.name}" and it has been removed from your wishlist.'