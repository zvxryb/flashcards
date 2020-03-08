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

import codecs, logging, msvcrt, sys
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

LOG = logging.getLogger(__name__)

Box = Tuple[int, int, int, int]

from flashcards_lib.ansi_esc import *
from flashcards_lib.console_ui import (
    Input,
    MarkupDrawer,
    ASCII_ESC,
    MS_KEY_ESC0,
    MS_KEY_ESC1,
    MS_KEY_DOWN,
    MS_KEY_UP,
    MS_KEY_PAGE_DOWN,
    MS_KEY_PAGE_UP)

class EditorApp:
    class Card:
        __slots__ = 'card_id', 'front', 'back'

        card_id: Any

        def __init__(self, card_id, box_front, box_back):
            self.card_id = card_id
            self.front = MarkupDrawer(*box_front, True, True)
            self.back  = MarkupDrawer(*box_back , True, True)

        def get_side(self, front: bool) -> MarkupDrawer:
            return self.front if front else self.back

    selected: Optional[int]

    INPUT_BOX     = (26,  3, 3, 115)
    PREVIEW_FRONT = (20,  3, 5,  56)
    PREVIEW_BACK  = (20, 62, 5,  56)
    CARD_BROWSER  = (
        (( 2, 3, 5, 56), ( 2, 62, 5, 56)),
        (( 8, 3, 5, 56), ( 8, 62, 5, 56)),
        ((14, 3, 5, 56), (14, 62, 5, 56)),
    )

    def __init__(self, on_submit: Callable[[Any, str, str], None], on_scroll: Callable[[bool], None]):
        self.input      = Input(EditorApp.INPUT_BOX)
        self.preview    = EditorApp.Card(None, EditorApp.PREVIEW_FRONT, EditorApp.PREVIEW_BACK)
        self.edit_front = True
        self.browser    = [
            EditorApp.Card(None, box_front, box_back)
            for box_front, box_back in EditorApp.CARD_BROWSER]
        self.selected   = None
        self.on_submit  = on_submit
        self.on_scroll  = on_scroll

        sys.stdout.write(ANSI_CLEAR + ANSI_RESET)

        lib_path = Path(__file__).parent
        with codecs.open(lib_path / 'editor_ui_utf8.txt', 'r', 'utf-8') as f:
            sys.stdout.write(f.read())

        sys.stdout.write(ansi_pos(
            EditorApp.INPUT_BOX[0],
            EditorApp.INPUT_BOX[1]))
        sys.stdout.flush()

    def __del__(self):
        sys.stdout.write(ansi_col(0) + ANSI_DOWN * 4)
        sys.stdout.flush()

    @property
    def first_card_id(self) -> Any:
        return self.browser[0].card_id

    @property
    def last_card_id(self) -> Any:
        return self.browser[-1].card_id

    def set_browser_cards(self, cards: List[Tuple[Any, str, str]]):
        for i in range(len(self.browser)):
            try: 
                card_id, front, back = cards[i]
            except IndexError:
                card_id, front, back = None, '', ''
            self.browser[i].card_id    = card_id
            self.browser[i].front.text = front
            self.browser[i].back .text = back
        self.redraw_browser()

    def redraw_browser(self):
        for card in self.browser:
            card.front.redraw()
            card.back .redraw()

    def set_selected(self, selected: Optional[int]):
        if self.selected is not None:
            self.browser[self.selected].front.style = ''
            self.browser[self.selected].back .style = ''
            self.browser[self.selected].front.redraw()
            self.browser[self.selected].back .redraw()

        self.selected = selected

        if self.selected is not None:
            self.browser[self.selected].front.style = ANSI_REVERSE
            self.browser[self.selected].back .style = ANSI_REVERSE
            self.browser[self.selected].front.redraw()
            self.browser[self.selected].back .redraw()

    def select_card(self, up: bool):
        n = len(self.browser)
        if up:
            if self.selected is None:
                self.set_selected(n - 1)
            elif self.selected > 0:
                self.set_selected(self.selected - 1)
            else:
                self.set_selected(None)
        else:
            if self.selected is None:
                self.set_selected(0)
            elif self.selected < n - 1:
                self.set_selected(self.selected + 1)
            else:
                self.set_selected(None)

    def edit(self, card_id: Any, front: str, back: str):
        self.preview.card_id    = card_id
        self.preview.front.text = front
        self.preview.back .text = back
        self.preview.front.redraw()
        self.preview.back .redraw()
        self.edit_front = True
        self.input.text = front
        self.update_input()
        self.set_selected(None)

    def edit_selected(self):
        if self.selected is None:
            return

        self.edit(
            self.browser[self.selected].card_id,
            self.browser[self.selected].front.text,
            self.browser[self.selected].back .text)

    def update_input(self, text: Optional[str] = None):
        preview = self.preview.get_side(self.edit_front)
        if text is not None:
            preview.text = text
            preview.redraw()
        self.input.formatter.set_error_ranges(preview.error_ranges)
        self.input.redraw_input()

    def flip_card(self, update_input: bool):
        if update_input:
            self.preview.get_side(self.edit_front).text = self.input.text
        self.edit_front = not self.edit_front
        self.input.text = self.preview.get_side(self.edit_front).text

    def main(self) -> int:
        def on_timeout(text: str) -> bool:
            self.update_input(text)
            return False

        while True:
            if self.selected is None:
                preview = self.preview.get_side(self.edit_front)
                preview.style = ANSI_REVERSE
                preview.redraw()

                event_or_input = self.input.get_input(0.3, on_timeout)

                preview.style = ''
                preview.redraw()

                if isinstance(event_or_input, str):
                    LOG.debug('user input \"%s\"', event_or_input)
                    LOG.debug('\tpreview data \"%s\" \"%s\"',
                        self.preview.front.text,
                        self.preview.back .text)
                    self.update_input(event_or_input)
                    LOG.debug('\tpreview data \"%s\" \"%s\"',
                        self.preview.front.text,
                        self.preview.back .text)
                    if self.preview.front.text and self.preview.back.text:
                        card_id    = self.preview.card_id
                        front_text = self.preview.front.text
                        back_text  = self.preview.back .text
                        self.preview.card_id    = None
                        self.preview.front.text = ''
                        self.preview.back .text = ''
                        self.on_submit(card_id, front_text, back_text)
                        self.edit_front = True
                        self.preview.front.redraw()
                        self.preview.back .redraw()
                    else:
                        self.flip_card(False)
                elif event_or_input == Input.UNFOCUS:
                    return 0
                elif event_or_input == Input.KEY_UP:
                    self.select_card(True)
                elif event_or_input == Input.KEY_DOWN:
                    self.select_card(False)
                elif event_or_input == Input.PAGE_UP:
                    self.on_scroll(True)
                elif event_or_input == Input.PAGE_DOWN:
                    self.on_scroll(False)
                elif event_or_input == Input.TAB:
                    self.flip_card(True)
            else:
                char = msvcrt.getwch()
                if char == ASCII_ESC:
                    self.set_selected(None)
                elif char == '\x03' or char == '\x04':
                    raise KeyboardInterrupt()
                elif char == MS_KEY_ESC0 or char == MS_KEY_ESC1:
                    char2 = msvcrt.getwch()
                    if char2 == MS_KEY_UP or char2 == MS_KEY_DOWN:
                        self.select_card(char2 == MS_KEY_UP)
                    elif char2 == MS_KEY_PAGE_UP:
                        self.on_scroll(True)
                    elif char2 == MS_KEY_PAGE_DOWN:
                        self.on_scroll(False)
                elif char in (' ', '\r'):
                    self.edit_selected()
            sys.stdout.flush()

def example_main():
    log_handler = logging.FileHandler('console_ui.log', encoding='utf-8')
    log_handler.setLevel(logging.DEBUG)
    LOG.setLevel(logging.DEBUG)
    LOG.addHandler(log_handler)

    app: Optional[EditorApp] = None
    start_id = 0
    def on_scroll(scroll_up: bool):
        nonlocal start_id
        if scroll_up:
            start_id -= 1
        else:
            start_id += 1

        assert app is not None
        app.set_browser_cards([
            (start_id + i, f'card {start_id + i} front', f'card {start_id + i} back')
            for i in range(3)
        ])

    from console_ui import WinAnsiMode
    with WinAnsiMode():
        app = EditorApp(lambda id, front, back: None, on_scroll)
        app.main()

if __name__ == '__main__':
    example_main()