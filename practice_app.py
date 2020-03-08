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
from typing import Any, Callable, Optional, Tuple, Union

LOG = logging.getLogger(__name__)

Box = Tuple[int, int, int, int]

from ansi_esc import *
from console_ui import (
    Formatter,
    Input,
    ASCII_ESC,
    MS_KEY_ESC0,
    MS_KEY_ESC1,
    MS_KEY_DOWN,
    MS_KEY_UP)

class QuestionResult:
    __slots__ = ()

RESULT_PASS = QuestionResult()
RESULT_FAIL = QuestionResult()

class HistoryData:
    __slots__ = 'id', 'modified', 'result', 'question', 'expected', 'answered'

    def __init__(self,
        id: Any = None,
        result: Optional[QuestionResult] = None,
        question: str = '',
        expected: str = '',
        answered: str = ''
    ):
        self.id       = id
        self.modified = False
        self.result   = result
        self.question = question
        self.expected = expected
        self.answered = answered

class HistoryForm:
    __slots__ = 'result', 'question', 'expected', 'answered'

    def __init__(self,
        result  : Box,
        question: Box,
        expected: Box,
        answered: Box
    ):
        self.result   = Formatter(*result  , False, False)
        self.question = Formatter(*question, False, False)
        self.expected = Formatter(*expected, False, False)
        self.answered = Formatter(*answered, False, False)

    def update_result(self, result: Optional[QuestionResult], highlight: bool):
        if result is None:
            self.result.style = ''
            self.result.text  = 'Question'
        elif result == RESULT_PASS:
            self.result.style = ANSI_GREEN
            self.result.text  = u'\u2713 Right'
        elif result == RESULT_FAIL:
            self.result.style = ANSI_RED
            self.result.text  = u'\u2717 Wrong'

        if highlight:
            self.result.style += ANSI_REVERSE

        self.result.redraw()

    def update_question(self, text: str):
        self.question.text = text
        self.question.redraw()

    def update_expected(self, text: str):
        self.expected.text = text
        self.expected.redraw()

    def update_answered(self, text: str):
        self.answered.text = text
        self.answered.redraw()

    def update(self, data: HistoryData, highlight: bool):
        self.update_result(data.result, highlight)
        self.update_question((f'{data.id}: ' + data.question) if data.question else '')
        self.update_expected(data.expected)
        self.update_answered(data.answered)

HISTORY_FORMS = (
    HistoryForm((16, 3, 1, 9), (16, 14, 2, 104), (18, 14, 2, 104), (20, 14, 2, 104)),
    HistoryForm(( 9, 3, 1, 9), ( 9, 14, 2, 104), (11, 14, 2, 104), (13, 14, 2, 104)),
    HistoryForm(( 2, 3, 1, 9), ( 2, 14, 2, 104), ( 4, 14, 2, 104), ( 6, 14, 2, 104)))

QUESTION_BOX = (23, 3, 3, 115)
NUMBER_BOX   = (22, 3, 1,   2)
TOTAL_BOX    = (22, 6, 1,   2)
ANSWER_BOX   = (27, 3, 2, 115)

class PracticeApp:
    selected: Optional[int]

    def __init__(self, on_submit: Callable[[str], bool], on_revise: Callable[[Any, QuestionResult], None]):
        self.answer    = Input(ANSWER_BOX)
        self.history   = [HistoryData() for _ in HISTORY_FORMS]
        self.question_formatter = Formatter(*QUESTION_BOX, True , True )
        self.selected  = None
        self.on_submit = on_submit
        self.on_revise = on_revise

        sys.stdout.write(ANSI_CLEAR + ANSI_RESET)

        with codecs.open('practice_ui_utf8.txt', 'r', 'utf-8') as f:
            sys.stdout.write(f.read())

        sys.stdout.write(ansi_pos(ANSWER_BOX[0], ANSWER_BOX[1]))
        sys.stdout.flush()

    def __del__(self):
        sys.stdout.write(ansi_col(0) + ANSI_DOWN * 3)
        sys.stdout.flush()

    def redraw_history(self):
        for i, (form, data) in enumerate(zip(HISTORY_FORMS, self.history)):
            form.update(data, i == self.selected)

    def clear_history(self):
        self.history = [HistoryData() for _ in HISTORY_FORMS]
        self.redraw_history()

    def push_history(self, id: Any, result: QuestionResult, question: str, expected: str, answered: str):
        item = HistoryData(id, result, question, expected, answered)
        self.history = [item] + self.history[:len(HISTORY_FORMS)-1]
        self.redraw_history()

    def update_question(self, question: str, number: Union[int, str], total: Union[int, str]):
        number = str(number)
        if len(number) > NUMBER_BOX[3]:
            number = '#' * NUMBER_BOX[3]
        else:
            number = number.rjust(NUMBER_BOX[3])

        total = str(total)
        if len(total) > TOTAL_BOX[3]:
            total = '#' * TOTAL_BOX[3]
        else:
            total = total.rjust(TOTAL_BOX[3])

        sys.stdout.write(
            ANSI_SAVE +
            ansi_pos(NUMBER_BOX[0], NUMBER_BOX[1]) + number +
            ansi_pos(TOTAL_BOX [0], TOTAL_BOX [1]) + total  +
            ANSI_RESTORE)

        self.question_formatter.text = question
        self.question_formatter.redraw()

    def set_selected(self, selected: Optional[int]):
        if self.selected is not None:
            history_data = self.history[self.selected]
            if history_data.modified:
                history_data.modified = False
                assert history_data.result is not None
                self.on_revise(history_data.id, history_data.result)
            HISTORY_FORMS[self.selected].update_result(history_data.result, False)

        self.selected = selected

        if self.selected is not None:
            history_data = self.history[self.selected]
            HISTORY_FORMS[self.selected].update_result(history_data.result, True)

    def select_item(self, up: bool):
        n = len(HISTORY_FORMS)
        if up:
            if self.selected is None:
                self.set_selected(0)
            elif self.selected < n - 1:
                self.set_selected(self.selected + 1)
            else:
                self.set_selected(None)
        else:
            if self.selected is None:
                self.set_selected(n - 1)
            elif self.selected > 0:
                self.set_selected(self.selected - 1)
            else:
                self.set_selected(None)

    def toggle_item(self):
        if self.selected is None:
            return
        history_data = self.history[self.selected]
        if history_data.result is None:
            return
        if history_data.result == RESULT_PASS:
            history_data.result = RESULT_FAIL
        else:
            history_data.result = RESULT_PASS
        history_data.modified = True
        HISTORY_FORMS[self.selected].update_result(history_data.result, True)

    def main(self) -> int:
        while True:
            if self.selected is None:
                event_or_input = self.answer.get_input()
                if isinstance(event_or_input, str):
                    if not self.on_submit(event_or_input):
                        return 0
                elif event_or_input == Input.UNFOCUS:
                    return 0
                elif event_or_input == Input.KEY_UP:
                    self.select_item(True)
                elif event_or_input == Input.KEY_DOWN:
                    self.select_item(False)
            else:
                char = msvcrt.getwch()
                if char == ASCII_ESC:
                    self.set_selected(None)
                elif char == '\x03' or char == '\x04':
                    raise KeyboardInterrupt()
                elif char == MS_KEY_ESC0 or char == MS_KEY_ESC1:
                    char2 = msvcrt.getwch()
                    if char2 == MS_KEY_UP or char2 == MS_KEY_DOWN:
                        self.select_item(char2 == MS_KEY_UP)
                elif char == ' ':
                    self.toggle_item()
                    self.set_selected(None)
            sys.stdout.flush()