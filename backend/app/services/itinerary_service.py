from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

import urllib.parse

from ..db.mongo import mongo
from ..core.config import settings
from .gemini_client import generate_json
from .openweather_client import get_weather_insights
from .email_service import send_email, get_itinerary_email_html
from .serpapi_client import search_hotels, search_web, search_flights
import asyncio


def _cache_key(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _google_maps_link(location: str) -> str:
    return "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(location)


def _days_from_dates(start_date: str, end_date: str) -> int:
    start = datetime.fromisoformat(start_date).date()
    end = datetime.fromisoformat(end_date).date()
    delta = (end - start).days
    return max(1, delta + 1)


def _build_generation_prompt(*, form: dict[str, Any], num_days: int, weather: str, hotels_data: str, transport_data: str, rag_data: str, cost_data: str) -> str:
    return f"""
You are an advanced AI travel planner and tourism expert.
Generate a PREMIUM, REALISTIC, DETAILED, USER-FRIENDLY travel plan.

IMPORTANT:
- Return ONLY valid JSON.
- No markdown.
- No explanation outside JSON.
- No code fences.

JSON SCHEMA:
{{
  "weatherInsights": string,
  "transportDetails": string,
  "hotels": [
    {{
      "name": string,
      "price": number,
      "rating": number,
      "location": string,
      "mapsLink": string
    }}
  ],
  "costPredictor": string,
  "aiRecommendations": string,
  "optimizedItinerary": {{
    "days": [string]
  }}
}}

USER TRIP DETAILS:
- Origin: {form['origin']}
- Destination: {form['destination']}
- Travel Dates: {form['startDate']} to {form['endDate']}
- Number Of People: {form['numberOfPeople']}
- Travel Type: {form['travelType']}
- Budget: ₹{form['budget']} INR
- Preferred Transport: {form['transportMode']}
- Preferences: {form.get('preferences', '')} (If preferences are missing, assume standard tourist experience with balanced sightseeing and food focus)

REAL-WORLD DATA (USE THIS STRICTLY):
---
REAL-TIME WEATHER DATA:
{weather}

LIVE HOTELS DATA (SERPAPI):
{hotels_data}

LIVE TRANSPORT DATA (WEB SEARCH):
{transport_data}

LIVE COST ESTIMATES (WEB SEARCH):
{cost_data}

LIVE RECOMMENDATIONS (WEB SEARCH):
{rag_data}
---

STRICT GENERATION RULES:
- CURRENCY RULE (CRITICAL): ALL prices, budgets, hotel rates, transport fares, meals, and activity fees MUST be strictly in Indian Rupees (INR / ₹). NEVER output USD or $.
- You MUST base your generation on the REAL-WORLD DATA provided above. Do not hallucinate prices, transport, or hotels if real data is provided. If real-world data is missing for any section, explicitly label it as 'Estimated' and proceed using fallback rules.
- Always adjust weather, pricing, and activities based on destination geography and season.
- Classify destination as: Budget / Mid-range / Expensive (based on global tourism standard) and adjust all pricing accordingly.

1. WEATHER INSIGHTS:
- Provide expected weather patterns based on historical averages for that date range for the destination {form['startDate']} to {form['endDate']}.
- Clearly tell:
  - whether the weather is suitable for travel or not.
  - temperature conditions (high/low during these dates).
  - rainfall/snowfall chances during travel period.
  - travel comfort level for the selected dates.
  - specific season characteristics at the destination during these dates.
- If the selected dates are not suitable:
  - recommend the BEST months/dates to visit instead.
- Mention specific clothing suggestions and safety tips for these dates.
- Generate professional tourism-style weather insights with specific date references.
- Keep this section SHORT and SWEET. Use concise sentences (Must Implemented).

2. TRANSPORT DETAILS:
- Keep this section extremely SHORT and SWEET. Use concise bullet points(must).
- Generate REALISTIC transportation insights for {form['transportMode']} from {form['origin']} to {form['destination']}.
- Include:
  - Whether this transport mode is available for this route.
  - Only mention well-known major operators; if uncertain, state 'multiple operators available'.
  - Approximate ticket prices (for {form['numberOfPeople']} people).
  - Typical travel duration.
  - Departure and arrival timing examples.
  - Booking recommendations and websites.
  - Comfort level and amenities for this transport mode.
- Transportation pricing must be realistic, moderate, distance-based, city/route based, traveler-count based, and transport-class based. Do NOT overestimate or underestimate. Outputs should be consistent for identical inputs under identical data conditions.

IF TRANSPORT MODE = FLIGHT:
- Mention:
  - Major airlines operating this route
  - EXPLICITLY state "Average One-Way Price per person: ₹X" (USE STANDARD ECONOMY AVERAGE IN INR)
  - Flight duration
  - Example departure/arrival times
  - Best booking websites (Skyscanner, Google Flights, MakeMyTrip, Booking.com, etc.)
  - EXPLICITLY state "Total One-Way Cost for {form['numberOfPeople']} person(s): ₹Y"

IF TRANSPORT MODE = TRAIN:
- Mention:
  - Train availability and frequency
  - Major train services/operators
  - EXPLICITLY state "Average One-Way Price per person: ₹X" (USE STANDARD ECONOMY AVERAGE IN INR)
  - Travel duration
  - Comfort classes available
  - Best booking methods
  - EXPLICITLY state "Total One-Way Cost for {form['numberOfPeople']} person(s): ₹Y"

IF TRANSPORT MODE = BUS:
- Mention:
  - Luxury/deluxe bus availability
  - EXPLICITLY state "Average One-Way Price per person: ₹X" (USE STANDARD AVERAGE IN INR)
  - Travel duration (including stops)
  - Day/night options
  - Popular bus operators
  - EXPLICITLY state "Total One-Way Cost for {form['numberOfPeople']} person(s): ₹Y"

IF SELECTED TRANSPORT IS NOT AVAILABLE:
- Clearly state: "Routes of {form['transportMode']} are not available for this route."
- Briefly recommend the BEST alternative transportation With explanation.

3. HOTELS:
- You MUST use the LIVE HOTELS DATA provided in the real-world data section. 
- Generate exactly 3 hotels suitable for {form['destination']} and user budget for {form['numberOfPeople']} people.
- Prioritize the hotels retrieved from SerpAPI. If they do not match the required categories or aren't enough, fallback to realistic estimates in INR.
- Include EXACTLY these three categories if possible: Standard Stay, Premium Stay, Luxury Stay.
- Extract the nightly price in INR from the provided live data (convert if needed). Return a clean numeric value without decimals or currency symbols in the JSON `price` field.

For each hotel provide:
- hotel name
- approximate NIGHTLY PRICE in INR (per room, not per person)
- realistic rating out of 5
- hotel location/area name
- Google Maps search link(Must working for the location provided).

Hotels must:
- Match the travel type and preferences.
- Include both room capacity info and accessibility notes.

CRITICAL: Provide realistic nightly prices in INR for the destination (not inflated/reduced).

4. COST PREDICTOR:
Generate a detailed cost breakdown in Indian Rupees (INR / ₹) for {form['numberOfPeople']} person(s) for {num_days} days.
CRITICAL INSTRUCTIONS:
- You MUST follow the exact formulas below.
- ALL amounts MUST be in Indian Rupees (₹). Never output USD or $.
- Do NOT generate arbitrary or dummy values.
- Calculate subtotal first, then calculate miscellaneous, then calculate final total.

ACCOMMODATION CALCULATION:
- Use the hotel pricing data in INR retrieved from SerpAPI (if available in live data).
- Calculate average nightly rate × {num_days} nights.
- Account for room sharing: Roughly 1 room per 2 people (adjust if needed).
- If no pricing exists, return an estimated range in INR and clearly label it as "Estimated". Do not fabricate luxury/premium prices.

MEALS & FOOD CALCULATION:
- Use destination-based daily estimates in INR.
- Budget tier: ₹500–₹1,200 per traveler per day.
- Mid-range tier: ₹1,200–₹2,800 per traveler per day.
- Premium tier: ₹2,800–₹5,000 per traveler per day.
- Choose tier based on overall budget: ₹{form['budget']} INR.
- Formula: daily_food_cost × {form['numberOfPeople']} travelers × {num_days} days.

LOCAL TRANSPORT CALCULATION:
- Use destination-specific estimates in INR.
- Budget tier: ₹250–₹650 per traveler per day.
- Mid-range tier: ₹650–₹1,600 per traveler per day.
- Premium tier: ₹1,600–₹3,500 per traveler per day.
- Formula: daily_transport_cost × {form['numberOfPeople']} travelers × {num_days} days.

SIGHTSEEING & ACTIVITIES CALCULATION:
- Use actual attraction ticket prices in INR if available in live data.
- Otherwise estimate conservatively in INR. Do not default to unrealistically large values.
- Formula: daily_activity_cost × {form['numberOfPeople']} travelers × {num_days} days.

ROUND TRIP TRAVEL ({form['transportMode']}):
- NEVER hallucinate flight or transport costs. Use the data calculated in the TRANSPORT DETAILS section in INR.
- Formula: round_trip_cost = total_one_way_cost_for_all_travelers × 2.
- CRITICAL: Do NOT estimate another value. If total one-way cost for 2 travelers is ₹15,000, Round Trip Cost MUST be ₹30,000.

MISCELLANEOUS COSTS:
- Includes tips, snacks, souvenirs, emergency purchases, and small unplanned expenses.
- Formula: miscellaneous_cost = 10% of subtotal (Accommodation + Food + Local Transport + Activities + Round Trip Travel).
- Display this separately below Round Trip Travel.

TOTAL CALCULATION:
- Final Output Format MUST exactly follow this list (all values in Indian Rupees ₹):
  Accommodation: ₹X
  Food: ₹X
  Local Transport: ₹X
  Sightseeing & Activities: ₹X
  Round Trip Travel ({form['transportMode']}): ₹X
  Miscellaneous Costs: ₹X
  
  Total Estimated Budget: ₹TOTAL INR

Also indicate:
- Budget level (Budget, Mid-range, or Premium)
- Number of travelers: {form['numberOfPeople']}
- Number of days: {num_days}
- Explain whether the user's budget of ₹{form['budget']} INR is Sufficient, Tight, or Luxury.

Use line-by-line bullet points, not paragraphs.

5. AI RECOMMENDATIONS:
- Keep this section SHORT and SWEET.
- Generate 4 to 8 maximum HIGH QUALITY recommendations specific to {form['destination']}.
- Use the LIVE RECOMMENDATIONS (WEB SEARCH) data provided above to give up-to-date and highly relevant tips.

STRICT FORMAT:
- Each recommendation MUST start with: "• "
- You MUST insert a literal newline character `\n` after every single recommendation.
- Do NOT output all recommendations on a single line. They MUST be separated by newlines.
- Include SPECIFIC activity names, locations, approximate costs in INR (₹)

Recommendations should include:
- Local foods with typical prices (₹X per meal)
- Safety tips specific to region and season
- Best local cafes/restaurants with price range
- Hidden gems (less touristy places) with cost estimates
- Local shopping spots with price info
- Best sunrise/sunset spots (free or paid)
- Cultural tips and etiquette
- Photography tips and good spots
- Activity costs should be per-person estimates that fit in the budget

IMPORTANT: Include realistic cost estimates for paid activities, entrance fees, or experiences
- DO NOT add extra explanations or long descriptions.


6. OPTIMIZED ITINERARY:
Generate EXACTLY {num_days} days.
Keep every activity description EXTREMELY SHORT AND SWEET. DO NOT write bulky paragraphs. Use a maximum of 1 short sentence per activity.

STRICT FORMAT FOR EACH DAY:
Day X: Title

• 07:00 AM - Activity
• 09:00 AM - Activity
• 11:00 AM - Activity
• 01:00 PM - Activity
• 03:00 PM - Activity
• 06:00 PM - Activity
• 08:00 PM - Activity

RULES:
- Include realistic timings.
- Activities must match travel preferences.
- Activities should be geographically practical.
- Avoid impossible schedules.
- Include:
  - breakfast
  - sightseeing
  - relaxation
  - local exploration
  - dinner suggestions
- Mention famous attractions and hidden gems.
- Make itinerary feel premium and exciting.
- Do NOT repeat activities across days.
- Each attraction must be unique across entire itinerary; reuse is forbidden unless it is a transport hub or unavoidable landmark. If destination is small, reduce unique attractions logically while maintaining structure.
- Do NOT generate generic plans.
- Plans should feel personalized and intelligent.

VERY IMPORTANT:
- ALL 6 JSON keys (`weatherInsights`, `transportDetails`, `hotels`, `costPredictor`, `aiRecommendations`, `optimizedItinerary`) are MANDATORY and MUST NOT be empty for ANY travelType (Solo, Couple, Family, or Group/Friends).
- `aiRecommendations` MUST be a non-empty newline-separated string of 4–8 bullet tips.
- `optimizedItinerary.days` MUST contain EXACTLY {num_days} detailed string items (one per day, never empty).
- Every day string must already include proper formatting with newline-separated `• HH:MM AM/PM - Activity` bullets.
- Do NOT repeat Day headings multiple times.
- Keep response highly professional and tourism-quality.
"""


def _normalize_ai_recommendations(raw_recs: Any) -> str:
    if not raw_recs:
        return ""
    if isinstance(raw_recs, str):
        text = raw_recs.strip()
        # Ensure inline bullets separated onto new lines if LLM put them on one line
        if "\n" not in text and "•" in text:
            parts = [p.strip() for p in text.split("•") if p.strip()]
            return "\n".join(f"• {p}" for p in parts)
        return text
    if isinstance(raw_recs, list):
        items: list[str] = []
        for item in raw_recs:
            if isinstance(item, dict):
                val = item.get("text") or item.get("description") or item.get("tip") or item.get("recommendation") or item.get("title") or ""
                s = str(val).strip()
            else:
                s = str(item).strip()
            if s:
                items.append(s if s.startswith(("•", "-", "*")) else f"• {s}")
        return "\n".join(items)
    if isinstance(raw_recs, dict):
        return "\n".join(f"• {k}: {v}" for k, v in raw_recs.items() if v)
    return str(raw_recs).strip()


def _format_day_entry(day_item: Any, idx: int) -> str:
    if isinstance(day_item, str):
        text = day_item.strip()
        if not text:
            return ""
        # If LLM placed bullets inline on one line without newlines, split cleanly so UI renders activities
        if "\n" not in text and "•" in text:
            parts = [p.strip() for p in text.split("•") if p.strip()]
            if len(parts) > 1:
                return parts[0] + "\n" + "\n".join(f"• {p}" for p in parts[1:])
        return text

    if isinstance(day_item, dict):
        raw_title = str(day_item.get("title") or day_item.get("heading") or day_item.get("theme") or f"Day {idx + 1}").strip()
        if not raw_title.lower().startswith("day"):
            title = f"Day {idx + 1}: {raw_title}"
        else:
            title = raw_title

        activities_raw = (
            day_item.get("activities")
            or day_item.get("schedule")
            or day_item.get("items")
            or day_item.get("plan")
            or day_item.get("events")
        )
        lines = [title]
        if isinstance(activities_raw, list):
            for act in activities_raw:
                if isinstance(act, dict):
                    t = act.get("time") or act.get("slot") or ""
                    desc = act.get("activity") or act.get("description") or act.get("title") or act.get("details") or ""
                    line = f"{t} - {desc}".strip(" -") if t else str(desc).strip()
                else:
                    line = str(act).strip()
                if line:
                    lines.append(line if line.startswith(("•", "-", "*")) else f"• {line}")
        elif isinstance(activities_raw, str) and activities_raw.strip():
            lines.append(activities_raw.strip())
        else:
            for slot in ("morning", "afternoon", "evening", "night"):
                val = day_item.get(slot)
                if val:
                    lines.append(f"• {slot.capitalize()} - {val}")
        return "\n".join(lines) if len(lines) > 1 else ""

    return str(day_item).strip()


def _normalize_days(raw_optimized: Any, num_days: int, generation: dict[str, Any] | None = None) -> list[str]:
    import re

    candidate = raw_optimized
    if not candidate and generation:
        candidate = generation.get("optimized_itinerary") or generation.get("itinerary") or generation.get("days")

    raw_list: list[Any] = []
    if isinstance(candidate, dict):
        if isinstance(candidate.get("days"), list):
            raw_list = candidate["days"]
        else:
            # Handle dicts shaped like {"Day 1": "...", "Day 2": "..."}
            day_keys = [k for k in candidate.keys() if "day" in str(k).lower()]
            for dk in day_keys:
                val = candidate[dk]
                if isinstance(val, str):
                    raw_list.append(val if val.lower().startswith("day") else f"{dk}: {val}")
                else:
                    raw_list.append(val)
    elif isinstance(candidate, list):
        raw_list = candidate
    elif isinstance(candidate, str) and candidate.strip():
        chunks = re.split(r"(?=\bDay\s+\d+\s*:)", candidate.strip(), flags=re.IGNORECASE)
        raw_list = [c.strip() for c in chunks if c.strip()]

    formatted = [_format_day_entry(item, i) for i, item in enumerate(raw_list)]
    formatted = [d for d in formatted if d]
    return formatted[:num_days] if formatted else []


def _is_complete_plan(data: dict[str, Any]) -> bool:
    recs = str(data.get("aiRecommendations") or "").strip()
    days = (data.get("optimizedItinerary") or {}).get("days") or []
    valid_days = [d for d in days if isinstance(d, str) and len(d.strip()) > 25]
    return bool(recs) and len(valid_days) > 0

async def _upsert_user(user_id: str, email: str, full_name: str) -> None:
    await mongo.connect()
    email_norm = email.strip().lower()
    await mongo.collection("users").update_one(
        {"email": email_norm},
        {
            "$set": {
                "userId": user_id,
                "fullName": full_name,
                "updatedAt": datetime.now(timezone.utc),
            },
            "$setOnInsert": {"createdAt": datetime.now(timezone.utc)},
        },
        upsert=True,
    )


def _summarize_preferences(preferences: str) -> str:
    if not preferences:
        return "your travel preferences"

    normalized = preferences.lower()
    phrases = []

    # Map user preference keywords to natural-sounding summary phrases.
    # Use general categories (e.g., 'sunrise', 'falls', 'caves') instead of specific place names.
    mapping = {
        'local culture': 'local cultural experiences',
        'culture': 'local cultural experiences',
        'lakeside': 'lakeside relaxation',
        'lake': 'lakeside experiences',
        'boating': 'boating and water activities',
        'view': 'scenic viewpoints',
        'sunrise': 'sunrise viewpoints',
        'caves': 'historic caves',
        'waterfall': 'waterfall excursions',
        'falls': 'waterfall excursions',
        'history': 'local history and heritage',
        'food': 'local cuisine and dining experiences',
        'adventure': 'adventure activities',
        'premium': 'premium travel comfort',
        'luxury': 'luxury experiences',
        'beach': 'beach relaxation and activities',
        'mountain': 'mountain scenery and trekking',
        'nature': 'nature and outdoor experiences',
        'wellness': 'spa and wellness retreats',
    }

    for keyword, phrase in mapping.items():
        if keyword in normalized and phrase not in phrases:
            phrases.append(phrase)

    if not phrases:
        return "your personalized travel interests"

    return ", ".join(phrases)


async def generate_plan(*, user_id: str, email: str, full_name: str, form: dict[str, Any]) -> dict[str, Any]:
    print(f"=== PLAN GENERATION START ===")
    print(f"User ID: {user_id}")
    print(f"Email: {email}")
    print(f"Full Name: {full_name}")
    print(f"Form: {form}")
    
    await mongo.connect()
    await _upsert_user(user_id, email, full_name)
    print("MongoDB connected and user upserted")

    cache_payload = {
        "origin": form["origin"],
        "destination": form["destination"],
        "startDate": form["startDate"],
        "endDate": form["endDate"],
        "budget": form["budget"],
        "transportMode": form["transportMode"],
        "travelType": form["travelType"],
        "numberOfPeople": form["numberOfPeople"],
        "preferences": form.get("preferences", ""),
        "currency": "INR",
        "promptVersion": "v2-inr",
    }
    key = _cache_key(cache_payload)

    cached = await mongo.collection("itineraries").find_one({"cacheKey": key})
    if cached and cached.get("data") and _is_complete_plan(cached["data"]):
        itinerary_id = cached.get("itineraryId") or str(uuid.uuid4())
        data = cached["data"]
    else:
        num_days = _days_from_dates(form["startDate"], form["endDate"])
        print(f"Number of days: {num_days}")

        # Concurrently fetch all real-world data
        transport_query = f"How to travel from {form['origin']} to {form['destination']} by {form['transportMode']} price in INR and duration"
        rag_query = f"Top things to do in {form['destination']} and travel tips matching preferences: {form.get('preferences', 'general sightseeing')}"
        cost_query = f"Average daily tourist cost in {form['destination']} in INR for food, local transport, and activities"

        if form['transportMode'].lower() == 'flight':
            transport_coro = search_flights(form['origin'], form['destination'], form['startDate'])
        else:
            transport_coro = search_web(transport_query)

        print("Fetching real-time data concurrently...")
        try:
            results = await asyncio.wait_for(
                asyncio.gather(
                    get_weather_insights(form["destination"], form["startDate"], form["endDate"]),
                    search_hotels(form["destination"], form["startDate"], form["endDate"], form["numberOfPeople"]),
                    transport_coro,
                    search_web(rag_query),
                    search_web(cost_query),
                    return_exceptions=True
                ),
                timeout=15.0
            )
        except asyncio.TimeoutError:
            print("Real-time data gathering timed out after 15s. Proceeding with estimations.")
            results = [
                "Weather data unavailable.",
                "Hotel data unavailable.",
                "Transport data unavailable.",
                "General sightseeing and local highlights.",
                "Average standard tourist expenses."
            ]
        
        def _safe_str(res: Any) -> str:
            return str(res) if not isinstance(res, Exception) else "Data unavailable due to error."
            
        weather = _safe_str(results[0])
        hotels_data = _safe_str(results[1])
        transport_data = _safe_str(results[2])
        rag_data = _safe_str(results[3])
        cost_data = _safe_str(results[4])
        print(f"Weather insights: {weather[:100]}...")
        print(f"Hotels data: {hotels_data[:100]}...")
        
        prompt = _build_generation_prompt(
            form=form, 
            num_days=num_days, 
            weather=weather,
            hotels_data=hotels_data,
            transport_data=transport_data,
            rag_data=rag_data,
            cost_data=cost_data
        )
        print(f"Generated prompt ({len(prompt)} characters)")
        
        try:
            generation = await generate_json(prompt)
            print(f"AI generation successful")
            print(f"Generated keys: {list(generation.keys())}")
        except Exception as e:
            print(f"AI generation failed: {str(e)}")
            raise

        hotels = []
        for h in generation.get("hotels", [])[:10]:
            loc = h.get("location") or h.get("city") or form.get("destination", "")
            hotels.append(
                {
                    "name": h.get("name") or "Recommended Stay",
                    "price": h.get("price"),
                    "rating": h.get("rating"),
                    "location": loc or "City Center",
                    "mapsLink": h.get("mapsLink")
                    or (_google_maps_link(loc) if loc else _google_maps_link(form["destination"])),
                }
            )

        ai_recs = _normalize_ai_recommendations(
            generation.get("aiRecommendations")
            or generation.get("ai_recommendations")
            or generation.get("recommendations")
        )
        days = _normalize_days(generation.get("optimizedItinerary"), num_days, generation=generation)

        # If LLM truncated or omitted aiRecommendations / optimizedItinerary.days, run compact recovery call
        if not ai_recs or len(days) < num_days or any(len(d.strip()) <= 25 for d in days):
            print(f"[ITINERARY] Incomplete sections detected (recs={bool(ai_recs)}, days={len(days)}/{num_days}). Running compact recovery...")
            recovery_prompt = f"""
Return ONLY valid JSON with NO markdown and NO extra explanation:
{{
  "aiRecommendations": "• Tip 1 (₹X)\\n• Tip 2 (₹X)\\n• Tip 3 (₹X)\\n• Tip 4 (₹X)\\n• Tip 5 (₹X)",
  "optimizedItinerary": {{
    "days": [
      "Day 1: Title\\n• 08:00 AM - Breakfast\\n• 10:00 AM - Morning Sightseeing\\n• 01:00 PM - Local Lunch\\n• 03:30 PM - Afternoon Attraction\\n• 06:30 PM - Sunset Viewpoint\\n• 08:30 PM - Dinner"
    ]
  }}
}}

Trip Details:
- Origin: {form['origin']}
- Destination: {form['destination']}
- Dates: {form['startDate']} to {form['endDate']} ({num_days} days)
- Travel Type: {form['travelType']} ({form['numberOfPeople']} traveler(s))
- Budget: ₹{form['budget']} INR
- Preferences: {form.get('preferences') or 'balanced sightseeing, local food, top highlights'}

Requirements:
1. `aiRecommendations`: 5-7 concise tips in {form['destination']} with prices in Indian Rupees (₹), separated by `\\n• `.
2. `optimizedItinerary.days`: EXACTLY {num_days} day strings, each formatted as "Day X: Title\\n• 07:00 AM - Activity\\n• 09:30 AM - Activity\\n• 01:00 PM - Lunch\\n• 03:30 PM - Activity\\n• 06:30 PM - Evening\\n• 08:30 PM - Dinner".
"""
            try:
                recovered = await generate_json(recovery_prompt)
                if not ai_recs:
                    ai_recs = _normalize_ai_recommendations(
                        recovered.get("aiRecommendations")
                        or recovered.get("ai_recommendations")
                        or recovered.get("recommendations")
                    )
                if len(days) < num_days or any(len(d.strip()) <= 25 for d in days):
                    recovered_days = _normalize_days(recovered.get("optimizedItinerary"), num_days, generation=recovered)
                    if recovered_days:
                        days = recovered_days
            except Exception as rec_err:
                print(f"[ITINERARY] Recovery call failed: {rec_err}")

        if not days:
            days = [""] * num_days
        elif len(days) < num_days:
            days = days + [""] * (num_days - len(days))

        itinerary_id = str(uuid.uuid4())
        data = {
            "itineraryId": itinerary_id,
            "weatherInsights": generation.get("weatherInsights") or weather,
            "transportDetails": generation.get("transportDetails") or "",
            "hotels": hotels,
            "costPredictor": generation.get("costPredictor") or "",
            "aiRecommendations": ai_recs,
            "optimizedItinerary": {"days": days},
        }

        storage_cache_key = key if _is_complete_plan(data) else f"{key}-{itinerary_id}"
        await mongo.collection("itineraries").update_one(
            {"cacheKey": storage_cache_key},
            {
                "$set": {
                    "itineraryId": itinerary_id,
                    "cacheKey": storage_cache_key,
                    "userId": user_id,
                    "updatedAt": datetime.now(timezone.utc),
                    "data": data,
                }
            },
            upsert=True,
        )

    await mongo.collection("trips").insert_one(
        {
            "userId": user_id,
            "itineraryId": itinerary_id,
            "createdAt": datetime.now(timezone.utc),
            "form": {
                "origin": form["origin"],
                "destination": form["destination"],
                "startDate": form["startDate"],
                "endDate": form["endDate"],
                "budget": form["budget"],
                "transportMode": form["transportMode"],
                "travelType": form["travelType"],
                "numberOfPeople": form["numberOfPeople"],
                "preferences": form.get("preferences", ""),
            },
        }
    )

    days = data.get("optimizedItinerary", {}).get("days") or []
    # Clean up day text to avoid duplicate "Day X"
    formatted_days = []
    for i, d in enumerate(days):
        day_label = f"Day {i+1}:"
        content = d.strip()
        if content.lower().startswith(f"day {i+1}"):
            # If it already starts with "Day X:", just use it as is (normalizing colon if needed)
            formatted_days.append(content)
        else:
            formatted_days.append(f"{day_label} {content}")
    
    day_text = "\n\n".join(formatted_days)

    # Clean up recommendations to ensure bullet points
    raw_recs = data.get("aiRecommendations") or ""
    recs_list = [line.strip() for line in raw_recs.split('\n') if line.strip()]
    formatted_recs = ""
    for rec in recs_list:
        if rec.startswith(('•', '-', '*')):
            formatted_recs += f"• {rec[1:].strip()}\n"
        else:
            formatted_recs += f"• {rec}\n"

    subject = f"Your TripNova itinerary ({form['destination']})"
    preferences_summary = _summarize_preferences(form.get('preferences', ''))
    body = (
        f"Hello {full_name},\n\n"
        f"Here is your personalized {len(days)}-day travel itinerary for your trip from {form['origin']} to {form['destination']}. This plan reflects {preferences_summary}, while staying aligned with your budget and travel details. The itinerary includes memorable local experiences, comfortable transportation, and premium sightseeing recommendations tailored for your trip.\n\n"
        f"{day_text}\n\n"
        f"We hope you have an amazing time exploring {form['destination']} and creating unforgettable memories.\n\n"
        f"If you capture beautiful moments during your trip, we would love to see them. Feel free to share your travel videos with us by uploading them to any social media platform and sending us the video link through the “Share Your Trip” section on our website.\n\n"
        f"Wishing you a safe, enjoyable, and wonderful journey. \n\n"
        f"Warm regards,\nTripNova Team"
    )

    frontend_url = "https://tripwithbinod.netlify.app" if settings.is_production else settings.FRONTEND_URLS
    body_html = get_itinerary_email_html(form['destination'], body)

    email_sent = False
    try:
        print(f"Queueing email in background to: {email}")
        asyncio.create_task(send_email(email, subject, body, body_html))
        email_sent = True
        print("Email queued successfully")
    except Exception as e:
        print(f"Email queueing failed: {str(e)}")
        email_sent = False

    resp = data.copy()
    resp["itineraryId"] = itinerary_id
    resp["emailSent"] = email_sent
    resp["optimizedItinerary"] = data.get("optimizedItinerary", {})
    
    print(f"=== PLAN GENERATION COMPLETE ===")
    print(f"Response keys: {list(resp.keys())}")
    print(f"Itinerary ID: {itinerary_id}")
    print(f"Email sent: {email_sent}")
    
    return resp