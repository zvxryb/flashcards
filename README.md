## Features

* Lightweight, no dependencies, console UI only
* Support for a simple markup language, including macros
* Interactive practice mode
  * Automatic evaluation of user's answers (equivalence normalized for case, whitespace, and unicode representation)
  * User self-evaluation using the space key (highlight card and toggle correct/incorrect)
* Interactive card editor
  * Real-time preview
  * Real-time validation of syntax (errors highlighted in red)
* Import and export decks to JSON or CSV
* Partial unicode support (full-width characters, etc., see below for notes)

## Usage

```
usage: flashcards.py [-h] --db DB {list,create,import,export,start} ...

positional arguments:
  {list,create,import,export,start}
    list                list items
    create              create items
    import              import a deck
    export              export a deck
    start               start a session

optional arguments:
  -h, --help            show this help message and exit
  --db DB
```

## Quickstart

Create a new deck:

```python flashcards.py --db example.db create deck```

Create a session:

```python flashcards.py --db example.db create session```

Start practicing:

```python flashcards.py --db example.db start example_session```

## Markup

The following operations are supported:

Operator                | Description
------------------------|------------
`\fgcolor{color}{text}` | Sets foreground color.  `color` may be any of `black`, `red`, `green`, `yellow`, `blue`, `magenta`, `cyan`, `lightgray`/`lightgrey`, `darkgray`/`darkgrey`, `brightred`, `brightyellow`, `brightblue`, `brightmagenta`, `brightcyan`, or `white`
`\` | Escape character; treat following character as a literal, unless it's a valid function or macro name.
`{}` | Create a group of text
`_` | Place right-hand side text directly below left-hand side text (centered)
`^` | Place right-hand side text directly above left-hand side text (centered)

Macros are also supported and can be created using the `create macro` command.  A macro is invoked using `\macroname{arg1}{arg2}...{argn}` syntax.  A macro definition references its arguments using `#1`, `#2`, etc., starting at index 1.  Arguments will be subsituted where the corresponding reference is found.

## Notes

If the UI displays incorrectly, ensure your terminal is appropriately sized _before_ launching the script.  The UI is statically sized at 119x29, but may require an extra column or row.

Only supports Windows, for now.

Unicode should mostly work, but language-specific formatting rules are not implemented for every language.  [Windows Terminal](https://github.com/microsoft/terminal) is recommended for display of unicode characters.