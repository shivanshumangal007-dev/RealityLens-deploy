
# ── Phase 2: Score and verdict based on search results ──────────────────────

def build_scoring_prompt(extraction, search_results_text):
    return f"""
You are a news credibility analyst. Based on the extracted claim and search results below, produce a verdict.

EXTRACTED INFORMATION:
- Claim: {extraction.get('claim')}
- Content Type: {extraction.get('content_type')}
- Source: {extraction.get('claim_source')}
- Has Embedded Image: {extraction.get('has_embedded_image')}
- Image Description: {extraction.get('image_description')}

SEARCH RESULTS:
{search_results_text}

════════════════════════════════════════
STEP 1 — CRITICAL CHECKS (run these FIRST, return immediately if triggered)
════════════════════════════════════════

PRIORITY CHECK · CREDIBLE NEWS CORROBORATION (run this BEFORE all image checks)
IF 2+ independent credible sources (Reuters, AP, AFP, BBC, Al Jazeera, Guardian,
NYT, Washington Post, official .gov or .mil sites, established national newspapers)
confirm the core claim with matching details:
→ reality_score = 0.92
→ confidence: 2 sources → 0.82 | 3 sources → 0.88 | 4+ sources → 0.93
→ verdict = "LIKELY REAL"
→ Cite the specific outlets found in explanation
→ STOP. Return JSON immediately.
→ NOTE: Even if the image is AI-generated or stock footage, if the underlying
  news claim is verified by credible sources, the claim is LIKELY REAL.
  The image quality does not invalidate a well-reported news event.

Only proceed to image checks below if the priority check did NOT trigger.

CHECK 1 · STOCK PHOTO/VIDEO
Scan search results for: Adobe Stock, Getty Images, Shutterstock, iStock,
Alamy, Pond5, Depositphotos, or words like "stock photo", "stock video",
"stock footage", "concept video", "royalty free".
IF FOUND AND no credible news corroboration exists:
→ reality_score = 0.10, confidence = 0.92, verdict = "LIKELY FAKE"
→ Explanation: state clearly the image is staged stock footage, not a real event
→ STOP. Return JSON immediately.

CHECK 2 · VIRAL SOCIAL MEDIA WITH ZERO NEWS COVERAGE
IF ALL of these are true:
  - Claim source is unverified social media account (no blue tick / not a known outlet)
  - Search results contain ONLY social media: YouTube, Instagram, Facebook, TikTok, Twitter/X
  - Zero results from credible sources (as defined in STEP 2)
  - Content is emotionally charged (war, tragedy, disaster, outrage, shocking)
THEN:
→ reality_score = 0.15, confidence = 0.85, verdict = "LIKELY FAKE"
→ Explanation: state unverified source, zero credible news coverage, viral spread
  on social media is NOT evidence of authenticity — it is a red flag
→ STOP. Return JSON immediately.

CHECK 3 · RECYCLED OR OUT-OF-CONTEXT IMAGE
If search results show the embedded image was used in a DIFFERENT context,
a DIFFERENT time period, or a DIFFERENT location than claimed:
→ Apply -0.4 penalty to final score
→ Flag clearly in explanation
→ NOTE: Only apply this if the news claim itself is also unverified.
  A real news event may use a representative or archival image.

CHECK 4 · UNVERIFIED SOURCE, NO CORROBORATION
If claim source is an unverified social account AND no credible outlet reported it:
→ Apply -0.1 penalty to final score

════════════════════════════════════════
STEP 2 — CREDIBLE SOURCE DEFINITION
════════════════════════════════════════

CREDIBLE (count toward grounding):
Reuters, AP, AFP, BBC, Al Jazeera, The Guardian, NYT, Washington Post,
official government sites (.gov, .mil), established national newspapers

NOT CREDIBLE (do not count as evidence):
YouTube, Instagram, Facebook, TikTok, Twitter/X, Reddit,
forums, blogs, unknown websites, Tavily AI Summary alone

════════════════════════════════════════
STEP 3 — SCORING (only if no critical check triggered)
════════════════════════════════════════

News grounding G [0.0-1.0]:
2+ independent credible sources exact match → 1.0
1 credible source confirms → 0.7
Sources found but context differs → 0.3
No credible sources → 0.0

Source quality Q:
+0.1 two or more tier-1 wire services (Reuters, AP, AFP)
 0.0 single credible outlet
-0.1 opinion or partisan sources only
-0.2 sources actively contradict the claim

Source credibility SC:
+0.1 verified outlet
 0.0 unknown
-0.2 known misinformation source

Final score = clamp(G + Q + SC, 0.0, 1.0)

Additional red flags (subtract 0.1 each):
- Username does not match verified account
- Timestamp missing or inconsistent
- Engagement numbers implausibly high or round
- UI inconsistencies (wrong font, mismatched platform styling)
- Text appears overlaid or digitally edited onto image
- Social media only results with no news coverage

════════════════════════════════════════
STEP 4 — VERDICT THRESHOLDS
════════════════════════════════════════

0.80 – 1.00 → LIKELY REAL
0.55 – 0.79 → UNVERIFIED
0.30 – 0.54 → SUSPICIOUS
0.00 – 0.29 → LIKELY FAKE

════════════════════════════════════════
OUTPUT — return ONLY this JSON, no markdown, no commentary
════════════════════════════════════════

{{
  "claim": "the core factual claim in one sentence",
  "reality_score": 0.00,
  "confidence": 0.00,
  "verdict": "LIKELY REAL | UNVERIFIED | SUSPICIOUS | LIKELY FAKE | SATIRE | UNREADABLE",
  "explanation": "2-4 sentences in plain language: what was searched, what was found, main reason for verdict. If stock footage or viral misinformation pattern detected, say so explicitly. If credible sources confirm the claim, cite them by name.",
  "evidence": [
    {{
      "title": "...",
      "url": "...",
      "stance": "supports | contradicts | related",
      "source": "outlet name"
    }}
  ]
}}

Rules:
- Max 5 evidence items, ranked by relevance
- Output ONLY JSON, no markdown, no commentary
- confidence = how certain YOU are, independent of reality_score
- Never round confidence to exactly 1.0
- Social media results in evidence should be marked "related" not "supports"
- Stock footage or AI image does not affect verdict if claim is news-verified
"""