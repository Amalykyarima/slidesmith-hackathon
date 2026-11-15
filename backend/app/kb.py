"""Knowledge base for grounded answers (RAG): the SEND Code of Practice plus the school's own documents.

Retrieval is BM25 over short passages, so it is fast, runs anywhere and is explainable: every passage
shown to the AI has an id ([C3], [S2]) that the answer must cite, and the teacher sees the sources.

The Code of Practice passages are short summaries in our own words of the SEND Code of Practice: 0 to 25
years (DfE/DoH, January 2015), Crown copyright, reused under the Open Government Licence v3.0. They point
to the chapter so staff can check the original.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from . import db

CODE_OF_PRACTICE: list[tuple[str, str]] = [
    ("Ch. 6: Broad areas of need",
     "The Code describes four broad areas of need: communication and interaction (including speech, language and "
     "communication needs and autism); cognition and learning (including moderate, severe and specific learning "
     "difficulties such as dyslexia); social, emotional and mental health difficulties; and sensory and/or physical "
     "needs. They help plan action; a pupil's needs are identified as a whole, not fitted into one box."),
    ("Ch. 6: High-quality teaching first",
     "High-quality teaching, differentiated for individual pupils, is the first step in responding to pupils who have "
     "or may have SEN. Additional intervention cannot make up for a lack of good-quality teaching. Schools regularly "
     "review the quality of teaching for all pupils, including those at risk of underachievement."),
    ("Ch. 6: SEN support and the graduated approach",
     "Where a pupil is identified as having SEN, schools should take action to remove barriers to learning and put "
     "effective special educational provision in place. This SEN support takes the form of a four-part cycle, assess, "
     "plan, do, review, through which earlier decisions are revisited and refined as understanding of the pupil grows."),
    ("Ch. 6: Assess",
     "Assess: the class or subject teacher, working with the SENCO, carries out a clear analysis of the pupil's needs. "
     "It draws on the teacher's assessment and experience of the pupil, their previous progress and attainment, their "
     "development compared with peers, the views and experience of parents, the pupil's own views and, where relevant, "
     "advice from external support services."),
    ("Ch. 6: Plan",
     "Plan: where SEN support is decided, parents must be notified. The teacher and SENCO agree, with the parents and "
     "pupil, the adjustments, interventions and support to be put in place, the expected impact on progress, "
     "development or behaviour, and a clear date for review. All staff who work with the pupil should be made aware "
     "of their needs, the outcomes sought, the support provided and any teaching strategies required."),
    ("Ch. 6: Do",
     "Do: the class or subject teacher remains responsible for working with the pupil every day. Where interventions "
     "involve group or one-to-one teaching away from the main teacher, the teacher still retains responsibility and "
     "works closely with teaching assistants or specialist staff to plan and assess the impact. The SENCO supports "
     "the teacher in problem solving and advising on effective support."),
    ("Ch. 6: Review",
     "Review: the effectiveness of the support and its impact on the pupil's progress is reviewed in line with the "
     "agreed date. The impact and quality of support is evaluated with the views of the pupil and parents, which feeds "
     "back into analysis of the pupil's needs. Teachers, with the SENCO, revise the support in light of progress and "
     "agree any changes to outcomes and support with parents and the pupil."),
    ("Ch. 6: Involving parents",
     "Schools must provide an annual report for parents on their child's progress, and should meet parents at least "
     "three times each year where a pupil is receiving SEN support, to set clear outcomes, review progress and discuss "
     "next steps. Conversations should give enough time to understand the pupil's strengths and difficulties and the "
     "parents' concerns, and the outcome should be recorded and shared with parents."),
    ("Ch. 6: Involving specialists",
     "Where a pupil continues to make less than expected progress despite evidence-based support matched to their "
     "needs, the school should consider involving specialists, such as educational psychologists, speech and language "
     "therapists or specialist teachers. Parents should be involved in this decision."),
    ("Ch. 6: Requesting an EHC needs assessment",
     "Where, despite the school having taken relevant and purposeful action to identify, assess and meet the needs of "
     "the pupil, the pupil has not made expected progress, the school or parents should consider requesting an "
     "Education, Health and Care needs assessment. The local authority will need evidence of the action taken as part "
     "of SEN support, so well-kept records of the assess-plan-do-review cycle matter."),
    ("Ch. 6: Record keeping",
     "Schools should record details of additional or different provision made under SEN support. This should form part "
     "of regular discussions with parents about the child's progress, expected outcomes and planned next steps. "
     "Schools are expected to provide information on the effectiveness of their SEN provision."),
    ("Ch. 6: The SENCO",
     "The SENCO has day-to-day responsibility for the operation of SEN policy and coordination of provision for pupils "
     "with SEN. Their duties include advising on the graduated approach, advising on deployment of the school's "
     "delegated budget, liaising with parents and external agencies, and ensuring records of pupils with SEN are up "
     "to date."),
    ("Ch. 9: EHC needs assessments and plans",
     "An EHC needs assessment is carried out by the local authority. The whole process, from request to issuing a final "
     "EHC plan, must take no more than 20 weeks, subject to limited exceptions. Schools contribute advice and "
     "information about the pupil's needs, the provision that has been made and its impact. The local authority, not "
     "the school, writes the EHC plan."),
    ("Ch. 9: Outcomes",
     "An outcome is the benefit or difference made to an individual as a result of an intervention. Good outcomes are "
     "specific, measurable, achievable, realistic and time-bound (SMART), and focus on what the pupil will be able to "
     "do, rather than on the provision itself."),
    ("Ch. 1 and 6: Pupil and parent voice",
     "Local authorities and schools must have regard to the views, wishes and feelings of children, young people and "
     "parents, and the importance of their participating as fully as possible in decisions. Pupils should be involved "
     "in setting outcomes and reviewing progress."),
    ("Ch. 7: Further education",
     "Colleges have duties similar to schools to use their best endeavours to secure the special educational provision "
     "a student needs. Support should be planned with the student, focus on outcomes for adult life, and follow the "
     "same cycle of assessing, planning, delivering and reviewing support."),
]

CREDIT = "SEND Code of Practice: 0 to 25 years (DfE/DoH, 2015), summarised. Contains public sector information licensed under the Open Government Licence v3.0."

SCHEMA = """
CREATE TABLE IF NOT EXISTS kb_docs (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "of", "and", "or", "to", "in", "on", "for", "with", "is", "are", "be", "as", "at", "by",
         "it", "this", "that", "their", "they", "from", "can", "should", "will", "has", "have", "who", "what", "not"}


def _tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall((text or "").lower()) if w not in _STOP and len(w) > 1]


def chunk(text: str, size: int = 90) -> list[str]:
    """Split a document into ~size-word passages on paragraph boundaries."""
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n(?=[-*•]|\d+[.)])", text or "") if p.strip()]
    out, cur = [], []
    for p in paras:
        words = p.split()
        if cur and len(cur) + len(words) > size:
            out.append(" ".join(cur))
            cur = []
        cur.extend(words)
        while len(cur) > size * 1.5:
            out.append(" ".join(cur[:size]))
            cur = cur[size:]
    if cur:
        out.append(" ".join(cur))
    return out


def passages(owner: str) -> list[dict]:
    items = [{"id": f"C{i + 1}", "source": "SEND Code of Practice", "title": t, "text": x}
             for i, (t, x) in enumerate(CODE_OF_PRACTICE)]
    n = 0
    for d in db.many("SELECT * FROM kb_docs WHERE owner=? ORDER BY created_at", (owner,)):
        for c in chunk(d["text"]):
            n += 1
            items.append({"id": f"S{n}", "source": d["name"], "title": d["name"], "text": c})
    return items


def search(owner: str, query: str, k: int = 6, school_first: int = 3) -> list[dict]:
    """BM25 over every passage; keeps at least `school_first` school passages when any match."""
    items = passages(owner)
    docs = [_tokens(p["title"] + " " + p["text"]) for p in items]
    if not docs:
        return []
    avg = sum(len(d) for d in docs) / len(docs)
    df = Counter(w for d in docs for w in set(d))
    q = _tokens(query)
    scored = []
    for p, d in zip(items, docs):
        tf = Counter(d)
        s = 0.0
        for w in q:
            if w in tf:
                idf = math.log(1 + (len(docs) - df[w] + 0.5) / (df[w] + 0.5))
                s += idf * tf[w] * 2.2 / (tf[w] + 1.2 * (0.25 + 0.75 * len(d) / avg))
        if s > 0:
            scored.append((s, p))
    scored.sort(key=lambda t: -t[0])
    school = [p for _, p in scored if p["id"].startswith("S")][:school_first]
    rest = [p for _, p in scored if p not in school]
    return (school + rest)[:k]


def context(hits: list[dict]) -> str:
    return "\n\n".join(f"[{h['id']}] ({h['source']}: {h['title']})\n{h['text']}" for h in hits)


def cited(text: str, hits: list[dict]) -> list[dict]:
    """The sources an answer actually cited, for the teacher to check."""
    ids = set(re.findall(r"\[([CS]\d+)\]", text or ""))
    return [{"id": h["id"], "source": h["source"], "title": h["title"], "text": h["text"]} for h in hits if h["id"] in ids]
