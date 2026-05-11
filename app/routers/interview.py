"""Interview router — /api/interview/*"""
import re
import logging
from fastapi import APIRouter, Depends
from app.database import User
from app.dependencies import get_current_user
from app.services.llm import get_llm

router = APIRouter(prefix="/api/interview", tags=["interview"])
logger = logging.getLogger(__name__)

RUBRICS = {
    "chevening": {
        "name": "Chevening Official Rubric",
        "dimensions": [
            {"key": "leadership", "label": "Leadership & Influence", "weight": 25},
            {"key": "networking", "label": "Networking Ability", "weight": 25},
            {"key": "ambassador", "label": "Ambassador Potential", "weight": 25},
            {"key": "career_plan", "label": "Study & Career Plan", "weight": 25},
        ],
    },
    "fulbright": {
        "name": "Fulbright Selection Criteria",
        "dimensions": [
            {"key": "academic", "label": "Academic Excellence", "weight": 30},
            {"key": "project", "label": "Project Feasibility", "weight": 30},
            {"key": "cross_cultural", "label": "Cross-cultural Engagement", "weight": 20},
            {"key": "impact", "label": "Long-term Impact", "weight": 20},
        ],
    },
    "gates_cambridge": {
        "name": "Gates Cambridge Criteria",
        "dimensions": [
            {"key": "academic", "label": "Academic Achievement", "weight": 30},
            {"key": "leadership", "label": "Leadership Potential", "weight": 30},
            {"key": "commitment", "label": "Commitment to Others", "weight": 25},
            {"key": "cambridge_fit", "label": "Cambridge Fit", "weight": 15},
        ],
    },
    "general": {
        "name": "General Scholarship Rubric",
        "dimensions": [
            {"key": "clarity", "label": "Clarity & Structure", "weight": 25},
            {"key": "specificity", "label": "Specificity & Evidence", "weight": 35},
            {"key": "relevance", "label": "Relevance to Scholarship", "weight": 25},
            {"key": "impact", "label": "Potential Impact", "weight": 15},
        ],
    },
}

FILLERS = ["um","uh","like","basically","literally","honestly",
           "actually","very","really","just","sort of","kind of"]


@router.get("/questions/{scholarship_slug}")
async def get_questions(scholarship_slug: str,
                        user: User = Depends(get_current_user)):
    from engine.interview_data import QUESTION_BANKS
    return {
        "scholarship": scholarship_slug,
        "rubric": RUBRICS.get(scholarship_slug, RUBRICS["general"]),
        "questions": QUESTION_BANKS.get(scholarship_slug.lower(),
                                        QUESTION_BANKS["general"]),
    }


@router.post("/score")
async def score_answer(data: dict, user: User = Depends(get_current_user)):
    question = data.get("question", "")
    answer = data.get("answer", "")
    scholarship = data.get("scholarship", "general")
    rubric = RUBRICS.get(scholarship, RUBRICS["general"])
    wc = len(answer.split())

    if wc < 20:
        return {"overall_score": 0.2, "grade": "D", "word_count": wc,
                "feedback": "Answer too short. Aim for 150–250 words with specific examples.",
                "strengths": [], "improvements": ["Write at least 150 words"],
                "filler_count": 0}

    rubric_str = ", ".join(
        f"{d['label']} ({d['weight']}%)" for d in rubric["dimensions"]
    )
    llm = get_llm()
    system = (
        "You are an expert scholarship interview coach scoring answers "
        "against official rubrics. Respond ONLY with a JSON object."
    )
    prompt = (
        f"Score this {scholarship.replace('_',' ').title()} scholarship answer.\n\n"
        f"RUBRIC: {rubric_str}\n\n"
        f"QUESTION: {question}\n\n"
        f"ANSWER ({wc} words): {answer}\n\n"
        "Return JSON: score (0.0-1.0), grade (A/B/C/D), "
        "feedback (2-3 sentences), strengths (list of 2), improvements (list of 2)"
    )
    try:
        raw = llm(system, prompt)
        start = raw.find("{"); end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            import json
            result = json.loads(raw[start:end])
            score = float(result.get("score", 0.6))
            grade = result.get("grade", "B")
            feedback = result.get("feedback", "Good answer. Add more specific examples.")
            strengths = result.get("strengths", [])
            improvements = result.get("improvements", [])
        else:
            raise ValueError("No JSON found")
    except Exception as e:
        logger.warning("AI scoring fallback: %s", e)
        has_numbers = any(c.isdigit() for c in answer)
        is_long = wc >= 150
        is_specific = len([w for w in answer.split() if len(w) > 6]) > 10
        score = 0.5 + (0.15 if has_numbers else 0) + \
                (0.1 if is_long else 0) + (0.1 if is_specific else 0)
        grade = "A" if score >= 0.85 else "B" if score >= 0.7 else \
                "C" if score >= 0.55 else "D"
        feedback = (f"{'Good length. ' if is_long else 'Too brief — aim for 150+ words. '}"
                    f"{'Good specifics. ' if is_specific else 'Add concrete examples. '}"
                    f"{'Quantified well. ' if has_numbers else 'Include measurable outcomes.'}")
        strengths = ["Relevant content" if is_long else "Concise"]
        improvements = ["Add specific numbers and dates", "Include measurable outcomes"]

    filler_count = sum(answer.lower().split().count(f) for f in FILLERS)
    return {
        "overall_score": round(min(1.0, max(0.0, score)), 2),
        "grade": grade, "feedback": feedback,
        "word_count": wc, "filler_count": filler_count,
        "strengths": strengths, "improvements": improvements,
        "rubric": rubric,
    }
