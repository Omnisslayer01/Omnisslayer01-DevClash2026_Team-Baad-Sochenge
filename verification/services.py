import logging
import re
import unicodedata
from difflib import SequenceMatcher
from io import BytesIO

import boto3
import pytesseract
from django.conf import settings
from PIL import Image, ImageEnhance, ImageOps

from .models import FraudSignal, UserVerification

logger = logging.getLogger(__name__)

_NAME_LABEL_PREFIXES = (
    "name:",
    "name ",
    "nm:",
    "nm ",
)


def _normalize_person_name(value: str) -> str:
    s = unicodedata.normalize("NFKC", (value or "").strip().lower())
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    for p in _NAME_LABEL_PREFIXES:
        if s.startswith(p):
            s = s[len(p) :].strip()
    return s


def names_likely_match(user_name: str, extracted_name: str, *, min_ratio: float = 0.82) -> bool:
    """
    Case-insensitive match: substring, high token overlap (order-independent), or fuzzy ratio.
    """
    a = _normalize_person_name(extracted_name)
    b = _normalize_person_name(user_name)
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    ta, tb = set(a.split()), set(b.split())
    if ta and tb:
        union = len(ta | tb)
        if union and (len(ta & tb) / union) >= 0.55:
            return True
    return SequenceMatcher(None, a, b).ratio() >= min_ratio


def _pil_image_for_ocr(image_file) -> Image.Image:
    image_file.seek(0)
    raw = image_file.read()
    img = Image.open(BytesIO(raw))
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    gray = img.convert("L")
    gray = ImageOps.autocontrast(gray, cutoff=2)
    gray = ImageEnhance.Contrast(gray).enhance(1.35)
    gray = ImageEnhance.Sharpness(gray).enhance(1.15)
    w, h = gray.size
    if max(w, h) < 1400:
        scale = 1400 / max(w, h)
        gray = gray.resize(
            (max(1, int(w * scale)), max(1, int(h * scale))),
            Image.Resampling.LANCZOS,
        )
    return gray


_OCR_CONFIGS = (
    "--oem 3 --psm 3",
    "--oem 3 --psm 6",
    "--oem 3 --psm 4",
    "--oem 3 --psm 11",
)


def _run_tesseract_variants(gray: Image.Image) -> str:
    chunks: list[str] = []
    for cfg in _OCR_CONFIGS:
        try:
            chunks.append(pytesseract.image_to_string(gray, config=cfg))
        except pytesseract.TesseractError as exc:
            logger.warning("Tesseract config %r failed: %s", cfg, exc)
    # Optional Devanagari + Latin (common on Indian IDs); ignore if pack missing.
    try:
        chunks.append(
            pytesseract.image_to_string(gray, lang="eng+hin", config="--oem 3 --psm 6")
        )
    except pytesseract.TesseractError:
        pass
    return "\n".join(chunks)


# OCR often joins lines; allow same-line "Name: … DOB …" and multiline "Name:\nRAHUL …"
_NAME_FIELD_RES = (
    re.compile(
        r"(?is)\bname\b\s*[:\-–—]?\s*([A-Za-z][A-Za-z .'\u2019\-]{2,120}?)(?=\s*(?:\n|dob|gender|year|yob|address|father|mother|uid|aadhaar|aadhar|\d{2}[/\-]\d{2})|\s*$)",
    ),
    re.compile(r"(?is)\bname\b\s*[:\-–—]?\s*([A-Za-z][^\n]{2,100})"),
)


def _clean_captured_name(raw: str) -> str:
    s = (raw or "").strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"^[:\-–—\s]+|[:\-–—\s]+$", "", s)
    return s.strip(" .")


def _extract_name_from_ocr_text(text: str) -> str:
    if not (text or "").strip():
        return ""

    for rx in _NAME_FIELD_RES:
        m = rx.search(text)
        if m:
            candidate = _clean_captured_name(m.group(1))
            if _line_looks_like_person_name(candidate):
                logger.info("Name from labeled field: %r", candidate)
                return candidate

    exclude_words = (
        "GOVERNMENT",
        "ID",
        "CARD",
        "IDENTITY",
        "NUMBER",
        "DATE",
        "BIRTH",
        "ISSUE",
        "VALID",
        "INDIA",
        "PASSPORT",
        "LICENSE",
        "AADHAAR",
        "VOTER",
        "FATHER",
        "MOTHER",
        "HUSBAND",
        "UNIQUE",
        "AUTHORITY",
        "ENROLMENT",
        "GOVT",
        "MALE",
        "FEMALE",
        "ADDRESS",
        "PIN",
        "STATE",
        "DISTRICT",
    )
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    candidates: list[str] = []
    for line in lines:
        line_upper = line.upper()
        if any(x in line_upper for x in ("S/O", "D/O", "W/O", "C/O")):
            continue
        if not _line_looks_like_person_name(line):
            continue
        if any(w in line_upper for w in exclude_words):
            continue
        if len(line) >= 3:
            candidates.append(line)

    if candidates:
        with_spaces = [c for c in candidates if " " in c]
        chosen = with_spaces[0] if with_spaces else candidates[0]
        logger.info("Name from heuristic line: %r", chosen)
        return _clean_captured_name(chosen)

    return ""


def _line_looks_like_person_name(line: str) -> bool:
    letters = sum(1 for c in line if c.isalpha())
    digits = sum(1 for c in line if c.isdigit())
    if letters < 3:
        return False
    if digits > max(2, letters // 4):
        return False
    return True


def _extract_masked_id(text: str) -> str:
    exclude_words = {
        "GOVERNMENT",
        "ID",
        "CARD",
        "IDENTITY",
        "NUMBER",
        "DATE",
        "BIRTH",
        "ISSUE",
        "VALID",
        "INDIA",
        "PASSPORT",
        "LICENSE",
        "AADHAAR",
        "VOTER",
    }
    id_pattern = re.compile(r"[A-Z0-9]{8,15}")
    matches = id_pattern.findall(text.upper())
    for raw_id in matches:
        if raw_id not in exclude_words:
            return f"****{raw_id[-4:]}" if len(raw_id) > 4 else raw_id
    return ""


def extract_id_data(image_file):
    """
    Extracts text from ID image using Tesseract OCR (multi-PSM + optional eng+hin).
    Parses full name (labeled fields first) and masks ID-like strings.
    """
    try:
        gray = _pil_image_for_ocr(image_file)
        text = _run_tesseract_variants(gray)
        logger.debug("Tesseract OCR merged length=%s", len(text))

        extracted_name = _extract_name_from_ocr_text(text)
        masked_id = _extract_masked_id(text)
        if masked_id:
            logger.info("Found ID match: %s", masked_id)

        return extracted_name, masked_id
    except Exception as e:
        logger.error("OCR Error: %s", e)
        return "", ""

def _compare_faces_once(client, source_bytes: bytes, target_bytes: bytes) -> float:
    response = client.compare_faces(
        SourceImage={"Bytes": source_bytes},
        TargetImage={"Bytes": target_bytes},
        SimilarityThreshold=0,
    )
    face_matches = response.get("FaceMatches") or []
    if not face_matches:
        return 0.0
    return max(float(m["Similarity"]) for m in face_matches)


def compare_faces(id_image_bytes, selfie_image_bytes):
    """
    Compare ID portrait vs selfie via configured cloud face API.
    Tries ID→selfie and selfie→ID (selfie often yields a clearer source face).
    """
    if not id_image_bytes or not selfie_image_bytes:
        logger.error("Empty image bytes provided for face comparison")
        return 0.0

    try:
        client = boto3.client(
            "rekognition",
            aws_access_key_id=getattr(settings, "AWS_ACCESS_KEY_ID", None) or None,
            aws_secret_access_key=getattr(settings, "AWS_SECRET_ACCESS_KEY", None) or None,
            region_name=getattr(settings, "AWS_REGION", "us-east-1"),
        )

        sim_id_source = _compare_faces_once(client, id_image_bytes, selfie_image_bytes)
        sim_selfie_source = _compare_faces_once(client, selfie_image_bytes, id_image_bytes)
        similarity = max(sim_id_source, sim_selfie_source)
        if similarity > 0:
            return similarity

        id_faces = client.detect_faces(Image={"Bytes": id_image_bytes})
        selfie_faces = client.detect_faces(Image={"Bytes": selfie_image_bytes})
        if not id_faces.get("FaceDetails"):
            logger.warning("Face comparison: no face detected in ID image")
        if not selfie_faces.get("FaceDetails"):
            logger.warning("Face comparison: no face detected in selfie image")
        if not getattr(settings, "AWS_ACCESS_KEY_ID", None) or not getattr(
            settings, "AWS_SECRET_ACCESS_KEY", None
        ):
            logger.warning("Face comparison: cloud credentials not configured")

        return 0.0
    except Exception:
        logger.error("Face comparison failed")
        return 0.0

def calculate_verification_confidence(face_similarity, liveness_passed, name_match):
    """Score: face >90 → +50, liveness → +20, name_match → +20 (max 90 from rules)."""
    confidence = 0
    if face_similarity > 90:
        confidence += 50
    if liveness_passed:
        confidence += 20
    if name_match:
        confidence += 20
    return min(100, confidence)

def verify_identity_pipeline(user, id_image, selfie_image, liveness_passed, user_name, pre_extracted_name=None, pre_masked_id=None):
    """
    Secure backend identity verification pipeline.
    """
    # 1. Immediate rejection if liveness failed
    if not liveness_passed:
        logger.warning(f"Liveness failed for user {user.username}")
        verification = UserVerification.objects.create(
            user=user,
            id_image=id_image,
            selfie_image=selfie_image,
            liveness_passed=False,
            is_identity_verified=False,
            verification_confidence=0
        )
        return verification

    # 2. OCR Extraction (Use pre-extracted if available)
    if pre_extracted_name is not None:
        extracted_name = pre_extracted_name
        masked_id_number = pre_masked_id if pre_masked_id is not None else ""
        if not (extracted_name or "").strip():
            extracted_name, masked_id_number = extract_id_data(id_image)
        logger.info(f"Using pre-processed ID for user {user.username}: {extracted_name!r}")
    else:
        extracted_name, masked_id_number = extract_id_data(id_image)
        logger.info(f"Extracted OCR for user {user.username}: {extracted_name}")
    
    # 3. Face Matching
    id_image.seek(0)
    selfie_image.seek(0)
    id_bytes = id_image.read()
    selfie_bytes = selfie_image.read()
    
    face_similarity = compare_faces(id_bytes, selfie_bytes)

    id_image.seek(0)
    selfie_image.seek(0)
    
    # 4. Name matching (substring + token overlap + fuzzy ratio)
    name_match = bool(
        extracted_name and user_name and names_likely_match(user_name, extracted_name)
    )
    if extracted_name or user_name:
        logger.info(
            "Name match for %s: %s (profile=%r, ocr=%r)",
            user.username,
            name_match,
            user_name,
            extracted_name,
        )
        
    # 5. Confidence Score
    confidence = calculate_verification_confidence(face_similarity, liveness_passed, name_match)
    
    # 6. Final Decision
    is_verified = (face_similarity > 90 and liveness_passed and name_match)
    logger.info(f"Final verification for {user.username}: {is_verified} (Confidence: {confidence}%)")
    
    # 7. Store Result
    verification = UserVerification.objects.create(
        user=user,
        id_image=id_image,
        selfie_image=selfie_image,
        extracted_name=extracted_name,
        masked_id_number=masked_id_number,
        face_similarity=face_similarity,
        liveness_passed=liveness_passed,
        name_match=name_match,
        verification_confidence=confidence,
        is_identity_verified=is_verified,
    )

    if liveness_passed and face_similarity > 90 and not name_match:
        FraudSignal.objects.create(
            signal_type=FraudSignal.SIGNAL_NAME_MISMATCH,
            severity="medium",
            detail={
                "user_id": user.id,
                "username": user.username,
                "submitted_name": user_name,
                "extracted_name": extracted_name,
            },
        )

    # 8. Update User model if verified
    if is_verified:
        user.is_verified = True
        user.is_verified_human = True
        # If Profile exists, update it too (based on project patterns)
        if hasattr(user, "profile"):
            user.profile.is_gov_id_verified = True
            user.profile.is_verified_user = True
            user.profile.save()
        user.save()
    
    return verification
