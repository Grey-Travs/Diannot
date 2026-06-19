"""AI-generated multiple-choice quizzes from a note, with an interactive HTML view."""
from __future__ import annotations

import html as _html
import json
from typing import Optional

from pydantic import BaseModel, Field

from .config import Settings
from .models import Note
from .render import load_theme


class Question(BaseModel):
    question: str
    choices: list[str]
    answer: int  # 0-based index of the correct choice
    explanation: Optional[str] = None


class Quiz(BaseModel):
    title: str
    questions: list[Question] = Field(default_factory=list)


def generate_quiz(
    note: Note, model: str | None = None, settings: Settings | None = None, count: int = 6
) -> Quiz:
    """Generate a multiple-choice quiz from ``note`` using Claude."""
    from .cards import note_to_text
    from .structure import complete_json

    system = (
        "You are a quiz generator. Output a SINGLE JSON object: "
        '{"questions": [{"question": "...", "choices": ["a","b","c","d"], '
        '"answer": <0-based index of the correct choice>, "explanation": "why"}]}. '
        "Exactly 4 choices each, exactly one correct. Questions must be answerable from "
        "the note. JSON only, no markdown."
    )
    prompt = f"Write {count} multiple-choice questions from this note. JSON only.\n\n" + note_to_text(note)
    data = complete_json(system, prompt, model=model, settings=settings)

    questions: list[Question] = []
    for q in data.get("questions", []):
        choices = [str(c) for c in q.get("choices", [])]
        answer = q.get("answer", 0)
        if isinstance(answer, str) and answer.isdigit():
            answer = int(answer)
        if len(choices) >= 2 and isinstance(answer, int) and 0 <= answer < len(choices):
            questions.append(
                Question(
                    question=str(q.get("question", "")).strip(),
                    choices=choices,
                    answer=answer,
                    explanation=(q.get("explanation") or None),
                )
            )
    return Quiz(title=note.title, questions=questions)


def render_quiz_html(quiz: Quiz, theme_name: str = "circulatory", settings: Settings | None = None) -> str:
    """Render a self-contained interactive multiple-choice quiz with scoring."""
    settings = settings or Settings()
    primary = load_theme(theme_name, settings.paths.themes_dir)["colors"]["primary"]

    blocks, answers, expl = [], [], []
    for i, q in enumerate(quiz.questions):
        answers.append(q.answer)
        expl.append(q.explanation or "")
        opts = "".join(
            f'<label class="opt"><input type="radio" name="q{i}" value="{j}"> {_html.escape(c)}</label>'
            for j, c in enumerate(q.choices)
        )
        blocks.append(
            f'<fieldset class="q" id="q{i}"><legend class="qtext">{i + 1}. {_html.escape(q.question)}</legend>'
            f'{opts}<div class="exp" id="exp{i}"></div></fieldset>'
        )

    css = (
        "body{font-family:'Segoe UI',system-ui,sans-serif;background:#f4f4f6;margin:0;padding:24px;color:#222;max-width:820px}"
        "h1{color:PRIMARY}.q{background:#fff;border:0;border-radius:12px;padding:14px 16px;margin:12px 0;box-shadow:0 2px 8px rgba(0,0,0,.08)}"
        ".qtext{font-weight:700;margin-bottom:8px;width:100%}.opt{display:block;padding:6px 8px;border-radius:8px;margin:3px 0;cursor:pointer}"
        ".opt:hover{background:#f0f0f3}.opt.correct{background:#e3f7e3;outline:1px solid #46a046}"
        ".opt.wrong{background:#fde8e8;outline:1px solid #d05050}"
        ".exp{display:none;font-size:13px;color:#666;margin-top:8px;font-style:italic}"
        "button{background:PRIMARY;color:#fff;border:0;border-radius:8px;padding:10px 18px;font-size:15px;cursor:pointer}"
        "#score{font-weight:700;font-size:18px;margin-top:14px;color:PRIMARY}"
    ).replace("PRIMARY", primary)

    js = (
        "const ANSWERS=%s;const EXPL=%s;"
        "function check(){let s=0;for(let i=0;i<ANSWERS.length;i++){"
        "const sel=document.querySelector('input[name=q'+i+']:checked');"
        "const q=document.getElementById('q'+i);const opts=q.querySelectorAll('.opt');"
        "opts.forEach((o,j)=>{o.classList.remove('correct','wrong');if(j===ANSWERS[i])o.classList.add('correct');});"
        "if(sel){const v=parseInt(sel.value);if(v===ANSWERS[i])s++;else opts[v].classList.add('wrong');}"
        "const e=document.getElementById('exp'+i);if(EXPL[i]){e.textContent='\\u00bb '+EXPL[i];e.style.display='block';}}"
        "document.getElementById('score').textContent='Score: '+s+' / '+ANSWERS.length;}"
    ) % (json.dumps(answers), json.dumps(expl))

    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        f"<title>{_html.escape(quiz.title)} — quiz</title><style>{css}</style></head><body>"
        f"<h1>{_html.escape(quiz.title)} — Quiz</h1>{''.join(blocks)}"
        "<button onclick='check()'>Check answers</button><div id='score' aria-live='polite'></div>"
        f"<script>{js}</script></body></html>"
    )
