from __future__ import annotations

import logging, sys, threading, unicodedata
from functools import reduce
from typing import Any, Callable, Dict, Generator, Iterator, List, Optional, Tuple, Union

from ansi_esc import *
from console_ui import WinAnsiMode
from util import is_breaking_space, is_inner_punctuation, is_starting_punctuation, is_ending_punctuation, line_break_opportunities, StringMask, unicode_width, unicode_center

LOG = logging.getLogger(__name__)

def token_boundaries(s: str) -> StringMask:
    cats = [unicodedata.category(c) for c in s]
    delim = StringMask.collect(
        c in ('\\', '{', '}', '^', '_') or
        is_breaking_space(c, cat) or
        is_inner_punctuation(cat) or
        is_starting_punctuation(cat) or
        is_ending_punctuation(cat)
        for c, cat in zip(s, cats))
    return line_break_opportunities(s) | delim | delim << 1

class Token:
    __slots__ = '_type', '_range', '_value'

    class Type:
        __slots__ = 'ident',

        def __init__(self, ident: str):
            self.ident = ident

        def __str__(self) -> str:
            return self.ident

    LITERAL  = Type('literal')
    ESCAPE   = Type('escape')
    SPACE    = Type('whitespace')
    INFIX    = Type('infix')
    FUNCTION = Type('function')
    LBRACKET = Type('lbracket')
    RBRACKET = Type('rbracket')

    def __init__(self, type_: Type, range_: Optional[Tuple[int, int]], value: str):
        self._type  = type_
        self._range = range_
        self._value = value

    @property
    def type(self) -> Type:
        return self._type

    @property
    def range(self) -> Optional[Tuple[int, int]]:
        return self._range

    @property
    def value(self) -> str:
        return self._value

    def with_type(self, type_: Type) -> Token:
        return Token(type_, self._range, self._value)

    def __repr__(self) -> str:
        return f'Token{{{str(self.type)}, {self.range}, \"{self.value}\"}}'

def tokenize(s: str) -> Generator[Token, None, None]:
    breaks = token_boundaries(s)
    i = 0
    j = 0
    while j < len(s):
        if breaks[j]:
            yield Token(Token.LITERAL, (i, j), s[i:j+1])
            i = j+1
        j = j+1
    if i < len(s):
        yield Token(Token.LITERAL, (i, j), s[i:])

def normalize(tokens: Iterator[Token]) -> Generator[Token, None, None]:
    t0: Optional[Token] = None

    VALUE_LIKE = (Token.LITERAL, Token.FUNCTION, Token.RBRACKET)

    while True:
        try:
            t1 = next(tokens)
        except StopIteration:
            break

        if t0 and t0.type == Token.ESCAPE:
            if t1.value in Function.LOOKUP:
                t1 = t1.with_type(Token.FUNCTION)
            t0 = t1
        elif t1.value == '\\':
            t1 = t1.with_type(Token.ESCAPE)
            if t0:
                yield t0
            t0 = t1
        elif t1.value in InfixOperator.LOOKUP:
            t1 = t1.with_type(Token.INFIX)
            if not t0 or t0.type not in VALUE_LIKE:
                yield Token(Token.LITERAL, None, '')
            if t0:
                yield t0
            t0 = t1
        elif t1.value == '{':
            t1 = t1.with_type(Token.LBRACKET)
            if t0:
                yield t0
                if t0.type in VALUE_LIKE:
                    yield Token(Token.SPACE, None, '')
            t0 = t1
        elif t1.value == '}':
            t1 = t1.with_type(Token.RBRACKET)
            if t0:
                yield t0
                if t0.type not in VALUE_LIKE:
                    yield Token(Token.LITERAL, None, '')
            t0 = t1
        elif all(is_breaking_space(c) for c in t1.value):
            if t0 and t0.type == Token.SPACE:
                assert t0.range and t1.range
                t0 = Token(Token.SPACE,
                    (
                        min(t0.range[0], t1.range[0]),
                        max(t0.range[1], t1.range[1])
                    ),
                    t0.value + t1.value)
            else:
                if t0 and t0.type in VALUE_LIKE:
                    t1 = t1.with_type(Token.SPACE)
                else:
                    t1 = t1.with_type(Token.LITERAL)
                if t0:
                    yield t0
                t0 = t1
        else:
            t1 = t1.with_type(Token.LITERAL)
            if t0:
                yield t0
                if t0.type in VALUE_LIKE:
                    yield Token(Token.SPACE, None, '')
            t0 = t1

    if t0:
        if t0.type not in VALUE_LIKE:
            yield t0
            yield Token(Token.LITERAL, None, '')
        else:
            yield t0

class Text:
    __slots__ = '_x', '_y', '_text'

    def __init__(self, x: int, y: int, text: str):
        self._x = x
        self._y = y
        self._text = text

    def __repr__(self) -> str:
        return f'Text{{{self.x}, {self.y}, \"{self.text}\"}}'

    @property
    def x(self) -> int:
        return self._x

    @property
    def y(self) -> int:
        return self._y

    @property
    def text(self) -> str:
        return self._text

    def with_text(self, text: str) -> Text:
        return Text(self._x, self._y, text)

    def clone(self) -> Text:
        return Text(self._x, self._y, self._text)

    @staticmethod
    def from_str(text: str) -> Text:
        return Text(0, 0, text)

class TextBox:
    __slots__ = '_width', '_height', '_baseline'

    def __init__(self, width: int, height: int, baseline: int):
        self._width    = width
        self._height   = height
        self._baseline = baseline

    def __repr__(self) -> str:
        return f'TextBox{{{self.width}x{self.height}, {self.baseline}}}'

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    @property
    def baseline(self) -> int:
        return self._baseline

    def clone(self) -> TextBox:
        return TextBox(self._width, self._height, self._baseline)

    @staticmethod
    def from_str(text: str) -> TextBox:
        return TextBox(unicode_width(text), 1, 0)

    @staticmethod
    def empty() -> TextBox:
        return TextBox(0, 0, 0)

class TextGroup:
    __slots__ = '_box', '_items'

    def __init__(self, box: TextBox, items: List[Text]):
        self._box = box
        self._items = items

    def __repr__(self) -> str:
        return f'TextGroup{{{self.box}, {self.items}}}'

    @property
    def box(self) -> TextBox:
        return self._box

    @property
    def items(self) -> List[Text]:
        return self._items

    def with_items(self, items: List[Text]) -> TextGroup:
        return TextGroup(self._box, items)

    def clone(self) -> TextGroup:
        return TextGroup(self._box, [*self._items])

    def concat(self,
        other: TextGroup,
        x_offset: Optional[int] = None,
        y_offset: Optional[int] = None,
        baseline: Optional[int] = None
    ) -> TextGroup:
        if x_offset is None:
            x_offset = self.box.width
        if y_offset is None:
            y_offset = self.box.baseline - other.box.baseline

        x0 = min(0, x_offset)
        x1 = max(self.box.width, other.box.width + x_offset)
        y0 = min(0, y_offset)
        y1 = max(self.box.height, other.box.height + y_offset)

        if baseline is None:
            baseline = self.box.baseline - y0

        box = TextBox(x1 - x0, y1 - y0, baseline)
        items = [
            *(Text(
                item.x - x0,
                item.y - y0,
                item.text)
            for item in self.items),
            *(Text(
                item.x + x_offset - x0,
                item.y + y_offset - y0,
                item.text)
            for item in other.items)]
        return TextGroup(box, items)

    @staticmethod
    def from_str(text: str) -> TextGroup:
        return TextGroup(TextBox.from_str(text), [Text.from_str(text)])

    @staticmethod
    def empty() -> TextGroup:
        return TextGroup(TextBox.empty(), [])

class Template:
    __slots__ = 'argn', 'definition'

    def __init__(self, argn: int, definition: str):
        self.argn = argn
        self.definition = definition

    def evaluate(self, *args: TextGroup) -> Generator[Union[Token, TextGroup], None, None]:
        assert self.argn == len(args)

        def match_group(argn: int, text: str) -> Optional[int]:
            if len(text) < 2:
                return None
            if text[0] != '#':
                return None
            try:
                group = int(text[1:])
            except ValueError:
                return None
            if 0 <= group < argn:
                return group
            return None

        for token in tokenize(self.definition):
            group = match_group(self.argn, token.value)
            if group is None:
                yield token
            else:
                yield args[group]

def with_tls(f: Callable[..., Any]) -> Callable[..., Any]:
    tls = threading.local()
    def g(*args: Any, **kwargs: Any):
        return f(tls, *args, **kwargs)
    return g

class Function:
    PushArgType = Callable[[Optional[TextGroup]], Tuple[List[str], Optional[TextGroup]]]

    LOOKUP: Dict[str, Function] = {}

    __slots__ = 'ident', 'push_arg'

    def __init__(self,
        ident: str,
        push_arg: Function.PushArgType
    ):
        self.ident     = ident
        self.push_arg  = push_arg

    @staticmethod
    def define(ident: str = '') -> Callable[[Function.PushArgType], Function]:
        def f(push_arg: Function.PushArgType) -> Function:
            nonlocal ident
            if not ident:
                ident = push_arg.__name__
            function = Function(ident, push_arg)
            Function.LOOKUP[ident] = function
            return function
        return f

FG_COLORS = {
    'black'        : ANSI_BLACK,
    'red'          : ANSI_RED,
    'green'        : ANSI_GREEN,
    'yellow'       : ANSI_YELLOW,
    'blue'         : ANSI_BLUE,
    'magenta'      : ANSI_MAGENTA,
    'cyan'         : ANSI_CYAN,
    'lightgray'    : ANSI_WHITE,
    'darkgray'     : ANSI_BRIGHT_BLACK,
    'brightred'    : ANSI_BRIGHT_RED,
    'brightgreen'  : ANSI_BRIGHT_GREEN,
    'brightyellow' : ANSI_BRIGHT_YELLOW,
    'brightblue'   : ANSI_BRIGHT_BLUE,
    'brightmagenta': ANSI_BRIGHT_MAGENTA,
    'brightcyan'   : ANSI_BRIGHT_CYAN,
    'white'        : ANSI_BRIGHT_WHITE
}

@Function.define('fgcolor')
@with_tls
def fgcolor(tls, arg: TextGroup) -> Tuple[List[str], Optional[TextGroup]]:
    try:
        state = tls.state
    except AttributeError:
        state = [ANSI_DEFAULT]
        tls.state = state

    if arg is None:
        state += [None]
        return [], None

    if state[-1] is None:
        for item in arg.items:
            key = item.text.strip().lower()
            try:
                color = FG_COLORS[key]
            except KeyError:
                continue
            state[-1] = color
            return [], None
        state[-1] = ANSI_DEFAULT
        return ['failed to get color'], None

    prefix = state.pop()
    suffix = state[-1]
    return [], TextGroup(arg.box, [Text.from_str(prefix), *arg.items, Text.from_str(suffix)])

class InfixOperator:
    class Associativity:
        __slots__ = ()

    LEFT  = Associativity()
    RIGHT = Associativity()

    EvaluateType = Callable[[TextGroup, TextGroup], TextGroup]

    LOOKUP: Dict[str, InfixOperator] = {}

    __slots__ = 'symbol', 'precedence', 'associativity', 'evaluate'

    def __init__(self,
        symbol       : str,
        precedence   : int,
        associativity: Associativity,
        evaluate     : InfixOperator.EvaluateType
    ):
        self.symbol        = symbol
        self.precedence    = precedence
        self.associativity = associativity
        self.evaluate      = evaluate

    @staticmethod
    def define(
        symbol       : str,
        precedence   : int,
        associativity: Associativity
    ) -> Callable[[InfixOperator.EvaluateType], InfixOperator]:
        def f(evaluate: InfixOperator.EvaluateType) -> InfixOperator:
            operator = InfixOperator(symbol, precedence, associativity, evaluate)
            InfixOperator.LOOKUP[symbol] = operator
            return operator
        return f

@InfixOperator.define('^', 10, InfixOperator.LEFT)
def infix_text_over(lhs: TextGroup, rhs: TextGroup) -> TextGroup:
    width = max(lhs.box.width, rhs.box.width)
    lhs_pad = (width - lhs.box.width) // 2
    rhs_pad = (width - rhs.box.width) // 2
    x_offset = rhs_pad - lhs_pad
    y_offset = lhs.box.height
    return lhs.concat(rhs, x_offset = x_offset, y_offset = y_offset)

@InfixOperator.define('_', 10, InfixOperator.LEFT)
def infix_text_under(lhs: TextGroup, rhs: TextGroup) -> TextGroup:
    width = max(lhs.box.width, rhs.box.width)
    lhs_pad = (width - lhs.box.width) // 2
    rhs_pad = (width - rhs.box.width) // 2
    x_offset = rhs_pad - lhs_pad
    y_offset = -rhs.box.height
    return lhs.concat(rhs, x_offset = x_offset, y_offset = y_offset)

# combined parsing and evaluation; uses shunting-yard based algorithm
def layout(tokens: Iterator[Token]) -> Tuple[List[Tuple[str, Optional[Tuple[int, int]]]], TextGroup]:
    LOG.info('beginning parsing/layout')

    output: List[TextGroup] = []
    operators: List[Token] = []
    quirks: List[Tuple[str, Optional[Tuple[int, int]]]] = []

    def push_arg(token: Token, arg: Optional[TextGroup]):
        nonlocal output, operators, quirks
        LOG.debug(f'push_arg {token} {arg}')
        quirks_, result = Function.LOOKUP[token.value].push_arg(arg)
        if quirks_:
            quirks += [(quirk, token.range) for quirk in quirks_]
        if result:
            LOG.debug(f'\tresult {result}')
            if operators and operators[-1].type == Token.FUNCTION:
                token_ = operators.pop()
                push_arg(token_, result)
            else:
                output += [result]
        else:
            operators += [token]

    def evaluate(token: Token):
        nonlocal output, quirks
        LOG.debug(f'eval {token}')
        if token.type == Token.FUNCTION:
            quirks += [('missing argument for function', token.range)]
            push_arg(token, TextGroup.empty())
        elif token.type == Token.INFIX:
            op = InfixOperator.LOOKUP[token.value]
            rhs = TextGroup.empty()
            lhs = TextGroup.empty()
            try:
                rhs = output.pop()
                LOG.debug(f'rhs {rhs}')
                LOG.debug(f'\ttail {output}')
                lhs = output.pop()
                LOG.debug(f'lhs {lhs}')
                LOG.debug(f'\ttail {output}')
            except IndexError:
                quirks += [('missing operand', token.range)]
            output += [op.evaluate(lhs, rhs)]
            LOG.debug(f'result {output[-1]}')
        elif token.type == Token.SPACE:
            rhs = TextGroup.empty()
            lhs = TextGroup.empty()
            try:
                rhs = output.pop()
                LOG.debug(f'rhs {rhs}')
                LOG.debug(f'\ttail {output}')
                lhs = output.pop()
                LOG.debug(f'lhs {lhs}')
                LOG.debug(f'\ttail {output}')
            except IndexError:
                pass
            output += [lhs.concat(TextGroup.from_str(token.value)).concat(rhs)]
            LOG.debug(f'result {output[-1]}')
        else:
            assert False

    def process_input(token: Token):
        nonlocal output, operators, quirks
        LOG.debug('-'*80)
        LOG.debug(f'input {token}')
        if token.type == Token.FUNCTION:
            push_arg(token, None)
        elif token.type == Token.LBRACKET:
            assert token.value == '{'
            operators += [token]
        elif token.type == Token.RBRACKET:
            assert token.value == '}'
            while True:
                try:
                    token_ = operators.pop()
                except IndexError:
                    quirks += [('unmatched right brace', token.range)]
                    break
                if token_.type == Token.LBRACKET:
                    assert token_.value == '{'
                    break
                else:
                    evaluate(token_)
            if operators and operators[-1].type == Token.FUNCTION:
                token_ = operators.pop()
                arg = output.pop()
                push_arg(token_, arg)
        elif token.type == Token.INFIX:
            op = InfixOperator.LOOKUP[token.value]
            while operators:
                token_ = operators[-1]
                try:
                    op_ = InfixOperator.LOOKUP[token_.value]
                except KeyError:
                    break
                if op.precedence > op_.precedence:
                    break
                if op.associativity == InfixOperator.RIGHT and op.precedence >= op_.precedence:
                    break
                operators = operators[:-1]
                evaluate(token_)
            operators += [token]
        elif token.type == Token.SPACE:
            if operators and operators[-1].type == Token.FUNCTION:
                pass
            else:
                while operators and operators[-1].type != Token.LBRACKET:
                    token_ = operators.pop()
                    evaluate(token_)
                operators += [token]
        else:
            text = TextGroup.from_str(token.value)
            if operators and operators[-1].type == Token.FUNCTION:
                token_ = operators.pop()
                quirks += [('function arguments should be grouped using brackets', token_.range)]
                quirks += [('function argument missing brackets', token.range)]
                push_arg(token_, text)
            else:
                output += [text]
        LOG.debug(f'output state {output}')
        LOG.debug(f'operators state {operators}')

    for token in tokens:
        process_input(token)

    while operators:
        token = operators.pop()
        if token.type == Token.LBRACKET:
            assert token.value == '{'
            quirks += [('unmatched left brace', token.range)]
        else:
            evaluate(token)

    if not output:
        quirks += [('empty output', None)]
    elif len(output) > 1:
        quirks += [('unprocessed operands in output', None)]

    LOG.info(f'quirks {quirks}')
    return quirks, reduce(lambda output, item: output.concat(item), output, TextGroup.empty())

with WinAnsiMode():
    log_handler = logging.FileHandler('markup.log', encoding='utf-8')
    log_handler.setLevel(logging.DEBUG)
    LOG.setLevel(logging.DEBUG)
    LOG.addHandler(log_handler)

    try:
        input = raw_input
    except NameError:
        pass

    while True:
        s = input('> ')
        if not s:
            break

        quirks, group = layout(normalize(tokenize(s)))

        sys.stdout.write(ANSI_SAVE + ANSI_CLEAR)
        for item in group.items:
            sys.stdout.write(ansi_pos(10 - item.y, item.x + 1) + item.text)
        sys.stdout.write(ANSI_RESTORE)

        sys.stdout.flush()