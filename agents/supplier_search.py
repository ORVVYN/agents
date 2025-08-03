import os
from typing import List, Dict
import logging
from serpapi import GoogleSearch
import json
from dotenv import load_dotenv
from sqlalchemy.orm import Session

from db.models import Supplier

load_dotenv()

SERP_API_KEY = os.getenv("SERP_API_KEY")

if not SERP_API_KEY:
    raise RuntimeError("SERP_API_KEY is not set in environment")


def _has_contacts(item: Dict) -> bool:
    """Return True if item contains at least phone, email, or website."""
    return bool(item.get("phone") or item.get("website") or item.get("email"))


def _normalize_phone(raw: str | None) -> str | None:
    if not raw:
        return None
    digits = "".join(c for c in raw if c.isdigit() or c == "+")
    return digits or None


def _fetch_details(place_id: str) -> Dict:
    """Fetch detailed info for a place via SerpApi google_local with place_id."""
    params = {
        "engine": "google_local",
        "api_key": SERP_API_KEY,
        "place_id": place_id,
        "hl": "ru",
        "gl": "ru",
    }
    return GoogleSearch(params).get_dict()


def _extract_contacts(text_blob: str) -> Dict[str, str | None]:
    """Very simple regex-based extraction for phone/email/whatsapp from arbitrary text."""
    import re
    phone_match = re.search(r"(\+?\d[\d\s\-()]{6,}\d)", text_blob)
    email_match = re.search(r"[\w.-]+@[\w.-]+", text_blob)
    # WhatsApp numbers usually same as phone; if 'WhatsApp' word present mark whatsapp
    whatsapp = None
    if "whatsapp" in text_blob.lower() and phone_match:
        whatsapp = phone_match.group(1)
    return {
        "phone": phone_match.group(1) if phone_match else None,
        "email": email_match.group(0) if email_match else None,
        "whatsapp": whatsapp,
    }


def validated_search(term: str, city: str, session: Session, max_rounds: int = 2) -> List[Supplier]:
    """Iteratively search until suppliers with contact info are found.

    We tweak the query adding keywords like "контакты", "телефон", "email".
    """
    postfixes = ["", " контакты", " телефон email"]
    tried_terms: list[str] = []
    logger = logging.getLogger(__name__)
    for round_idx in range(min(max_rounds, len(postfixes))):
        q = term + postfixes[round_idx]
        tried_terms.append(q)
        logger.info(f"SerpAPI google_local query='{q}', location='{city}'")
        params = {
            "engine": "google_local",
            "q": q,
            "location": city or "Russia",
            "api_key": SERP_API_KEY,
            "google_domain": "google.com",
            "hl": "ru",
            "gl": "ru",
            "num": 20,
        }
        results = GoogleSearch(params).get_dict()
        local_results = results.get("local_results", [])
        if not local_results and city:
            # fallback: try same query without explicit location (city already in q)
            params_no_loc = params.copy()
            params_no_loc.pop("location", None)
            logger.info("Fallback search without location param (GoogleSearch)")
            results = GoogleSearch(params_no_loc).get_dict()
            local_results = results.get("local_results", [])
        if not local_results:
            # Raw HTTP request as additional fallback / debug
            import httpx
            logger.info("Raw HTTP GET to SerpApi as fallback")
            try:
                raw_resp = httpx.get("https://serpapi.com/search.json", params=params, timeout=20)
                logger.info("Raw SerpApi status %s", raw_resp.status_code)
                if raw_resp.status_code == 200:
                    raw_data = raw_resp.json()
                    local_results = raw_data.get("local_results", [])
            except Exception as e:
                logger.exception("Raw SerpApi request failed: %s", e)
        # Enrich each result via place_id details
        for item in local_results:
            print(item)
            pid = item.get("place_id")
            if pid:
                detail = _fetch_details(pid)
                details_blob = json.dumps(detail)
                contacts = _extract_contacts(details_blob)
                # merge if not present
                if not item.get("phone") and contacts["phone"]:
                    item["phone"] = contacts["phone"]
                if not item.get("website") and contacts["email"]:
                    item["email"] = contacts["email"]
                item["whatsapp"] = contacts["whatsapp"]
        # Filter items with contacts
        contacts_items = [it for it in local_results if _has_contacts(it)]
        if contacts_items:
            suppliers: list[Supplier] = []
            for item in contacts_items:
                name = item.get("title") or ""
                if not name:
                    continue
                supplier = (
                    session.query(Supplier)
                    .filter_by(name=name, category=term, city=city)
                    .first()
                )
                if not supplier:
                    supplier = Supplier(
                        name=name,
                        category=term,
                        address=item.get("address"),
                        phone=_normalize_phone(item.get("phone")),
                        email=None,  # SerpApi rarely gives email; placeholder
                        website=item.get("website"),
                        city=city,
                        source_query=q,
                    )
                    session.add(supplier)
                    session.flush()
                               # Update missing fields if new info available
                updated = False
                for field in ["address", "phone", "email", "website", "whatsapp"]:
                    new_val = None
                    if field == "address":
                        new_val = item.get("address")
                    elif field == "phone":
                        new_val = _normalize_phone(item.get("phone"))
                    else:
                        new_val = item.get(field)
                    if new_val and not getattr(supplier, field):
                        setattr(supplier, field, new_val)
                        updated = True
                if updated:
                    session.flush()
                suppliers.append(supplier)
            session.commit()
            return suppliers
    # Nothing found
    return []

# Backward compatibility wrapper
def search_suppliers(term: str, session: Session, city: str = "") -> List[Supplier]:
    return validated_search(term, city, session)
