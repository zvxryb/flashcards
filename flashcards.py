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

import csv, json, os, sys, unicodedata
from argparse import ArgumentParser
from itertools import zip_longest
from random import shuffle
from textwrap import TextWrapper

from console_ui import WinAnsiMode, Display, RESULT_PASS, RESULT_FAIL
from database import Database
from util import unicode_ljust

try:
    input = raw_input
except NameError:
    pass

def print_table(cols, rows):
    cols = [(name, TextWrapper(width), width) for name, width in cols]
    print('╔═' + '═╤═'.join(['═' * width for _, _, width in cols]) + '═╗')
    print('║ ' + ' │ '.join([name.ljust(width) for name, _, width in cols]) + ' ║')
    for i, row in enumerate(rows):
        print('╟─' + '─┼─'.join(['─' * width for _, _, width in cols]) + '─╢')
        cells = [wrapper.wrap(str(value)) for (_, wrapper, _), value in zip(cols, row)]
        for line in zip_longest(*cells, fillvalue=''):
            print('║ ' + ' │ '.join([unicode_ljust(s, width) for s, (_, _, width) in zip(line, cols)]) + ' ║')
    print('╚═' + '═╧═'.join(['═' * width for _, _, width in cols]) + '═╝')

def cmd_list(db_path, list_type, session_name, deck_name):
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
                session=(cur.get_session_id(session_name) if session_name else None),
                deck   =(cur.get_deck_id   (deck_name   ) if deck_name    else None))
        else:
            return -1
    print_table(cols, rows)
    return 0

def cmd_create(db_path, item_type):
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

    elif item_type == 'deck':
        name = input('New deck name: ')
        with db as cur:
            deck_id = cur.create_deck(name)
        print(f'Created deck "{name}"')

        while True:
            front = input('Card front: ')
            if not front:
                break

            back  = input('Card back : ')
            if not back:
                break

            with db as cur:
                cur.add_cards(deck_id, ((front, back),))

            print(f'Added card "{front}", "{back}"')

def cmd_import(db_path, deck_name, in_path, format):
    with open(in_path, 'r', encoding='utf-8') as f:
        if format == 'json':
            cards = json.load(f)
        elif format == 'csv':
            cards = [(card['front'], card['back']) for card in csv.DictReader(f)]

    db = Database(db_path)

    with db as cur:
        deck_id = cur.create_deck(deck_name)
        cur.add_cards(deck_id, cards)

def cmd_export(db_path, deck_name, out_path, format):
    db = Database(db_path)

    with db as cur:
        deck_id = cur.get_deck_id(deck_name)
        cards = [(front, back) for _, _, front, back in cur.list_cards(deck=deck_id)]

    with open(out_path, 'w', encoding='utf-8') as f:
        if format == 'json':
            json.dump(cards, f, ensure_ascii=False, indent='\t')
        elif format == 'csv':
            writer = csv.DictWriter(f, ('front', 'back'))
            writer.writeheader()
            writer.writerows({'front': front, 'back': back} for front, back in cards)

def cmd_start(db_path, session_name, round_cards):
    db = Database(db_path)
    with db as cur:
        session_id = cur.get_session_id(session_name)

    display = None
    ready   = []
    current = None
    done    = []

    def next_question():
        nonlocal display, ready, current, done

        current = None

        if ready:
            current = ready.pop()
            card_id, front, back, streak = current
            display.update_question(front, len(done) + 1, len(ready) + len(done) + 1)
        elif done:
            display.update_question('Continue? [Y/N]', 0, 0)
        else:
            display.update_question('No cards to review.\n(Add more! :D)', 0, 0)

    def start_round():
        nonlocal display, ready, current, done

        ready   = []
        current = None
        done    = []

        display.clear_history()
        with db as cur:
            cur.increment_session_counter(session_id)
            review_cards = cur.get_review_cards(session_id, round_cards)
            new_cards = cur.get_new_cards(session_id, round_cards - len(review_cards))
        ready += [(card_id, front, back, streak) for card_id, front, back, streak, _ in review_cards]
        ready += [(card_id, front, back,      0) for card_id, front, back            in new_cards   ]
        shuffle(ready)

        next_question()

    def normalize(s):
        return ' '.join(unicodedata.normalize('NFKD', s).lower().split())

    def update_card(card_id, streak, result):
        with db as cur:
            if result == RESULT_PASS:
                streak += 1
                if streak > 31:
                    streak = 31
                counter = cur.get_session_counter(session_id)
                review_at = counter + 2**streak
            else:
                streak = 0
                review_at = 0
            cur.update_session_card(session_id, card_id, streak, review_at)

    def on_submit(answer):
        nonlocal display, ready, current, done
        if current:
            card_id, front, back, streak = current
            done.append((card_id, streak))
            result = RESULT_PASS if normalize(back) == normalize(answer) else RESULT_FAIL
            display.push_history(card_id, result, front, back, answer)
            update_card(card_id, streak, result)
            next_question()
        elif answer.lower() in ('y', 'yes'):
            start_round()
        elif answer.lower() in ('n', 'no'):
            return False
        return True

    def on_revise(card_id, result):
        nonlocal display, ready, current, done
        streak = next(streak for card_id_, streak in done if card_id_ == card_id)
        update_card(card_id, streak, result)

    with WinAnsiMode():
        display = Display(on_submit, on_revise)
        start_round()
        sys.stdout.flush()
        display.main()

def main(argv):
    parse = ArgumentParser()
    parse.add_argument('--db', required=True)
    commands = parse.add_subparsers(dest='cmd')

    list_args   = commands.add_parser('list'  , help='list items')
    create_args = commands.add_parser('create', help='create items')
    import_args = commands.add_parser('import', help='import a deck')
    export_args = commands.add_parser('export', help='export a deck')
    start_args  = commands.add_parser('start' , help='start a session')

    list_args.add_argument('type', choices=('sessions', 'decks', 'cards'))
    list_args.add_argument('--in-session')
    list_args.add_argument('--in-deck')

    create_args.add_argument('type', choices=('session', 'deck'))

    import_args.add_argument('deck')
    import_args.add_argument('path')
    import_args.add_argument('--format', choices=('csv', 'json'), default='json')

    export_args.add_argument('deck')
    export_args.add_argument('path')
    export_args.add_argument('--format', choices=('csv', 'json'), default='json')

    start_args.add_argument('session')

    args = parse.parse_args(args=argv[1:])
    if args.cmd == 'list':
        return cmd_list(args.db, args.type, args.in_session, args.in_deck)
    elif args.cmd == 'create':
        return cmd_create(args.db, args.type)
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