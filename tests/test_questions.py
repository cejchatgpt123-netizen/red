import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_question_bank():
    questions = json.loads((ROOT / 'questions.json').read_text(encoding='utf-8'))
    assert len(questions) == 15
    assert len({q['id'] for q in questions}) == len(questions)
    for q in questions:
        assert q['explanation']
        if q['type'] == 'multiple_choice':
            assert q['answer'] in q['options']
        elif q['type'] == 'true_false':
            assert type(q['answer']) is bool
        else:
            assert q['type'] == 'matching'
            assert all(value in q['options'] for value in q['pairs'].values())
