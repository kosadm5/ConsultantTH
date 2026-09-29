"""
backend/core/pipeline/query_planner.py
Consultant+ Core Engine 2.0 — Issue-Based Multilingual Query Planner.
Derives abstract legal issues from user message and active case facts.
Maps detected legal issues to canonical legal concepts to supply targeted
dense and lexical search anchors in English and Thai WITHOUT global hardcoding.
"""

from typing import List, Dict, Any, Optional
from core.models import QueryPlan, LegalIssue, LegalCaseState
from core.gateway import ModelGateway


CANONICAL_LEGAL_CONCEPTS = {
    "holographic_self_written_will": {
        "trigger_issues": ["will_formal_requirements", "holographic_will", "handwritten_will", "probate_process", "asset_transfer_via_will"],
        "trigger_terms": ["руки", "рукописн", "на коленке", "holographic", "handwritten", "เขียนเอง"],
        "en_dense": "holographic handwritten will formal requirements Civil Commercial Code Section 1657",
        "th_dense": "พินัยกรรมแบบเขียนเองทั้งฉบับ ข้อกำหนดแบบพินัยกรรม ประมวลกฎหมายแพ่งและพาณิชย์ มาตรา 1657",
        "lexical_anchors": ["CIVIL_CODE_1657", "CIVIL_CODE_1656", "1657", "1656", "พินัยกรรมเขียนเองทั้งฉบับ", "พินัยกรรม"]
    },
    "villa_leasehold_superficies": {
        "trigger_issues": ["long_term_lease_registration", "usufruct_superficies_rights", "villa_ownership_structure", "foreign_ownership_eligibility_building"],
        "trigger_terms": ["вилл", "villa", "leasehold", "superficies", "суперфиций", "долгосрочн", "30 лет", "สิทธิเหนือพื้นดิน", "เช่าระยะยาว"],
        "en_dense": "long term lease 30 years registration Section 538 superficies right to own building Section 1410 Civil Commercial Code",
        "th_dense": "การเช่าอสังหาริมทรัพย์เกินสามปีจดทะเบียน มาตรา 538 สิทธิเหนือพื้นดิน มาตรา 1410 ประมวลกฎหมายแพ่งและพาณิชย์",
        "lexical_anchors": ["CIVIL_CODE_538", "CIVIL_CODE_1410", "TH_LAND_SEC_86", "538", "1410", "สิทธิเหนือพื้นดิน", "เช่าเกินสามปี"]
    },
    "short_term_tourist_rental_hotel_act": {
        "trigger_issues": ["daily_tourist_rental_licensing", "hotel_act_applicability_condominiums", "hotel_business_definition_thresholds", "condominium_regulations_short_term_rental"],
        "trigger_terms": ["посуточн", "airbnb", "daily rental", "4 комнат", "4 rooms", "tourist rental", "ที่พักรายวัน", "โรงแรม"],
        "en_dense": "hotel business license daily rental tourist short term accommodation exemption 4 rooms 20 guests ministerial regulation Hotel Act B.E. 2547 Section 4 Section 15",
        "th_dense": "ใบอนุญาตประกอบธุรกิจโรงแรม ให้เช่ารายวัน สถานที่พักที่ไม่เป็นโรงแรม กฎกระทรวง ไม่เกิน 4 ห้อง พระราชบัญญัติโรงแรม พ.ศ. 2547",
        "lexical_anchors": ["TH_GAZ_ร0049_1B_0001", "TH_LAW_dd8204c75944", "พระราชบัญญัติโรงแรม", "สถานที่พักที่ไม่เป็นโรงแรม", "ใบอนุญาตโรงแรม"]
    },
    "nominee_shareholding_prohibition": {
        "trigger_issues": ["nominee_director_liability", "foreign_business_act_violations", "company_ownership_structure", "anti_money_laundering_implications"],
        "trigger_terms": ["номин", "nominee", "นอมินี", "ถือหุ้นแทน", "49%"],
        "en_dense": "nominee shareholder liability criminal penalties Section 36 Section 37 Foreign Business Act B.E. 2542 Thailand",
        "th_dense": "คนต่างด้าว นอมินี ถือหุ้นแทน ความผิดและโทษ มาตรา 36 มาตรา 37 พระราชบัญญัติการประกอบธุรกิจของคนต่างด้าว",
        "lexical_anchors": ["TH_FBA_SEC_36", "TH_FBA_SEC_37", "FBA", "คนต่างด้าว", "นอมินี", "ถือหุ้นแทน"]
    },
    "foreign_income_remittance_tax_p161": {
        "trigger_issues": ["foreign_sourced_income_tax", "remittance_tax_p161", "tax_residency_180_days", "revenue_department_p161", "revenue_code_section_41", "foreign_income_taxation"],
        "trigger_terms": ["p.161", "p161", "п.161", "п161", "161/2566", "162/2567", "ввоз денег", "перевод денег", "доход из-за границы", "налоговое резидентство", "180 дней", "foreign income", "remittance", "foreign-sourced", "คำสั่งกรมสรรพากร", "ป.161", "เงินได้จากต่างประเทศ"],
        "en_dense": "foreign sourced income tax remittance Thailand Revenue Code Section 41 Paragraph 2 Revenue Department Instruction Paw 161 2566 Paw 162 2567 tax resident 180 days",
        "th_dense": "การเสียภาษีเงินได้จากต่างประเทศ นำเข้ามาในประเทศไทย ประมวลรัษฎากร มาตรา 41 วรรคสอง คำสั่งกรมสรรพากรที่ ป. 161 2566 และ ป. 162 2567 ผู้มีถิ่นที่อยู่ทางภาษี 180 วัน",
        "lexical_anchors": ["ป.161/2566", "ป.162/2567", "P.161/2566", "P.162/2567", "Section 41", "มาตรา 41", "180 วัน", "foreign income", "ภาษีเงินได้บุคคลธรรมดา"]
    },
    "property_transfer_taxes_and_sbt": {
        "trigger_issues": ["land_office_taxes_condominium_sale", "tax_implications_property_acquisition", "transaction_registration_and_taxes"],
        "trigger_terms": ["налог на недвижимость", "налог при покупке", "налог на землю", "налог с продажи квартиры", "land office", "transfer fee", "specific business tax", "ภาษีธุรกิจเฉพาะ", "ค่าธรรมเนียมการโอน", "sbt"],
        "en_dense": "property transfer taxes fees Land Office specific business tax withholding tax stamp duty Revenue Code Section 91/2",
        "th_dense": "ภาษีธุรกิจเฉพาะ การโอนอสังหาริมทรัพย์ กรมที่ดิน ค่าธรรมเนียมการโอน ประมวลรัษฎากร มาตรา 91/2",
        "lexical_anchors": ["Revenue Code", "91/2", "ภาษีธุรกิจเฉพาะ", "ค่าธรรมเนียมการโอน", "ประมวลรัษฎากร"]
    },
    "property_investment_visa_distinction": {
        "trigger_issues": ["property_ownership_and_residency_linkage", "residency_permit_requirements_general", "citizenship_requirements_general"],
        "trigger_terms": ["внж", "гражданств", "паспорт", "residence", "citizenship", "investment visa", "10 million", "elite", "privilege card"],
        "en_dense": "real estate purchase residency investment visa 10 million baht privilege card Thailand Elite citizenship restrictions Land Code Section 86",
        "th_dense": "การลงทุนซื้ออสังหาริมทรัพย์ วีซ่าผู้ลงทุน 10 ล้านบาท สิทธิการอยู่อาศัย สัญชาติไทย คนต่างด้าว ที่ดิน มาตรา 86",
        "lexical_anchors": ["TH_LAND_SEC_86", "Investment Visa", "10 Million", "คนต่างด้าว", "ที่ดิน"]
    },
    "condo_foreign_inheritance": {
        "trigger_issues": ["condominium_foreign_ownership_inheritance", "validity_and_enforcement_of_thai_will", "foreign_heir_rights_and_obligations"],
        "trigger_terms": ["наследован", "наследник", "умер", "condo inheritance", "heir", "มรดก", "ทายาท"],
        "en_dense": "foreign national inheritance condominium unit transfer 1 year disposal quota Condominium Act B.E. 2522 Section 19 Section 19(7)",
        "th_dense": "คนต่างด้าวรับมรดกห้องชุด อาคารชุด มาตรา 19 ทายาทผู้รับโอน กรรมสิทธิ์ ภายในหนึ่งปี พระราชบัญญัติอาคารชุด",
        "lexical_anchors": ["TH_LAW_7051e2562145", "CIVIL_CODE_1656", "19(7)", "ห้องชุด", "รับมรดก", "อาคารชุด"]
    },
    "labor_severance_pay": {
        "trigger_issues": ["labor_protection_severance", "termination_compensation", "work_permit_compliance"],
        "trigger_terms": ["увольнен", "компенсац", "severance", "dismissal", "labor", "เลิกจ้าง", "ค่าชดเชย"],
        "en_dense": "severance pay calculation length of employment Section 118 Labor Protection Act B.E. 2541 Thailand",
        "th_dense": "การจ่ายค่าชดเชยการเลิกจ้าง ตามอายุงาน พระราชบัญญัติคุ้มครองแรงงาน พ.ศ. 2541 มาตรา 118",
        "lexical_anchors": ["TH_LABOR_SEC_118", "TH_LABOR", "118", "ค่าชดเชย", "เลิกจ้าง"]
    },
    "marital_property_and_prenup": {
        "trigger_issues": ["prenuptial_agreement_validity", "marital_property_division", "foreign_spouse_land"],
        "trigger_terms": ["брак", "брачн", "супруг", "тайка", "жена", "prenup", "marriage", "sin somros", "sin suan tua", "สมรส"],
        "en_dense": "prenuptial agreement validity registration Section 1465 1466 separate personal property Sin Suan Tua Sin Somros Section 1471 1474",
        "th_dense": "สัญญาก่อนสมรส จดทะเบียน มาตรา 1465 มาตรา 1466 สินส่วนตัว สินสมรส มาตรา 1471 มาตรา 1474 ประมวลกฎหมายแพ่งและพาณิชย์",
        "lexical_anchors": ["CIVIL_CODE_1465", "CIVIL_CODE_1466", "CIVIL_CODE_1471", "CIVIL_CODE_1474", "1465", "1466", "1471", "1474", "สัญญาก่อนสมรส", "สินสมรส", "สินส่วนตัว"]
    },
    "condo_foreign_quota_and_fet": {
        "trigger_issues": ["foreign_condo_ownership_quota", "inward_foreign_currency_remittance", "freehold_title_registration", "foreign_currency_declaration"],
        "trigger_terms": ["кондо", "condo", "49%", "fet", "foreign exchange", "квартир", "apartment"],
        "en_dense": "foreign condominium ownership 49% quota inward remittance FET form foreign exchange certificate Condominium Act Section 19 Section 19(5)",
        "th_dense": "สิทธิคนต่างด้าวซื้อห้องชุด ถือครองกรรมสิทธิ์ไม่เกิน 49% แบบ ธ.ต. 3 แบบ FET พระราชบัญญัติอาคารชุด มาตรา 19 มาตรา 19(5)",
        "lexical_anchors": ["TH_CONDO_SEC_19", "TH_LAW_7051e2562145", "19(5)", "FET", "อาคารชุด", "ห้องชุด", "49%"]
    },
    "ltr_visa_investment_regulations": {
        "trigger_issues": ["ltr_visa_requirements", "ltr_wealthy_global_citizen", "long_term_resident_visa", "ltr_visa"],
        "trigger_terms": ["ltr", "10-летн", "10-year visa", "long-term resident", "wealthy investor", "ltr visa", "วีซ่า ltr"],
        "en_dense": "Long-Term Resident LTR visa wealthy global citizen investor criteria Immigration Act B.E. 2522 Section 17 BOI Board of Investment regulations",
        "th_dense": "การตรวจลงตราประเภทคนอยู่ชั่วคราวเป็นกรณีพิเศษ Long-Term Resident LTR วีซ่า พระราชบัญญัติคนเข้าเมือง พ.ศ. 2522 มาตรา 17 คณะกรรมการส่งเสริมการลงทุน BOI",
        "lexical_anchors": ["TH_LAW_782c1a9e7325", "พระราชบัญญัติคนเข้าเมือง", "Immigration Act B.E. 2522", "BOI", "LTR Visa", "ส่งเสริมการลงทุน"]
    }
}


SYSTEM_PROMPT = """You are the Senior Legal Query Planner of Consultant+ for the Kingdom of Thailand.
Your duty is to formulate an Issue-Based Multi-Query Search Plan.

STRICT PRINCIPLES:
1. Deconstruct the inquiry and client facts into abstract substantive LEGAL ISSUES (e.g. "foreign_condo_ownership_quota", "daily_tourist_rental_licensing", "long_term_lease_registration", "usufruct_superficies_rights", "nominee_director_liability", "will_formal_requirements").
2. Multilingual Query Expansion: Formulate dense search phrases in BOTH English AND Thai describing the legal concepts, rights, and restrictions under Thai law.
3. Formulate lexical keywords for database FTS in English and Thai.

Output strictly JSON matching this format:
{
  "canonical_summary": "English summary of the legal question",
  "detected_issues": [
    {
      "issue_id": "iss_1",
      "name": "daily_tourist_rental_licensing",
      "description": "Statutory rules and licensing requirements for renting residential villas or apartments to tourists on a daily basis",
      "priority": 1
    }
  ],
  "dense_queries": [
    "foreign national rights to own land villa Thailand restrictions",
    "daily tourist rental license requirements residential accommodation regulations",
    "สิทธิคนต่างด้าวถือครองที่ดินวิลล่า",
    "การให้เช่าที่พักรายวันใบอนุญาตประกอบธุรกิจโรงแรม"
  ],
  "lexical_queries": [
    "foreigner land lease",
    "daily rental tourist license",
    "เช่าที่ดิน ต่างด้าว",
    "ที่พักรายวัน"
  ]
}
"""


class QueryPlanner:
    def __init__(self, gateway: Optional[ModelGateway] = None):
        self.gateway = gateway or ModelGateway()

    def plan_queries(
        self,
        user_query: str,
        case_state: LegalCaseState
    ) -> QueryPlan:
        active_facts = case_state.get_active_facts()
        lower_q = user_query.lower()

        prompt = f"""USER QUERY: \"{user_query}\"
CASE MATTER: {case_state.matter_type}
CURRENT ACTIVE FACTS: {active_facts}
KNOWN UNKNOWNS: {case_state.unknowns}
"""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ]

        try:
            res = self.gateway.chat_structured_json(messages, temperature=0.1)
            
            issues = [
                LegalIssue(
                    issue_id=i.get("issue_id", f"iss_{idx}"),
                    name=i.get("name", "legal_issue"),
                    description=i.get("description", ""),
                    priority=int(i.get("priority", 1))
                )
                for idx, i in enumerate(res.get("detected_issues", []))
            ]

            dense = res.get("dense_queries", [user_query])
            lexical = res.get("lexical_queries", [user_query])

            # Principled Legal Concept & Issue Mapping
            # Directive 2: Apply ONLY when corresponding legal issue is detected
            detected_issue_names = set([iss.name.lower() for iss in issues])
            detected_issue_descs = " ".join([iss.description.lower() for iss in issues])
            
            activated_concepts = []
            # 1. Primary: match against detected substantive issues
            for concept_id, concept_meta in CANONICAL_LEGAL_CONCEPTS.items():
                is_triggered = False
                for ti in concept_meta["trigger_issues"]:
                    if ti.lower() in detected_issue_names or ti.lower() in detected_issue_descs:
                        is_triggered = True
                        break

                if is_triggered:
                    activated_concepts.append(concept_id)
                    en_d = concept_meta["en_dense"]
                    th_d = concept_meta["th_dense"]
                    if en_d not in dense:
                        dense.append(en_d)
                    if th_d not in dense:
                        dense.append(th_d)
                    for la in concept_meta["lexical_anchors"]:
                        if la not in lexical:
                            lexical.append(la)

            # 2. Secondary fallback: only if no issues triggered any concept
            if not activated_concepts:
                for concept_id, concept_meta in CANONICAL_LEGAL_CONCEPTS.items():
                    for term in concept_meta["trigger_terms"]:
                        if term in lower_q:
                            activated_concepts.append(concept_id)
                            en_d = concept_meta["en_dense"]
                            th_d = concept_meta["th_dense"]
                            if en_d not in dense:
                                dense.append(en_d)
                            if th_d not in dense:
                                dense.append(th_d)
                            for la in concept_meta["lexical_anchors"]:
                                if la not in lexical:
                                    lexical.append(la)
                            break

            return QueryPlan(
                original_query=user_query,
                canonical_summary=res.get("canonical_summary", user_query),
                detected_issues=issues,
                activated_legal_concepts=activated_concepts,
                dense_queries=dense,
                lexical_queries=lexical
            )
        except Exception as e:
            print(f"QueryPlanner error: {e}, using baseline plan")
            return QueryPlan(
                original_query=user_query,
                canonical_summary=user_query,
                detected_issues=[LegalIssue(issue_id="iss_gen", name="general_legal_issue", description=user_query)],
                activated_legal_concepts=[],
                dense_queries=[user_query, f"{user_query} Thailand law"],
                lexical_queries=[user_query]
            )
