import json
import sys
from pathlib import Path

from app.services.extractor import extract_travel_intent
from app.services.planner import build_itinerary
from app.services.retriever import retrieve_places

PROMPT_PATH = Path(__file__).resolve().parents[1] / "data" / "test_prompts.json"


def evaluate_prompt(prompt: str) -> dict:
    intent = extract_travel_intent(prompt)
    places = retrieve_places(intent)
    itinerary = build_itinerary(intent, places) if places else None
    flattened = itinerary.stops if itinerary else []
    duplicate_count = len(flattened) - len(
        {(place.name.lower(), place.city.lower()) for place in flattened}
    )
    return {
        "prompt": prompt,
        "request_intents": intent.request_intents,
        "destination": intent.destination,
        "duration_days": intent.duration_days,
        "budget": intent.budget,
        "mood": intent.mood,
        "group_type": intent.group_type,
        "food_preference": intent.food_preference,
        "indoor_outdoor": intent.indoor_outdoor,
        "transportation": intent.transportation,
        "walking_constraints": intent.walking_constraints,
        "assumption_count": len(intent.assumptions),
        "clarification_question": intent.clarification_question,
        "candidate_count": len(places),
        "day_count": len(itinerary.days) if itinerary else 0,
        "duplicate_count": duplicate_count,
        "top_places": [
            {
                "name": place.name,
                "city": place.city,
                "category": place.category,
                "source_type": place.source_type,
            }
            for place in flattened[:6]
        ],
    }


def main() -> None:
    payload = json.loads(PROMPT_PATH.read_text(encoding="utf-8"))
    results = [evaluate_prompt(prompt) for prompt in payload["prompts"]]
    output = json.dumps({"total": len(results), "results": results}, indent=2)
    if "--output" in sys.argv:
        output_index = sys.argv.index("--output") + 1
        Path(sys.argv[output_index]).write_text(output, encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
