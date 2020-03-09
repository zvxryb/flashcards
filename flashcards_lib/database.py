# Copyright 2020 Michael Lodato <zvxryb@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import contextlib, os, sqlite3
from typing import Any, Dict, List, Optional, Tuple, Sequence

DB_SCHEMA = ('''
CREATE TABLE IF NOT EXISTS decks (
    id   INTEGER NOT NULL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
)''', '''
CREATE TABLE IF NOT EXISTS cards (
    id      INTEGER NOT NULL PRIMARY KEY,
    deck_id INTEGER NOT NULL,
    front   TEXT NOT NULL,
    back    TEXT NOT NULL,
    FOREIGN KEY(deck_id) REFERENCES decks(id)
)''', '''
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER NOT NULL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    counter INTEGER NOT NULL
)''', '''
CREATE TABLE IF NOT EXISTS session_decks (
    session_id INTEGER NOT NULL,
    deck_id    INTEGER NOT NULL,
    FOREIGN KEY(session_id) REFERENCES sessions(id),
    FOREIGN KEY(deck_id   ) REFERENCES decks   (id),
    UNIQUE(session_id, deck_id)
)''', '''
CREATE TABLE IF NOT EXISTS session_cards (
    session_id INTEGER NOT NULL,
    card_id    INTEGER NOT NULL,
    streak     INTEGER,
    review_at  INTEGER,
    FOREIGN KEY(session_id) REFERENCES sessions(id),
    FOREIGN KEY(card_id   ) REFERENCES cards   (id),
    UNIQUE(session_id, card_id)
)''', '''
CREATE TABLE IF NOT EXISTS macros (
    id         INTEGER NOT NULL PRIMARY KEY,
    name       TEXT    NOT NULL UNIQUE,
    definition TEXT    NOT NULL
)''')

class Cursor:
    __slots__ = 'cur'

    def __init__(self, cur: sqlite3.Cursor):
        self.cur = cur

    def __del__(self):
        self.close()

    def close(self):
        if self.cur:
            self.cur.close()
        self.cur = None

    def list_sessions(self):
        self.cur.execute('SELECT * FROM sessions')
        return self.cur.fetchall()

    def list_decks(self,
        session: Optional[int] = None
    ) -> List[Tuple[int, str]]:
        if session:
            self.cur.execute('''
                SELECT * FROM decks WHERE id IN
                    (SELECT deck_id FROM session_decks WHERE session_id=?)''',
                (session,))
        else:
            self.cur.execute('SELECT * FROM decks')
        return self.cur.fetchall()

    def list_cards(self,
        session_id: Optional[int] = None,
        deck_id: Optional[int] = None,
        contains_text: Optional[str] = None,
        before_id: Optional[int] = None,
        after_id: Optional[int] = None,
        limit: Optional[int] = None,
        get_tail: Optional[bool] = None
    ) -> List[Tuple[int, int, str, str]]:
        query = 'SELECT * FROM cards'
        ordering = 'ORDER BY id DESC' if get_tail else 'ORDER BY id ASC'
        where: List[str] = []
        args: Dict[str, Any] = {}
        if session_id is not None:
            where += ['(id IN (SELECT card_id FROM session_cards WHERE session_id=:session_id))']
            args = {**args, 'session_id': session_id}
        if deck_id is not None:
            where += ['(deck_id=:deck_id)']
            args = {**args, 'deck_id': deck_id}
        if contains_text is not None:
            where += ['(front LIKE :contains_text OR back LIKE :contains_text)']
            args = {**args, 'contains_text': '%'+contains_text+'%'}
        if before_id is not None:
            assert get_tail is None
            ordering = 'ORDER BY id DESC'
            where += ['(id < :before_id)']
            args = {**args, 'before_id': before_id}
        if after_id is not None:
            assert get_tail is None
            ordering = 'ORDER BY id ASC'
            where += ['(id > :after_id)']
            args = {**args, 'after_id': after_id}

        if where:
            query += ' WHERE ' + ' AND '.join(where)
        query += ' ' + ordering

        if limit is not None:
            query += ' LIMIT :limit'
            args = {**args, 'limit': limit}

        self.cur.execute(query, args)
        cards = self.cur.fetchall()
        cards.sort(key = lambda card: card[0])
        return cards

    def get_deck_id(self, name: str) -> int:
        self.cur.execute('SELECT id FROM decks WHERE name=?', (name,))
        deck = self.cur.fetchone()
        if not deck:
            raise Exception(f'no deck named {name} exists')
        return deck[0]

    def create_deck(self, name: str) -> int:
        self.cur.execute('INSERT INTO decks (name) VALUES (?)', (name,))
        return self.cur.lastrowid

    def get_card(self, card_id: int) -> Tuple[int, int, str, str]:
        self.cur.execute('SELECT * FROM cards WHERE id == ?', (card_id,))
        return self.cur.fetchone()

    def update_card(self, card_id: int, front: str, back: str):
        self.cur.execute(
            'UPDATE cards SET front=:front, back=:back WHERE id=:card_id',
            {'card_id': card_id, 'front': front, 'back': back})
        if self.cur.rowcount != 1:
            raise Exception('failed to update card')

    def add_card(self, deck_id: int, front: str, back: str) -> int:
        self.cur.execute(
            'INSERT INTO cards (deck_id, front, back) VALUES (?, ?, ?)',
            (deck_id, front, back))
        if self.cur.rowcount != 1:
            raise Exception('failed to create card')
        return self.cur.lastrowid

    def add_cards(self, deck: int, cards: Sequence[Tuple[str, str]]):
        self.cur.executemany(
            'INSERT INTO cards (deck_id, front, back) VALUES (?, ?, ?)',
            [(deck, front, back) for (front, back) in cards])
        if self.cur.rowcount != len(cards):
            raise Exception('failed to create card')

    def delete_card(self, card_id: int):
        self.cur.execute('DELETE FROM session_cards WHERE card_id=?', (card_id,))
        self.cur.execute('DELETE FROM cards WHERE id=?', (card_id,))
        if self.cur.rowcount != 1:
            raise Exception('failed to delete card')

    def get_session_id(self, name: str) -> int:
        self.cur.execute('SELECT id FROM sessions WHERE name=?', (name,))
        session = self.cur.fetchone()
        if not session:
            raise Exception(f'no session named {name} exists')
        return session[0]

    def create_session(self, name: str) -> int:
        self.cur.execute('INSERT INTO sessions (name, counter) VALUES (?, ?)', (name, 0))
        if self.cur.rowcount != 1:
            raise Exception('failed to create session')
        return self.cur.lastrowid

    def get_session_counter(self, session: int) -> int:
        self.cur.execute('SELECT counter FROM sessions WHERE id=?', (session,))
        return self.cur.fetchone()[0]

    def add_session_decks(self, session: int, decks: List[int]):
        self.cur.executemany(
            'INSERT INTO session_decks (session_id, deck_id) VALUES (?, ?)',
            [(session, deck) for deck in decks])
        if self.cur.rowcount != len(decks):
            raise Exception('failed to add decks to session')

    def get_session_decks(self, session_id: int) -> List[int]:
        self.cur.execute(
            'SELECT session_decks.deck_id FROM session_decks WHERE session_id=?',
            (session_id,))
        rows = self.cur.fetchall()
        if not rows:
            raise Exception('failed to get session decks')
        return [row[0] for row in rows]

    def cleanup_session_cards(self, session_id: int):
        self.cur.execute(
            '''DELETE FROM session_cards
                WHERE session_id=?
                AND NOT EXISTS (
                    SELECT 1
                        FROM cards
                        INNER JOIN session_decks ON
                            session_cards.card_id = cards.id AND
                            session_decks.deck_id = cards.deck_id AND
                            session_decks.session_id = session_cards.session_id
                )''',
            (session_id,))
        if self.cur.rowcount < 0:
            raise Exception('failed to cleanup session card info')

    def update_session_decks(self, session_id: int, deck_ids: List[int]):
        self.cur.execute(
            'DELETE FROM session_decks WHERE session_id=?',
            (session_id,))
        if self.cur.rowcount < 0:
            raise Exception('failed to remove decks from session')

        self.add_session_decks(session_id, deck_ids)
        self.cleanup_session_cards(session_id)

    def get_new_cards(self,
        session: int,
        limit: int
    ) -> List[Tuple[int, str, str, str]]:
        self.cur.execute('''
            SELECT cards.id, decks.name, cards.front, cards.back
                FROM cards
                LEFT JOIN decks ON
                    cards.deck_id == decks.id
                WHERE EXISTS (
                    SELECT 1 FROM session_decks
                        WHERE session_decks.session_id=:session
                        AND session_decks.deck_id=cards.deck_id
                ) AND NOT EXISTS (
                    SELECT 1 FROM session_cards
                        WHERE session_cards.session_id=:session
                        AND session_cards.card_id=cards.id
                )
                LIMIT :limit''',
            {'session': session, 'limit': limit})
        return self.cur.fetchall()

    def get_review_cards(self,
        session: int,
        limit: int
    ) -> List[Tuple[int, str, str, str, int]]:
        counter = self.get_session_counter(session)
        self.cur.execute(
            '''SELECT cards.id, decks.name, cards.front, cards.back, session_cards.streak
                FROM session_cards
                INNER JOIN cards ON
                    session_cards.session_id = :session
                    AND (
                        session_cards.review_at IS NULL OR
                        session_cards.review_at <= :counter)
                    AND session_cards.card_id = cards.id
                LEFT JOIN decks ON
                    cards.deck_id == decks.id
                ORDER BY session_cards.review_at ASC
                LIMIT :limit''',
            {'session': session, 'counter': counter, 'limit': limit})
        return self.cur.fetchall()

    def increment_session_counter(self, session: int):
        self.cur.execute('UPDATE sessions SET counter = counter + 1 WHERE id=?', (session,))

    def update_session_card(self, session: int, card: int, streak: int, review_at: int):
        self.cur.execute('''
            INSERT INTO session_cards
                (session_id, card_id, streak, review_at)
                VALUES (:session_id, :card_id, :streak, :review_at)
                ON CONFLICT(session_id, card_id) DO UPDATE SET
                    streak=:streak,
                    review_at=coalesce(:review_at, review_at)''',
            {'session_id': session, 'card_id': card, 'streak': streak, 'review_at': review_at})
        if self.cur.rowcount != 1:
            raise Exception('failed to update session card info')

    def get_macro(self, macro_id: int) -> Tuple[int, str, str]:
        self.cur.execute('SELECT * FROM macros WHERE id = ?', (macro_id,))
        if self.cur.rowcount != 1:
            raise Exception('failed to get macro')
        return self.cur.fetchone()

    def create_macro(self, name: str, definition: str) -> int:
        self.cur.execute(
            'INSERT INTO macros (name, definition) VALUES (?, ?)',
            (name, definition))
        if self.cur.rowcount != 1:
            raise Exception('failed to create macro')
        return self.cur.lastrowid

    def delete_macro(self, macro_id: int):
        self.cur.execute('DELETE FROM macros WHERE id = ?', (macro_id,))
        if self.cur.rowcount != 1:
            raise Exception('failed to delete macro')

    def list_macros(self) -> List[Tuple[int, str, str]]:
        self.cur.execute('SELECT * FROM macros')
        return self.cur.fetchall()

class Database:
    __slots__ = 'path', 'db', 'cur'

    def __init__(self, path: str):
        self.path = path
        self.db = sqlite3.connect(self.path, isolation_level=None)
        #self.db.set_trace_callback(print)
        with self.db:
            cur = self.db.cursor()
            cur.execute('BEGIN')
            for table in DB_SCHEMA:
                cur.execute(table)
            cur.close()

    def __del__(self):
        self.db.commit()
        self.db.close()

    def __enter__(self) -> Cursor:
        self.db.__enter__()
        cur = self.db.cursor()
        cur.execute('BEGIN')
        self.cur = Cursor(cur)
        return self.cur

    def __exit__(self, type_, value, tb):
        self.cur.close()
        self.cur = None
        self.db.__exit__(type_, value, tb)