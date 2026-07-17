"""Conversation memory: session-scoped chat history.

Not wired to any route yet -- there's no LLM in the loop today -- but
the vision's "AI is the interface" goal needs a place to remember
context across turns, so this exists as ready-to-use scaffolding for
that future chat endpoint.
"""


class ConversationMemory:
    def __init__(self):
        self._sessions = {}

    def add_message(self, session_id, role, content):
        self._sessions.setdefault(session_id, []).append({"role": role, "content": content})

    def history(self, session_id):
        return list(self._sessions.get(session_id, []))

    def clear(self, session_id):
        self._sessions.pop(session_id, None)
