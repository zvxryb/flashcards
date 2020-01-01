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

## Notes

Only supports Windows, for now.

Unicode should mostly work.  [Windows Terminal](https://github.com/microsoft/terminal) is recommended for display of unicode characters.