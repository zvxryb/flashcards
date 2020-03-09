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

import csv, json, logging, sys, unicodedata
from argparse import ArgumentParser
from itertools import zip_longest
from random import shuffle
from textwrap import TextWrapper
from typing import Any, Callable, Dict, List, Optional, Tuple, Sequence

from flashcards_lib.console_ui import WinAnsiMode
from flashcards_lib.editor_app import EditorApp
from flashcards_lib.practice_app import PracticeApp, QuestionResult, RESULT_PASS, RESULT_FAIL
from flashcards_lib.database import Database
from flashcards_lib.util import unicode_ljust
from flashcards_lib.markup import Macro

LOG = logging.getLogger(__name__)

try:
    input = raw_input # type: ignore
except NameError:
    pass

def once(f: Callable[..., Any]):
    called = False
    def g(*args, **kwargs):
        nonlocal called
        if not called:
            f(*args, **kwargs)
        else:
            LOG.debug('%s called more than once', f.__name__)
        called = True

@once
def load_macros(db: Database):
    with db as cur:
        macros = cur.list_macros()
    for macro_id, name, definition in macros:
        Macro.create(name, definition)

def print_table(cols: Sequence[Tuple[str, int]], rows: Sequence[Sequence[Any]]):
    cols_ = [(name, TextWrapper(width), width) for name, width in cols]
    print('╔═' + '═╤═'.join(['═' * width for _, _, width in cols_]) + '═╗')
    print('║ ' + ' │ '.join([name.ljust(width) for name, _, width in cols_]) + ' ║')
    for i, row in enumerate(rows):
        print('╟─' + '─┼─'.join(['─' * width for _, _, width in cols_]) + '─╢')
        cells = [wrapper.wrap(str(value)) for (_, wrapper, _), value in zip(cols_, row)]
        for line in zip_longest(*cells, fillvalue=''):
            print('║ ' + ' │ '.join([unicode_ljust(s, width) for s, (_, _, width) in zip(line, cols_)]) + ' ║')
    print('╚═' + '═╧═'.join(['═' * width for _, _, width in cols_]) + '═╝')

def cmd_list(
    db_path: str,
    list_type: str,
    session_name: Optional[str],
    deck_name: Optional[str],
    contains_text: Optional[str]
) -> int:
    cols: Tuple[Tuple[str, int], ...]
    with Database(db_path) as cur:
        if list_type == 'sessions':
            if session_name:
                sys.stderr.write('"--in-session" unsupported for "list sessions" queries\n')
                sys.stderr.flush()
                return -1
            if deck_name:
                sys.stderr.write('"--in-deck" unsupported for "list sessions" queries\n')
                sys.stderr.flush()
                return -1
            cols = ('id', 5), ('name', 80)
            rows = cur.list_sessions()
        elif list_type == 'decks':
            if deck_name:
                sys.stderr.write('"--in-deck" unsupported for "list decks" queries\n')
                sys.stderr.flush()
                return -1
            cols = ('id', 5), ('name', 80)
            rows = cur.list_decks(
                session=(cur.get_session_id(session_name) if session_name else None))
        elif list_type == 'cards':
            cols = ('id', 5), ('deck_id', 7), ('front', 40), ('back', 40)
            rows = cur.list_cards(
                session_id=(cur.get_session_id(session_name) if session_name else None),
                deck_id   =(cur.get_deck_id   (deck_name   ) if deck_name    else None),
                contains_text=contains_text)
        elif list_type == 'macros':
            cols = ('id', 5), ('name', 20), ('definition', 60)
            rows = cur.list_macros()
        else:
            return -1
    print_table(cols, rows)
    return 0

def cmd_modify(db_path: str, item_type: str, item_id: int) -> int:
    db = Database(db_path)

    if item_type == 'session':
        with db as cur:
            all_decks = cur.list_decks()
            old_decks = cur.get_session_decks(item_id)
        print_table((('id', 5), ('name', 80)), all_decks)
        old_decks_ = ",".join([str(deck_id) for deck_id in old_decks])

        while True:
            new_decks = input(f'Deck IDs (comma-delimited, i.e. "1, 2") [{old_decks_}]: ').split(',')
            if not new_decks:
                break
            try:
                new_decks = [int(deck_id.strip()) for deck_id in new_decks]
            except ValueError:
                print('failed to parse deck IDs')
            else:
                break

        if new_decks:
            with db as cur:
                cur.update_session_decks(item_id, new_decks)

    elif item_type == 'card':
        run_editor(db, card_id = item_id)

    return 0

def cmd_create(db_path: str, item_type: str) -> int:
    db = Database(db_path)

    if item_type == 'session':
        name = input('New session name: ')

        with db as cur:
            decks = cur.list_decks()
        print_table((('id', 5), ('name', 80)), decks)

        while True:
            deck_ids = input('Deck IDs (comma-delimited, i.e. "1, 2"): ').split(',')
            try:
                deck_ids = [int(deck_id.strip()) for deck_id in deck_ids]
            except ValueError:
                print('failed to parse deck IDs')
            else:
                break

        with db as cur:
            session_id = cur.create_session(name)
            cur.add_session_decks(session_id, deck_ids)

        deck_names = ",".join([f'"{deck[1]}"' for deck in decks if deck[0] in deck_ids])
        print(f'Created session "{name}" with decks {deck_names}')

    elif item_type == 'deck' or item_type == 'cards':
        name = input('Deck name: ')
        if item_type == 'deck':
            with db as cur:
                deck_id = cur.create_deck(name)
            print(f'Created deck "{name}"')
        else:
            with db as cur:
                deck_id = cur.get_deck_id(name)

        return run_editor(db, deck_id = deck_id)

    elif item_type == 'macro':
        name       = input('New macro name: ')
        definition = input('New macro definition: ')
        with db as cur:
            macro_id = cur.create_macro(name, definition)
        print(f'created macro {macro_id}: {name} => {definition}')

    return 0

def cmd_delete(db_path: str, item_type: str, item_id: int) -> int:
    db = Database(db_path)

    if item_type == 'card':
        with db as cur:
            cur.delete_card(item_id)
        print(f'Deleted card {item_id}')

    elif item_type == 'macro':
        with db as cur:
            cur.delete_macro(item_id)
        print(f'Deleted macro {item_id}')

    return 0

def cmd_import(db_path: str, deck_name: str, in_path: str, format: str) -> int:
    with open(in_path, 'r', encoding='utf-8') as f:
        if format == 'json':
            cards = json.load(f)
        elif format == 'csv':
            cards = [(card['front'], card['back']) for card in csv.DictReader(f)]

    db = Database(db_path)

    with db as cur:
        deck_id = cur.create_deck(deck_name)
        cur.add_cards(deck_id, cards)
    return 0

def cmd_export(db_path: str, deck_name: str, out_path: str, format: str) -> int:
    db = Database(db_path)

    with db as cur:
        deck_id = cur.get_deck_id(deck_name)
        cards = [(front, back) for _, _, front, back in cur.list_cards(deck_id=deck_id)]

    with open(out_path, 'w', encoding='utf-8') as f:
        if format == 'json':
            json.dump(cards, f, ensure_ascii=False, indent='\t')
        elif format == 'csv':
            writer = csv.DictWriter(f, ('front', 'back'))
            writer.writeheader()
            writer.writerows({'front': front, 'back': back} for front, back in cards)
    return 0

def run_editor(db: Database, deck_id: Optional[int] = None, card_id: Optional[int] = None) -> int:
    app: Optional[EditorApp] = None

    load_macros(db)

    def try_update_cards(scroll_up: bool, list_kwargs):
        nonlocal db, app
        assert app is not None

        with db as cur:
            cards = cur.list_cards(**list_kwargs)

        if not cards:
            return

        cards_: List[Tuple[Optional[int], str, str]] = [
            (card_id_, front, back)
            for card_id_, deck_id_, front, back in cards
        ]

        n = len(EditorApp.CARD_BROWSER)
        pad: List[Tuple[Optional[int], str, str]] = [(None, '', '')] * (n - len(cards))
        if scroll_up:
            cards_ = pad + cards_
        else:
            cards_ = cards_ + pad

        app.set_browser_cards(cards_)

    def scroll_to(card_id: int):
        nonlocal app, deck_id
        assert deck_id is not None

        n = len(EditorApp.CARD_BROWSER)

        try_update_cards(False, {
            'deck_id': deck_id,
            'before_id': card_id + 1,
            'limit': n,
        })

    def on_submit(card_id: Any, front: str, back: str):
        nonlocal deck_id
        assert deck_id is not None

        LOG.info('on_submit %s, %s, %s', card_id, front, back)

        with db as cur:
            if card_id is not None:
                assert isinstance(card_id, int)
                LOG.info('\tupdate existing card')
                cur.update_card(card_id, front, back)
            else:
                LOG.info('\tadd new card to %s', deck_id)
                card_id = cur.add_card(deck_id, front, back)

        scroll_to(card_id)

    def on_scroll(scroll_up: bool):
        nonlocal app, deck_id
        assert app is not None
        assert deck_id is not None

        n = len(EditorApp.CARD_BROWSER)

        list_kwargs: Dict[str, Any] = {
            'deck_id': deck_id,
            'limit': n,
        }

        if scroll_up:
            before_id = app.first_card_id
            if before_id is None:
                return
            assert isinstance(before_id, int)
            list_kwargs = {**list_kwargs, 'before_id': before_id}
        else:
            after_id = app.last_card_id
            if after_id is None:
                return
            assert isinstance(after_id, int)
            list_kwargs = {**list_kwargs, 'after_id': after_id}

        try_update_cards(scroll_up, list_kwargs)

    def main() -> int:
        nonlocal app, deck_id, card_id

        if card_id is not None:
            with db as cur:
                _, deck_id, front, back = cur.get_card(card_id)

        if deck_id is None:
            print('no deck ID or card ID given')
            return -1

        with WinAnsiMode():
            app = EditorApp(on_submit, on_scroll)
            if card_id is not None:
                scroll_to(card_id)
                app.edit(card_id, front, back)
            else:
                n = len(EditorApp.CARD_BROWSER)
                try_update_cards(False, {'limit': n, 'get_tail': True})
            return app.main()

    return main()

def cmd_start(db_path: str, session_name: str, round_cards: int) -> int:
    db = Database(db_path)

    load_macros(db)

    with db as cur:
        session_id = cur.get_session_id(session_name)

    app: Optional[PracticeApp] = None
    ready: List[Tuple[int, str, str, str, int]] = []
    current = None
    done: List[Tuple[int, int]] = []

    def next_question():
        nonlocal app, ready, current, done
        assert app is not None

        current = None

        if ready:
            current = ready.pop()
            card_id, deck_name, front, back, streak = current
            prefix = f'[{card_id}, {deck_name}] '
            app.update_question(prefix + front, len(done) + 1, len(ready) + len(done) + 1)
        elif done:
            app.update_question('Continue? [Y/N]', 0, 0)
        else:
            app.update_question('No cards to review.\n(Add more! :D)', 0, 0)

    def start_round():
        nonlocal app, ready, current, done
        assert app is not None

        ready   = []
        current = None
        done    = []

        app.clear_history()
        with db as cur:
            cur.increment_session_counter(session_id)
            review_cards = cur.get_review_cards(session_id, round_cards)
            new_cards = cur.get_new_cards(session_id, round_cards - len(review_cards))
        ready += [(card_id, deck_name, front, back, streak) for card_id, deck_name, front, back, streak in review_cards]
        ready += [(card_id, deck_name, front, back,      0) for card_id, deck_name, front, back         in new_cards   ]
        shuffle(ready)

        next_question()

    def normalize(s: str) -> str:
        return ' '.join(unicodedata.normalize('NFKD', s).lower().split())

    def update_card(card_id: int, streak: int, result: QuestionResult):
        with db as cur:
            if result == RESULT_PASS:
                streak += 1
                if streak > 31:
                    streak = 31
                counter = cur.get_session_counter(session_id)
                review_at = counter + 2**streak
            else:
                streak = 0
                review_at = None
            cur.update_session_card(session_id, card_id, streak, review_at)

    def on_submit(answer: str) -> bool:
        nonlocal app, ready, current, done
        assert app is not None

        if current:
            card_id, deck_name, front, back, streak = current
            done.append((card_id, streak))
            result = RESULT_PASS if normalize(back) == normalize(answer) else RESULT_FAIL
            app.push_history(card_id, result, front, back, answer)
            update_card(card_id, streak, result)
            next_question()
        elif answer.lower() in ('y', 'yes'):
            start_round()
        elif answer.lower() in ('n', 'no'):
            return False
        return True

    def on_revise(card_id: Any, result: QuestionResult):
        nonlocal app, ready, current, done
        assert app is not None

        assert isinstance(card_id, int)
        streak = next(streak for card_id_, streak in done if card_id_ == card_id)
        update_card(card_id, streak, result)

    with WinAnsiMode():
        app = PracticeApp(on_submit, on_revise)
        start_round()
        sys.stdout.flush()
        return app.main()

def main(argv: List[str]) -> int:
    log_handler = logging.FileHandler('main.log', encoding='utf-8')
    log_handler.setLevel(logging.DEBUG)
    ui_logger = logging.getLogger('console_ui')
    LOG.setLevel(logging.DEBUG)
    LOG.addHandler(log_handler)

    parse = ArgumentParser()
    parse.add_argument('--db', required=True)
    commands = parse.add_subparsers(dest='cmd')

    list_args   = commands.add_parser('list'  , help='list items')
    modify_args = commands.add_parser('modify', help='edit an item')
    create_args = commands.add_parser('create', help='create items')
    delete_args = commands.add_parser('delete', help='delete items')
    import_args = commands.add_parser('import', help='import a deck')
    export_args = commands.add_parser('export', help='export a deck')
    start_args  = commands.add_parser('start' , help='start a session')

    list_args.add_argument('type', choices=('sessions', 'decks', 'cards', 'macros'))
    list_args.add_argument('--in-session')
    list_args.add_argument('--in-deck')
    list_args.add_argument('--contains-text')

    modify_args.add_argument('type', choices=('card', 'session'))
    modify_args.add_argument('--id', required=True, type=int)
    modify_args.add_argument('--front')
    modify_args.add_argument('--back')

    create_args.add_argument('type', choices=('session', 'deck', 'cards', 'macro'))

    delete_args.add_argument('type', choices=('card', 'macro'))
    delete_args.add_argument('--id', required=True, type=int)

    import_args.add_argument('deck')
    import_args.add_argument('path')
    import_args.add_argument('--format', choices=('csv', 'json'), default='json')

    export_args.add_argument('deck')
    export_args.add_argument('path')
    export_args.add_argument('--format', choices=('csv', 'json'), default='json')

    start_args.add_argument('session')

    args = parse.parse_args(args=argv[1:])
    if args.cmd == 'list':
        return cmd_list(args.db, args.type, args.in_session, args.in_deck, args.contains_text)
    if args.cmd == 'modify':
        return cmd_modify(args.db, args.type, args.id)
    elif args.cmd == 'create':
        return cmd_create(args.db, args.type)
    elif args.cmd == 'delete':
        return cmd_delete(args.db, args.type, args.id)
    elif args.cmd == 'import':
        return cmd_import(args.db, args.deck, args.path, args.format)
    elif args.cmd == 'export':
        return cmd_export(args.db, args.deck, args.path, args.format)
    elif args.cmd == 'start':
        return cmd_start(args.db, args.session, 10)
    else:
        return -1
    return 0

if __name__ == '__main__':
    sys.exit(main(sys.argv))