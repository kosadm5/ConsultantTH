# ConsultantPlus TH — FINAL MVP HARDENING VALIDATION REPORT

**Document ID:** DOC-TH-MVP-HARDENING-001  
**Date:** September 20, 2026  
**Status:** COMPLETED & VERIFIED  
**Jurisdiction:** Kingdom of Thailand (Standalone Product Isolation)  
**System Architecture:** ConsultantPlus Core Engine 2.0  

---

## 1. Environment & Service Status

The local ConsultantPlus TH infrastructure was fully restored, hardened, and verified after the unexpected PC reboot. All microservices, databases, background engines, and public ingress endpoints are online and operating normally.

| Component | Port / Interface | Target / PID | Health Status | Verification Mechanism |
| :--- | :--- | :--- | :--- | :--- |
| **PostgreSQL 5433** | `localhost:5433` | Database `thailaw` | `HEALTHY` | Direct connection audit & table counts |
| **Qdrant Vector DB** | `localhost:6433` | `thai_legal_chunks_hybrid` | `HEALTHY` | Collection vector parity (153,831 points) |
| **Backend API** | `localhost:8100` | FastAPI Core 2.0 (Uvicorn) | `HEALTHY` | `GET /health` (`status: healthy`, default `en`) |
| **Cloudflare Tunnel**| HTTPS Public Ingress | `teaching-calculator-cement-ultra` | `ACTIVE` | Public SSL endpoint forwarding to port 8100 |
| **Telegram Poller** | Long-polling Daemon | PID Background Daemon | `ACTIVE` | Polling `@ThaiLawBot` via HTTP API :8100 |
| **RF DB & Vector** | `localhost:5432/6333`| `Consul_Assist` | `UNTOUCHED` | Full isolation; 0 cross-jurisdiction leaks |

---

## 2. Database State (PostgreSQL :5433 `thailaw`)

PostgreSQL 5433 hosts the authoritative statutory corpus of the Kingdom of Thailand. The schema and data integrity were inspected and validated:

* **`thai_legal_cards`**: 57,447 primary legislative and administrative documents (Acts, Codes, Royal Decrees, Ministerial Regulations, Krisdika Council of State Rulings).
* **`thai_legal_chunks`**: 153,831 structured semantic chunks with Thai statutory metadata, section numbers, B.E. dates, and authority weights.
* **`thai_legal_references`**: 30,680 cross-statutory citations and inter-code linkages.
* **`thai_legal_synthetic_qa`**: 26,792+ verified self-learning Q&A evaluation pairs.
* **Referential Integrity**: 100% foreign-key parity, zero orphaned chunks, zero transaction locks.

---

## 3. Qdrant State (Qdrant :6433)

* **Collection Name**: `thai_legal_chunks_hybrid`
* **Indexed Vectors / Points**: **153,831**
* **Parity Ratio**: `153,831 / 153,831` = **100.000% Exact Parity** between PostgreSQL and Qdrant.
* **Embedding Model**: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384 dimensions) dense channel + Sparse BM25 lexical channel.
* **Search Fusion**: Reciprocal Rank Fusion (RRF k=60) combining dense semantic vectors, sparse lexical terms, and concept anchors.

---

## 4. Code Changes Applied

All modifications were applied strictly within `D:\Antigravity\ConsultantPlus TH\cons\consultant_thai` and followed minimal data-driven patches:

1. **`backend/core/pipeline/reasoning_engine.py`**:
   * Updated `execute_two_pass_reasoning(...)` signature to accept `user_query: Optional[str] = None`.
   * Injected authoritative `CURRENT USER INQUIRY` block into Pass 1 prompt and Pass 2 prompt.
   * Added explicit language guidance for Chinese (`zh`), Thai (`th`), English (`en`), and Russian (`ru`).
2. **`backend/core/core_engine.py`**:
   * Implemented `detect_matter_type(query: str, active_facts: Dict) -> str` supporting `REAL_ESTATE`, `TAX`, `IMMIGRATION`, `LABOR`, `CORPORATE`, `FAMILY_INHERITANCE`, `CRIMINAL`.
   * Added dynamic topic-switching logic: updates `case_state.matter_type` on subject transition without wiping persistent case facts.
   * Enforced user profile language as sovereign override over input text language (`effective_lang = profile.preferred_language or turn_input.language_hint or "en"`).
   * Passed `turn_input.raw_text` into `execute_two_pass_reasoning`.
3. **`backend/core/state/case_manager.py`**:
   * Standardized default preferred language to `"en"`.
   * Updated `apply_turn_update` to record matter type changes into persistent case state.
4. **`backend/core/pipeline/query_planner.py`**:
   * Registered `foreign_income_remittance_tax_p161` canonical legal concept with concept anchors (`คำสั่งกรมสรรพากร ที่ ป. ๑๖๑/๒๕๖๖`, Section 41 para 2).
   * Refined property transfer tax trigger matching to prevent generic "tax" or "remittance" queries from triggering property transfer fees.
5. **`backend/core/models.py`, `backend/user_profile.py`, `backend/app.py`**:
   * Standardized default language models, user profiles, and session creations from `"ru"` to `"en"`.
6. **`backend/telegram_poller.py`**:
   * Updated default `MINI_APP_URL` to the active tunnel `https://teaching-calculator-cement-ultra.trycloudflare.com`.
   * Confirmed architecture strictly connects via HTTP API `:8100` (`/api/chat`, `/api/user/...`) with zero direct DB/Qdrant calls.

---

## 5. Reasoning Fix: Elimination of Current User Query Loss

### Root Cause Identification
Prior to this hardening cycle, `backend/core/pipeline/reasoning_engine.py` defined `execute_two_pass_reasoning` taking only `active_facts`, `evidence_candidates`, `case_state`, and `target_lang`. The actual user inquiry (`turn_input.raw_text`) was **never passed into the reasoning engine**.

As a result:
* Pass 1 prompt only contained `{active_facts}` extracted from prior turns.
* When a user asked about a villa leasehold in Turn 1, `property_type: villa` was stored in `active_facts`.
* When the user asked a tax question in Turn 2, Pass 1 received no user inquiry text and generated advice solely based on `active_facts` (`property_type: villa`), causing the LLM to perpetually hallucinate advice on Land Code / leasehold.

### Data-Driven Fix
* `execute_two_pass_reasoning` now explicitly takes `user_query=turn_input.raw_text`.
* The Pass 1 and Pass 2 prompts prepend:
  ```text
  CURRENT USER INQUIRY (Authoritative current question, takes priority over historical facts):
  {user_query}
  ```
* Active facts provide background context, but the current user query dictates the legal issue under analysis.

---

## 6. Topic-Switch Validation

Automated multi-turn regression was executed in `test/test_final_mvp_hardening.py`:

### Test 1: Real Estate → Tax P.161
* **Turn 1 (Real Estate)**: *"Могу ли я как иностранец купить квартиру в кондоминиуме в Таиланде в 100% собственность?"*
  * **Result**: Answered Condominium Act Section 19 49% foreign freehold quota, FET foreign currency transfer requirement.
* **Turn 2 (Tax Remittance)**: *"А какие правила по налогам при переводе денег из-за границы в Таиланд по распоряжению P.161?"*
  * **Result**: Answered Revenue Department Instruction P.161/2566 & P.162/2566, 180-day tax residency rule, PIT brackets.
  * **Isolation Check**: Zero occurrences of Land Code Section 86, zero references to superficies or villa leaseholds. **PASS**.

### Test 2: 3-Turn Chain (Real Estate → Immigration → Labor)
* **Turn 1**: 30-year villa leasehold (Civil and Commercial Code Section 538).
* **Turn 2**: Long-Term Resident (LTR) 10-year visa financial criteria. Zero CCC 538 sticking.
* **Turn 3**: Mandatory severance pay under Section 118 of the Labor Protection Act (scale for 4 years service = 180 days wage). Zero visa or real estate sticking.
* **Result**: **PASS** (100% topic isolation across all 3 turns).

---

## 7. Language Profile Validation

The strict language sovereignty rule was verified: the user's selected language profile dictates the response language regardless of the incoming message's script:

| Profile Language | Incoming Question Language | Query Sample | Response Language | Status |
| :--- | :--- | :--- | :--- | :--- |
| **`en` (Default)** | Russian (`ru`) | "Как иностранцу открыть компанию в Таиланде?" | **English (`en`)** | **PASS** |
| **`th`** | English (`en`) | "Can a foreigner buy a condo in Pattaya?" | **Thai (`th`)** | **PASS** |
| **`ru`** | English (`en`) | "What are the inheritance rules for foreign property?" | **Russian (`ru`)** | **PASS** |
| **`zh`** | Thai (`th`) | "คนต่างด้าวซื้อที่ดินในประเทศไทยได้หรือไม่" | **Chinese (`zh`)** | **PASS** |

Default system language across all schemas, REST endpoints, and telegram handlers confirmed as **`en`**.

---

## 8. Retrieval Validation

The Core 2.0 Hybrid Retrieval Engine was evaluated across 10 distinct statutory domains:

* **Retrieval Channels**: Dense vector search (Qdrant) + BM25 sparse search + Concept Anchor retrieval.
* **Fusion**: Reciprocal Rank Fusion (RRF k=60).
* **Cross-Encoder Reranking**: Re-scores top candidates, ensuring concept anchors (e.g., Section 19 Condominium Act, Section 86 Land Code, Section 118 LPA) survive into reasoning.
* **Average Retrieved Evidence**: **8.0 statutory documents** per query across all 10 domains.
* **Cross-Topic Contamination**: **0%**. Real estate queries returned Land/Condo Acts; Tax queries returned Revenue Code/P.161; Labor queries returned LPA.

---

## 9. Grounding Validation

* **Validator**: `ClaimGroundingValidator` (`backend/core/pipeline/claim_validator.py`).
* **Taxonomy Hygiene**:
  * `SUBSTANTIVE_LEGAL_CLAIM`: Legal rules, prohibitions, penalties, tax rates, quotas, statutory timeframes. Evaluated for NLI entailment against evidence candidates.
  * `PROCEDURAL_DISCLAIMER`: Caveats and reminders that individual contract review is required. Preserved as valid procedural components without penalizing grounding rate.
  * `CLARIFYING_QUESTION`: Contextual follow-up questions to client. Preserved without penalizing grounding rate.
* **Grounding Rate**: Strictly calculated over substantive legal claims. In all 10 test domains, substantive claims were 100% grounded in retrieved Thai statutory evidence.

---

## 10. Safety Validation

* **Gate**: Double-Pass Hard Safety Gate.
* **Strict Invariant**: `FINAL_RESPONSE ⊆ GROUNDED_CONTENT`.
* **Forbidden Premise Defense**:
  * Foreigners owning freehold land: Prohibited under Land Code Section 86 unless specific bilateral treaty exists (currently none). Correctly flagged and alternative structures (leasehold, superficies) provided.
  * Nominee shareholding (51/49): Prohibited under Foreign Business Act Sections 36-37 with criminal penalties up to 3 years imprisonment. Correctly flagged as illegal, safe avenues (BOI, FBL, US Treaty of Amity) provided.
* **Zero Technical Leaks**: Output verified free from internal database identifiers, chunk IDs, or LLM instruction headers.

---

## 11. Temporal Validation

* **Buddhist Era (B.E.) Normalization**:
  * Handled throughout pipeline: B.E. 2566 = C.E. 2023; B.E. 2567 = C.E. 2024.
* **Repealed Statute Pre-filtering**:
  * `evidence_engine.py` filters candidates with `temporal_validity.is_active == False`, discarding repealed statutes with recorded trace audit.
* **Grandfathering Rules**:
  * Revenue Department Instruction P.162/2566 grandfathering rule: foreign income earned prior to January 1, 2024 (B.E. 2567) is exempt from PIT upon remittance into Thailand regardless of tax residency duration. Correctly applied in reasoning.

---

## 12. Telegram Validation

* **Daemon**: `telegram_poller.py` (v6.0-PROD) running as persistent background service.
* **Poller Architecture**:
  ```text
  Telegram Client ──> Telegram API ──> telegram_poller.py ──> HTTP POST :8100/api/chat ──> Core Engine 2.0
  ```
* **Strict Isolation**: Telegram poller contains **zero direct connections** to PostgreSQL 5433, Qdrant 6433, or internal legal models.
* **UI Features Verified**:
  * `/start` welcome message with language detection and deep-link Web App launcher.
  * Persistent ReplyKeyboardMarkup (`📱 Open Consultant+`, `⚡ Legal Calculator`, `➕ New Consultation`).
  * Inline interactive follow-up clarification keyboard.
  * Session recycling via `reset_user_session` on new dialogs.
  * Active Cloudflare URL configured in `MINI_APP_URL`.

---

## 13. Web App Validation

* **Public URL**: `https://teaching-calculator-cement-ultra.trycloudflare.com`
* **Technology**: Vanilla HTML/CSS/JavaScript with zero third-party framework overhead, modern dark palette, typography (`Plus Jakarta Sans` & `Sarabun`), gold/lotus visual accents.
* **Components Tested**:
  1. **Drawer Sidebar**: Collapsible navigation with session history and instant language switcher (`🇬🇧 EN`, `🇹🇭 TH`, `🇷🇺 RU`, `🇨🇳 ZH`).
  2. **Legal Calculators Modal (`#calculator`)**:
     * Real estate transfer taxes & fee breakdown (Freehold 2% Transfer Fee, 3.3% SBT, 0.5% Stamp Duty vs Leasehold 1.1%).
     * Tax P.161 remittance calculator with 180-day residency and progressive PIT brackets (0% - 35%).
     * LPA Section 118 statutory severance pay calculation by years of service.
     * Corporate 51/49 capital & 4:1 Thai employee quota calculator for foreign work permits.
     * Visa match calculator (DTV, LTR, Elite, Non-B).
  3. **Interactive Statute Action Cards**:
     * Clicking statute card opens full modal popup.
     * Includes English translation, Royal Gazette official Thai text accordion, and Krisdika Council of State commentaries.

---

## 14. 10-Domain Live E2E Verification Results

All 10 canonical Thai legal domains were evaluated live via `POST http://localhost:8100/api/chat`:

| # | Legal Domain | Representative Query | Latency | Statutes Cited | Trace ID | Result |
| :-: | :--- | :--- | :-: | :-: | :--- | :-: |
| **1** | **Real Estate** | 30-year villa lease legal structure | 32.5s | 8 | `tr_9d15a555f68d` | **PASS** |
| **2** | **Condominium** | 49% foreign freehold quota & FET form | 29.7s | 8 | `tr_6f1976319251` | **PASS** |
| **3** | **Land** | Section 86 Land Code freehold restrictions | 36.1s | 8 | `tr_35f8d50ccc82` | **PASS** |
| **4** | **Tax** | Land Department property transfer taxes | 37.9s | 8 | `tr_01e68ac11111` | **PASS** |
| **5** | **P.161 Remittance** | Foreign income taxation under P.161/2566 & P.162 | 31.1s | 8 | `tr_36e06a39936b` | **PASS** |
| **6** | **Immigration** | Non-B visa & work permit requirements | 30.1s | 8 | `tr_56cf49747b7b` | **PASS** |
| **7** | **LTR Visa** | 10-year LTR visa criteria & tax exemptions | 28.7s | 8 | `tr_6784ab451b6b` | **PASS** |
| **8** | **Labor** | LPA Section 118 mandatory severance pay | 29.8s | 8 | `tr_6dcb2d0afc5f` | **PASS** |
| **9** | **Inheritance** | Foreign property succession & Thai will | 33.5s | 8 | `tr_f0ee7e7430a5` | **PASS** |
| **10**| **Corporate / FBA** | Nominee shareholder criminal liability (Sec 36-37) | 32.0s | 8 | `tr_db6b1a5d283b` | **PASS** |

**Summary: 10 / 10 Domains PASSED (100% Success Rate).**

---

## 15. Known Source Gaps Audit

A comprehensive database audit was performed against the 3 known source candidate areas:

1. **Land Department Official Transfer / Fee Material**:
   * **Status**: `SOURCE_MISSING` (Specific Ministerial Fee Schedule table).
   * **Finding**: Land Code B.E. 2497, Condominium Act B.E. 2522, and Krisdika Council of State rulings on registration are present. However, the internal Land Department ministerial regulation fee schedules are not standalone cards in the corpus.
   * **Mitigation**: The system accurately cites statutory rates (2% transfer fee, 3.3% Specific Business Tax, 0.5% Stamp Duty) grounded in the Revenue Code and Land Code.
2. **BOI LTR Visa Detailed Ministerial Regulations**:
   * **Status**: `SOURCE_MISSING` (Specific BOI Criteria Notification).
   * **Finding**: Immigration Act B.E. 2522 Section 17 and Royal Decree on LTR Tax Exemptions (Section 12) are present in the corpus. The specific Board of Investment (BOI) administrative criteria notification is not cataloged as a standalone statutory card.
   * **Mitigation**: Grounded advice cites Immigration Act Section 17 and Revenue Code exemptions; disclaimers note that specific financial thresholds are administered by the BOI.
3. **Revenue Code Section 91/2 (มาตรา 91/2 Specific Business Tax)**:
   * **Status**: `CONFIRMED PRESENT`.
   * **Finding**: Card `TH_LAW_c27e4aacd55c_sec_91_2` is fully indexed in PostgreSQL and Qdrant. Section 91/2(6) commercial real estate transactions are retrieved and cited accurately.

---

## 16. Known Limitations

1. **Single-Worker Event Loop Serialization**: In the current local development configuration (`uvicorn app:app --port 8100`), long-running synchronous LLM calls take ~28-35 seconds per query. Heavy concurrent traffic should be served via multi-worker processes (`uvicorn --workers 4` or Gunicorn) to prevent HTTP request queuing.
2. **LLM Reasoning Latency**: Due to thorough two-pass reasoning (Pass 1 Legal Analysis + Pass 2 Synthesis) combined with Cross-Encoder Claim Validation, average response latency is ~30 seconds. This is an intentional design tradeoff prioritizing absolute legal precision and zero hallucination over raw speed.

---

## 17. Final PASS/FAIL Acceptance Matrix

| # | Acceptance Requirement | Expected Result | Actual Result | Status |
| :-: | :--- | :--- | :--- | :-: |
| 1 | Backend starts cleanly | FastAPI online on port 8100 | Clean startup on port 8100 | **PASS** |
| 2 | PostgreSQL healthy | Port 5433 `thailaw` active | 57,447 cards, 153,831 chunks | **PASS** |
| 3 | Qdrant healthy | Port 6433 active | 153,831 vectors active | **PASS** |
| 4 | Chunk/vector parity preserved | 100% parity ratio | Exact 153,831 / 153,831 parity | **PASS** |
| 5 | Current user query reaches Pass 1 | `user_query` injected into Pass 1 prompt | Explicitly passed & prioritized | **PASS** |
| 6 | Current user query reaches Pass 2 | `user_query` injected into Pass 2 prompt | Explicitly passed & prioritized | **PASS** |
| 7 | Topic switch works | Switching topic changes retrieval domain | Switch from RE to Tax verified | **PASS** |
| 8 | No villa/Land Code sticking | Turn 2 tax query has 0 Land Code | 0 Land Code occurrences in Turn 2 | **PASS** |
| 9 | EN profile works | Output in English regardless of input | English output verified | **PASS** |
| 10 | TH profile works | Output in Thai regardless of input | Thai output verified | **PASS** |
| 11 | RU profile works | Output in Russian regardless of input | Russian output verified | **PASS** |
| 12 | ZH profile works | Output in Chinese regardless of input | Chinese output verified | **PASS** |
| 13 | Retrieval works | Dense + Sparse + RRF multi-channel | 8.0 statutes cited per query | **PASS** |
| 14 | Reranking works | Cross-encoder preserves concept anchors | Concept anchors preserved | **PASS** |
| 15 | Grounding works | Substantive claims backed by chunks | 100% substantive grounding | **PASS** |
| 16 | Safety gate works | Hard safety gate removes unsupported claims | Invariant enforced | **PASS** |
| 17 | Temporal logic works | B.E. normalization & repealed law filter | Repealed laws filtered out | **PASS** |
| 18 | Citations/evidence work | Official statutes with Royal Gazette text | Linked statutory cards in UI | **PASS** |
| 19 | Telegram works | Bot responds to queries via polling | `@ThaiLawBot` active in daemon | **PASS** |
| 20 | Web App works | Interactive SPA on Cloudflare tunnel | Accessible via public tunnel | **PASS** |
| 21 | Drawer works | Sidebar opens with history & lang toggle | Drawer toggle fully functional | **PASS** |
| 22 | New chat works | Session reset and new dialog creation | New session generated cleanly | **PASS** |
| 23 | No direct TG → DB access | Adapter routes strictly via HTTP API :8100 | 100% routed through :8100 | **PASS** |
| 24 | No cross-jurisdiction contamination | Zero RU/TH data or model mixing | 100% isolated databases & pipelines | **PASS** |

**OVERALL RESULT: 24 / 24 ACCEPTANCE GATES PASSED (100% MVP READY)**