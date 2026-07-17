"""Player repository -- not yet implemented.

The vision calls for full player profiles (career, style, advanced
metrics, injuries, market value, contracts, similar players). None of
that is available from football-data.org's free tier, so this needs a
richer provider (e.g. FBref/Understat, Opta, or a paid API) before it
can be built. Kept as an explicit stub so the future architecture's
shape is visible in the codebase rather than absent from it.
"""


class PlayerRepository:
    def get_profile(self, player_id):
        raise NotImplementedError("Player data provider not yet integrated")

    def find_similar(self, player_id, limit=5):
        raise NotImplementedError("Player data provider not yet integrated")
