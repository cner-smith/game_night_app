Accessable through https://gamenight.sgammill.com

---

## Database Schema (DBML)

```dbml
Table gamenights {
  id integer [pk, increment]
  date date [not null]
  notes text
  created_at timestamp [default: `CURRENT_TIMESTAMP`]
  final boolean [default: false]
  closed boolean [default: false]
}

Table people {
  id integer [pk, increment]
  created_at timestamp [default: `CURRENT_TIMESTAMP`]
  first_name varchar [not null]
  last_name varchar [not null]
  email varchar [unique]
  password varchar
  temp_pass boolean [default: false]
  admin boolean [not null, default: false]
  owner boolean [not null, default: false]
}

Table games {
  id integer [pk, increment]
  name varchar(255) [not null]
  bgg_id integer
  min_players integer
  max_players integer
  playtime integer
  description text
  image_url varchar(255)
  tutorial_url varchar(255)
}

Table players {
  id integer [pk, increment]
  game_night_id integer [ref: > gamenights.id]
  people_id integer [ref: > people.id]
  created_at timestamp [default: `CURRENT_TIMESTAMP`]
}

Table gamenightgames {
  id integer [pk, increment]
  game_night_id integer [ref: > gamenights.id]
  game_id integer [ref: > games.id]
  round integer
  created_at timestamp [default: `CURRENT_TIMESTAMP`]
}

Table results {
  id integer [pk, increment]
  game_night_game_id integer [ref: > gamenightgames.id]
  player_id integer [ref: > players.id]
  score integer
  position integer
  created_at timestamp [default: `CURRENT_TIMESTAMP`]
}

Table game_nominations {
  id integer [pk, increment]
  game_night_id integer [ref: > gamenights.id]
  player_id integer [ref: > players.id]
  game_id integer [ref: > games.id]
}

Table game_votes {
  id integer [pk, increment]
  game_night_id integer [ref: > gamenights.id]
  player_id integer [ref: > players.id]
  game_id integer [ref: > games.id]
  rank integer [note: 'check: 1, 2, or 3']
}

Table game_Ratings {
  id integer [pk, increment]
  game_id integer [ref: > games.id]
  person_id integer [ref: > people.id]
  ranking integer
}

Table ownedby {
  id integer [pk, increment]
  game_id integer [ref: > games.id]
  person_id integer [ref: > people.id]
}

Table wishlist {
  id integer [pk, increment]
  person_id integer [ref: > people.id]
  game_id integer [ref: > games.id]

  indexes {
    (person_id, game_id) [unique]
  }
}

Table game_full_ownership {
  game_id integer [pk, increment]
  game_name varchar [not null]
  image_url varchar
  min_players integer [not null]
  max_players integer [not null]
  playtime integer
  owner_id integer [ref: > people.id]
  player_owner boolean
  user_owns_game boolean [not null]
}
```

---

## Views

### `admin_game_nights_list`
Lists all game nights with a generated sequential row number as `id`.

```sql
CREATE VIEW public.admin_game_nights_list AS
SELECT row_number() OVER () AS id,
    id AS game_night_id,
    date,
    notes,
    final,
    closed
FROM public.gamenights gn;
```

---

### `admin_recent_future_game_nights`
Shows all upcoming game nights plus the 3 most recent past game nights. Dates are converted from UTC to America/Chicago timezone. No user filter — admin view.

```sql
CREATE VIEW public.admin_recent_future_game_nights AS
WITH user_game_nights AS (
    SELECT DISTINCT gn.id AS game_night_id,
        ((gn.date AT TIME ZONE 'UTC') AT TIME ZONE 'America/Chicago') AS date,
        gn.notes,
        gn.final,
        gn.closed
    FROM public.gamenights gn
), past_game_nights AS (
    SELECT ugn.game_night_id, ugn.date, ugn.notes, ugn.final, ugn.closed
    FROM user_game_nights ugn
    WHERE ugn.date < ((CURRENT_DATE AT TIME ZONE 'UTC') AT TIME ZONE 'America/Chicago')
    ORDER BY ugn.date DESC
    LIMIT 3
)
SELECT game_night_id, date, notes, final, closed
FROM (
    SELECT ugn.game_night_id, ugn.date, ugn.notes, ugn.final, ugn.closed
    FROM user_game_nights ugn
    WHERE ugn.date >= ((CURRENT_DATE AT TIME ZONE 'UTC') AT TIME ZONE 'America/Chicago')
    UNION ALL
    SELECT past.game_night_id, past.date, past.notes, past.final, past.closed
    FROM past_game_nights past
) combined
ORDER BY date DESC;
```

---

### `earliest_game_night`
Returns a single row with the earliest game night date ever recorded.

```sql
CREATE VIEW public.earliest_game_night AS
SELECT min(date) AS earliest_date
FROM public.gamenights;
```

---

### `game_night_game_results`
Per game played in a game night, aggregates all player results into a JSON array ordered by position/score. Empty results return `[]` rather than null.

```sql
CREATE VIEW public.game_night_game_results AS
SELECT
    gng.id AS game_night_game_id,
    gng.game_night_id,
    gng.game_id,
    gng.round,
    g.name AS game_name,
    g.image_url AS game_image_url,
    COALESCE(
        json_agg(
            json_build_object(
                'player_id', r.player_id,
                'first_name', p.first_name,
                'last_name', p.last_name,
                'position', r.position,
                'score', r.score
            ) ORDER BY r.position, r.score DESC
        ) FILTER (WHERE r.id IS NOT NULL),
        '[]'::json
    ) AS results
FROM public.gamenightgames gng
LEFT JOIN public.results r ON gng.id = r.game_night_game_id
LEFT JOIN public.games g ON gng.game_id = g.id
LEFT JOIN public.players pl ON r.player_id = pl.id
LEFT JOIN public.people p ON pl.people_id = p.id
GROUP BY gng.id, gng.game_night_id, gng.game_id, g.name, g.image_url
ORDER BY gng.id;
```

---

### `game_night_nominations_votes`
Aggregates nominations and weighted vote scores per game per game night. Vote scoring: rank 1 = 3pts, rank 2 = 2pts, rank 3 = 1pt.

```sql
CREATE VIEW public.game_night_nominations_votes AS
SELECT
    gn.id AS game_night_id,
    g.id AS game_id,
    g.name AS game_name,
    g.image_url,
    count(DISTINCT gnm.id) AS total_nominations,
    COALESCE(sum(
        CASE
            WHEN gv.rank = 1 THEN 3
            WHEN gv.rank = 2 THEN 2
            WHEN gv.rank = 3 THEN 1
            ELSE 0
        END
    ), 0) AS vote_score
FROM public.gamenights gn
LEFT JOIN (
    SELECT DISTINCT game_id, game_night_id FROM public.game_nominations
    UNION
    SELECT DISTINCT game_id, game_night_id FROM public.game_votes
) included_games ON included_games.game_night_id = gn.id
JOIN public.games g ON included_games.game_id = g.id
LEFT JOIN public.game_nominations gnm ON gnm.game_id = g.id AND gnm.game_night_id = gn.id
LEFT JOIN public.game_votes gv ON gv.game_id = g.id AND gv.game_night_id = gn.id
GROUP BY gn.id, g.id, g.name, g.image_url
ORDER BY gn.id DESC, vote_score DESC, total_nominations DESC;
```

---

### `game_night_participants*`
Lists all players and their personal info for each game night.

```sql
CREATE VIEW public."game_night_participants*" AS
SELECT
    gn.id AS game_night_id,
    p.id AS player_id,
    pe.first_name AS player_first_name,
    pe.last_name AS player_last_name,
    pe.email AS player_email
FROM public.gamenights gn
LEFT JOIN public.players p ON p.game_night_id = gn.id
LEFT JOIN public.people pe ON p.people_id = pe.id
ORDER BY gn.id, pe.last_name, pe.first_name;
```

---

### `game_night_players*`
Lists all players across all game nights with their associated person info.

```sql
CREATE VIEW public."game_night_players*" AS
SELECT
    p.id AS player_id,
    p.game_night_id,
    pe.first_name,
    pe.last_name,
    pe.email
FROM public.players p
JOIN public.people pe ON p.people_id = pe.id
ORDER BY pe.last_name, pe.first_name;
```

---

### `game_night_rankings_view`
Ranks players within each game night by finish positions across all games played that night. Position counts are stored as an array `[1st, 2nd, 3rd, 4th]` and sorted DESC, with total score as tiebreaker.

```sql
CREATE VIEW public.game_night_rankings_view AS
WITH positions AS (
    SELECT unnest(ARRAY[1, 2, 3, 4]) AS position
), players_in_games AS (
    SELECT DISTINCT gng.game_night_id, r.player_id
    FROM public.gamenightgames gng
    JOIN public.results r ON r.game_night_game_id = gng.id
), ranked_players AS (
    SELECT
        pig.game_night_id,
        pig.player_id,
        pos.position,
        count(r.id) AS count,
        sum(COALESCE(r.score, 0)) AS total_score
    FROM players_in_games pig
    CROSS JOIN positions pos
    LEFT JOIN public.results r ON
        r.player_id = pig.player_id
        AND r.position = pos.position
        AND r.game_night_game_id IN (
            SELECT id FROM public.gamenightgames
            WHERE game_night_id = pig.game_night_id
        )
    GROUP BY pig.game_night_id, pig.player_id, pos.position
), aggregated_scores AS (
    SELECT
        game_night_id,
        player_id,
        array_agg(count ORDER BY position) AS position_counts,
        sum(total_score) AS overall_score
    FROM ranked_players
    GROUP BY game_night_id, player_id
), ranked AS (
    SELECT
        game_night_id,
        player_id,
        position_counts,
        overall_score,
        dense_rank() OVER (
            PARTITION BY game_night_id
            ORDER BY position_counts DESC, overall_score DESC
        ) AS rank
    FROM aggregated_scores
)
SELECT
    row_number() OVER () AS id,
    game_night_id,
    player_id,
    position_counts,
    overall_score,
    rank
FROM ranked;
```

---

### `game_night_summary*`
One row per game night with aggregate stats and the name of the overall winner (player with a position=1 result).

```sql
CREATE VIEW public."game_night_summary*" AS
SELECT
    gn.id AS game_night_id,
    gn.date AS game_night_date,
    gn.notes AS game_night_notes,
    count(DISTINCT p.id) AS player_count,
    count(DISTINCT gng.id) AS game_count,
    concat(pe.first_name, ' ', pe.last_name) AS winner_name
FROM public.gamenights gn
LEFT JOIN public.players p ON gn.id = p.game_night_id
LEFT JOIN public.gamenightgames gng ON gn.id = gng.game_night_id
LEFT JOIN public.results r ON gng.id = r.game_night_game_id AND r.position = 1
LEFT JOIN public.players rp ON r.player_id = rp.id
LEFT JOIN public.people pe ON rp.people_id = pe.id
GROUP BY gn.id, gn.date, gn.notes, pe.first_name, pe.last_name
ORDER BY gn.date DESC;
```

---

### `games_index`
Lists all games with ownership info. May return multiple rows per game if multiple people own it.

```sql
CREATE VIEW public.games_index AS
SELECT
    g.id AS game_id,
    g.name AS game_name,
    g.image_url,
    g.min_players,
    g.max_players,
    g.playtime,
    ob.person_id AS owner_id,
    pe.owner AS player_owner,
    CASE
        WHEN ob.person_id IS NOT NULL THEN true
        ELSE false
    END AS user_owns_game
FROM public.games g
LEFT JOIN public.ownedby ob ON g.id = ob.game_id
LEFT JOIN public.people pe ON pe.id = ob.person_id;
```

---

### `user_game_nights_list`
Lists all game nights with the associated `user_id` (people_id from players). Used as the base for user-scoped views. Returns 0 for user_id when no player record exists.

```sql
CREATE VIEW public.user_game_nights_list AS
SELECT
    row_number() OVER () AS id,
    gn.id AS game_night_id,
    gn.date,
    gn.notes,
    gn.final,
    gn.closed,
    COALESCE(p.people_id, 0) AS user_id
FROM public.gamenights gn
LEFT JOIN public.players p ON p.game_night_id = gn.id;
```

---

### `user_recent_future_game_nights`
Per-user version of the recent/future game nights view. Shows all upcoming nights plus the 3 most recent past nights **per user**. Dates converted to America/Chicago timezone.

```sql
CREATE VIEW public.user_recent_future_game_nights AS
WITH user_game_nights AS (
    SELECT DISTINCT
        gn.game_night_id,
        ((gn.date AT TIME ZONE 'UTC') AT TIME ZONE 'America/Chicago') AS date,
        gn.notes,
        gn.final,
        gn.closed,
        gn.user_id
    FROM public.user_game_nights_list gn
), past_game_nights AS (
    SELECT
        ugn.game_night_id, ugn.date, ugn.notes, ugn.final, ugn.closed, ugn.user_id,
        row_number() OVER (PARTITION BY ugn.user_id ORDER BY ugn.date DESC) AS row_num
    FROM user_game_nights ugn
    WHERE ugn.date < ((CURRENT_DATE AT TIME ZONE 'UTC') AT TIME ZONE 'America/Chicago')
)
SELECT
    row_number() OVER () AS id,
    game_night_id, date, notes, final, closed, user_id
FROM (
    SELECT ugn.game_night_id, ugn.date, ugn.notes, ugn.final, ugn.closed, ugn.user_id
    FROM user_game_nights ugn
    WHERE ugn.date >= ((CURRENT_DATE AT TIME ZONE 'UTC') AT TIME ZONE 'America/Chicago')
    UNION ALL
    SELECT past.game_night_id, past.date, past.notes, past.final, past.closed, past.user_id
    FROM past_game_nights past
    WHERE past.row_num <= 3
) combined
ORDER BY date DESC;
```
