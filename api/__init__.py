"""The HTTP surface. A layer OVER the runtime, never part of it.

`app/` imports nothing from here and nothing from FastAPI, so an interview runs on the
standard library alone whether or not the web extra is installed. Everything below calls the
same functions the terminal tools call -- `app/review.py` was written for two callers from the
start, and a second implementation of a rule is a second place for it to be wrong.
"""
