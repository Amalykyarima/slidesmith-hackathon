"""Pictograms for visual supports (OpenMoji, CC BY-SA 4.0, bundled in backend/pictos).

The AI never draws pictures. It names a plain word for each card ("listen", "volcano"), and this
module finds the closest symbol in a fixed, open, child-safe set. Same word, same symbol, every
time: consistency matters for autistic pupils who learn a symbol once and rely on it.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from . import config

INDEX = Path(__file__).parent / "data" / "pictos.json"
PICTO_DIR = config.BASE_DIR / "pictos"
CREDIT = "Symbols: OpenMoji (openmoji.org), CC BY-SA 4.0"

# Classroom routines and actions: the symbol SEN teams expect, not the first literal match.
PREFERRED: dict[str, str] = {
    "listen": "1F442", "listening": "1F442", "hear": "1F442",
    "look": "1F440", "watch": "1F440", "eyes": "1F440", "see": "1F440",
    "read": "1F4D6", "reading": "1F4D6", "book": "1F4D6", "story": "1F4D6",
    "write": "270D", "writing": "270D", "pencil": "270F", "draw": "1F58D",
    "think": "1F914", "thinking": "1F914", "idea": "1F4A1",
    "talk": "1F5E3", "speak": "1F5E3", "discuss": "1F465", "pair": "1F465", "partner": "1F465",
    "group": "1F46A", "together": "1F91D", "team": "1F91D", "share": "1F91D",
    "quiet": "1F92B", "silent": "1F92B", "shh": "1F92B",
    "question": "2753", "ask": "270B", "hand up": "270B", "answer": "1F4AC",
    "check": "2705", "done": "2705", "finish": "2705", "finished": "2705", "complete": "2705",
    "start": "1F6A6", "begin": "1F6A6", "starter": "1F6A6", "stop": "1F6D1", "wait": "23F3", "time": "23F0", "timer": "23F2",
    "break": "2615", "rest": "1F6CB", "calm": "1F60C", "breathe": "1F32C",
    "lunch": "1F96A", "eat": "1F37D", "drink": "1F964", "water": "1F4A7",
    "play": "26BD", "playground": "1F6DD", "pe": "1F3C3", "run": "1F3C3", "music": "1F3B5", "art": "1F3A8",
    "maths": "1F522", "math": "1F522", "numbers": "1F522", "count": "1F522", "calculate": "1F9EE",
    "science": "1F52C", "experiment": "1F9EA", "computer": "1F4BB", "tablet": "1F4F1",
    "home": "1F3E0", "homework": "1F3E0", "school": "1F3EB", "teacher": "1F9D1-200D-1F3EB",
    "happy": "1F600", "sad": "1F622", "angry": "1F620", "worried": "1F61F", "scared": "1F628",
    "tired": "1F971", "excited": "1F929", "proud": "1F60A", "help": "1F64B", "toilet": "1F6BB",
    "good": "1F44D", "well done": "1F31F", "star": "2B50", "remember": "1F9E0", "brain": "1F9E0",
    "now": "1F449", "next": "27A1", "then": "27A1", "goal": "1F3AF", "target": "1F3AF",
    "electricity": "26A1", "energy": "26A1", "heart": "1FAC0", "cell": "1F9A0", "cells": "1F9A0",
    "germ": "1F9A0", "bacteria": "1F9A0", "dinosaur": "1F995", "history": "1F4DC", "romans": "1F3DB",
    "water cycle": "1F327", "rain": "1F327", "plant": "1FAB4", "plants": "1FAB4", "photosynthesis": "1FAB4",
    "fraction": "1F355", "fractions": "1F355", "map": "1F5FA", "geography": "1F5FA", "world": "1F30D",
    "moon": "1F319", "light": "1F4A1", "ocean": "1F30A", "sea": "1F30A", "graph": "1F4C8", "data": "1F4CA",
    "healthy": "1F34E", "food": "1F34E", "fruit": "1F34E", "sleep": "1F634", "exercise": "1F3C3",
    "underline": "270F", "circle": "2B55", "label": "1F3F7", "match": "1F517", "sort": "1F5C2", "list": "1F4DD",
    "explain": "1F4AC", "describe": "1F4AC", "compare": "2696", "plan": "1F4CB", "design": "1F4D0", "find": "1F50D",
    "lava": "E099", "magma": "E099", "eruption": "E099", "erupt": "E099", "crater": "1F30B",
    "pour": "1FAD7", "pouring": "1FAD7", "liquid": "1FAD7", "vinegar": "1FAD7", "mix": "1F944", "stir": "1F944",
    "add": "2795", "plus": "2795", "minus": "2796", "equals": "1F7F0", "pressure": "1F4A8", "gas": "1F4A8",
    "diagram": "1F5BC", "picture": "1F5BC", "key words": "1F511", "key word": "1F511", "vocabulary": "1F511",
    "safety": "1F97D", "goggles": "1F97D", "lab": "1F97C", "practical": "1F97C", "experiment": "1F9EA",
    "show": "1F64B", "welcome": "1F44B", "hello": "1F44B", "goodbye": "1F44B", "glue": "1F4CE",
    "learn": "1F393", "lesson": "1F393", "lecture": "1F393", "study": "1F393", "revise": "1F4DA",
    "supply": "1F4E6", "demand": "1F6D2", "price": "1F4B7", "market": "1F3EA", "money": "1F4B7",
    "equilibrium": "2696", "balance": "2696", "bottle": "E0CB", "alcohol": "1F377", "wine": "1F377", "drinks": "1F964", "adult": "1F9D1", "make": "1F6E0", "model": "1F6E0", "build": "1F6E0",
    "card": "1F4C7", "plate": "1F37D", "bin": "1F5D1", "rubbish": "1F5D1", "clay": "1F3FA", "sand": "1F3D6",
    "cut": "2702", "colour": "1F58D", "color": "1F58D", "colouring": "1F3A8", "paint": "1F58C", "measure": "1F4CF",
    "tidy": "1F9F9", "line up": "1F6B6", "walk": "1F6B6", "sit": "1FA91", "chair": "1FA91",
}


@lru_cache(maxsize=1)
def _index() -> list[dict]:
    return json.loads(INDEX.read_text()) if INDEX.exists() else []


@lru_cache(maxsize=1)
def _by_id() -> dict[str, dict]:
    return {p["id"]: p for p in _index()}


STOP = {"the", "a", "an", "of", "and", "or", "to", "in", "on", "for", "with", "your", "my", "our",
        "is", "are", "be", "at", "by", "it", "this", "that"}


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]+", (text or "").lower()) if w not in STOP]


@lru_cache(maxsize=4096)
def find(word: str) -> dict | None:
    """Best symbol for a word or short phrase, or None."""
    q = " ".join(_words(word))
    if not q:
        return None
    if q in PREFERRED and PREFERRED[q] in _by_id():
        return _by_id()[PREFERRED[q]]
    qw = set(q.split())
    if len(qw) > 1:  # a phrase containing a known classroom word: that word's symbol wins
        padded = f" {q} "
        for key in sorted(PREFERRED, key=len, reverse=True):
            if f" {key} " in padded and PREFERRED[key] in _by_id():
                return _by_id()[PREFERRED[key]]
    stem = {w.rstrip("s") for w in qw}
    best, best_score = None, 0.0
    for p in _index():
        name = p["name"].lower()
        nw = set(_words(name))
        tw = set(_words(p["tags"]))
        if name == q:
            score = 100.0
        else:
            score = 0.0
            score += 12 * len(qw & nw) + 8 * len({w.rstrip("s") for w in nw} & stem)
            score += 4 * len(qw & tw) + 2 * len({w.rstrip("s") for w in tw} & stem)
            if score:
                score -= 0.3 * len(nw)  # prefer short, literal names ("volcano" over "volcano with smoke")
                if p["group"] == "extras-openmoji":
                    score -= 1  # keep standard emoji first; extras are niche
        if score > best_score:
            best, best_score = p, score
    # One partial word in a long phrase is too weak a match: show the word without a symbol.
    # Each query word must earn its place: a phrase needs most of its words to match.
    need = 7 if len(qw) == 1 else 10 * len(qw) * 0.6
    if best and best_score < need:
        best = None
    for w in q.split():  # fall back to any single word we have a preferred symbol for
        if best is None and w in PREFERRED:
            return _by_id().get(PREFERRED[w])
    return best


def symbol(word: str, *fallbacks: str) -> dict:
    """{word, picto_id, picto_url, picto_name} for a card. picto_* are null when nothing fits.

    When the agent's symbol word has no match, try the card's own text, then each of its words,
    so a card is rarely left without a picture.
    """
    p = find(word)
    for alt in fallbacks:
        if p:
            break
        p = find(alt)
        for w in _words(alt):
            if p:
                break
            if len(w) > 2:
                p = find(w)
    return {
        "word": word,
        "picto_id": p["id"] if p else None,
        "picto_url": f"/files/pictos/{p['id']}.svg" if p else None,
        "picto_name": p["name"] if p else None,
    }


def search(query: str, limit: int = 24) -> list[dict]:
    """For the teacher's 'swap symbol' picker."""
    qw = set(_words(query))
    if not qw:
        return []
    stem = {w.rstrip("s") for w in qw}
    scored = []
    for p in _index():
        nw = {w.rstrip("s") for w in _words(p["name"])}
        tw = {w.rstrip("s") for w in _words(p["tags"])}
        score = 10 * len(stem & nw) + 3 * len(stem & tw) - 0.3 * len(nw)
        if stem & (nw | tw):
            scored.append((-score, p))
    scored.sort(key=lambda t: t[0])
    return [{"id": p["id"], "name": p["name"], "url": f"/files/pictos/{p['id']}.svg"} for _, p in scored[:limit]]
