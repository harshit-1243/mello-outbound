"""Small shared helpers for the booking engine."""
from __future__ import annotations


def normalize_phone(phone: str) -> str:
    """Reduce a phone number to comparable digits, dropping +91 / leading 0 and separators.

    Exotel delivers caller IDs like ``+919876543210`` while a facility may store ``9876543210``;
    both must match the same member.
    """
    digits = "".join(ch for ch in phone if ch.isdigit())
    if digits.startswith("91") and len(digits) > 10:
        digits = digits[2:]
    return digits.lstrip("0")
