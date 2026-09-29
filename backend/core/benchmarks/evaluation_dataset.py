"""
backend/core/benchmarks/evaluation_dataset.py
Consultant+ Core Engine 2.0 — Versioned Evaluation Suite (v2.1).
Contains 30 standardized legal evaluation scenarios across 8 statutory domains,
with explicit ground-truth expectations for:
- intent & abstract legal issues
- expected extracted user facts
- expected clarification question
- relevant legal documents/sections
- admissible claims (MUST be grounded)
- forbidden claims (HALUCINATION triggers to flag)
- expected retrieval results
"""

from typing import List, Dict, Any

EVALUATION_DATASET_VERSION = "2.1.0"

TH_EVALUATION_SCENARIOS: List[Dict[str, Any]] = [
    # ── 1. CONDOMINIUM & APARTMENTS (1-4) ───────────────────────────────────
    {
        "id": "TH_EVAL_01",
        "domain": "CONDO_PROPERTY",
        "complexity": "SIMPLE_DIRECT",
        "query": "Могу ли я как гражданин России купить квартиру в кондоминиуме в Таиланде в 100% личную собственность?",
        "expected_intent": "property_acquisition",
        "expected_issues": ["foreign_condo_ownership_quota", "inward_foreign_currency_remittance", "freehold_title_registration"],
        "expected_user_facts": {"role": "buyer", "nationality": "Russian", "property_type": "condominium"},
        "expected_clarification": "Планируете ли вы покупку на первичном рынке у застройщика или вторичном рынке у частного лица?",
        "relevant_statutes": ["Condominium Act B.E. 2522 Section 19", "Condominium Act Section 19(5)"],
        "admissible_claims": [
            "Иностранец может владеть квартирой в кондоминиуме на правах 100% частной собственности (Freehold) в пределах 49% квоты здания.",
            "Обязательным условием является предоставление справки FET из тайского банка о переводе валюты из-за рубежа."
        ],
        "forbidden_claims": [
            "Иностранец может владеть землей под кондоминиумом.",
            "Справка FET не требуется при расчете наличными батами внутри Таиланда."
        ]
    },
    {
        "id": "TH_EVAL_02",
        "domain": "CONDO_PROPERTY",
        "complexity": "AMBIGUOUS",
        "query": "Хочу купить квартиру в Паттайе за наличные доллары, которые привез с собой. Как оформить документы?",
        "expected_intent": "property_acquisition",
        "expected_issues": ["foreign_currency_declaration", "bank_foreign_exchange_certificate", "customs_currency_import"],
        "expected_user_facts": {"property_type": "condominium", "payment_method": "cash_usd"},
        "expected_clarification": "Были ли наличные доллары задекларированы на тайской таможне при въезде в Королевство?",
        "relevant_statutes": ["Condominium Act Section 19(5)", "Bank of Thailand Foreign Exchange Regulations"],
        "admissible_claims": [
            "Ввоз наличной валюты требует обязательной таможенной декларации для последующего зачисления в банк и получения справки FET.",
            "Земельный департамент не зарегистрирует право собственности иностранца без официальной банковской формы FET."
        ],
        "forbidden_claims": [
            "Можно просто передать наличные продавцу в офисе застройщика без банка."
        ]
    },
    {
        "id": "TH_EVAL_03",
        "domain": "CONDO_PROPERTY",
        "complexity": "MULTI_TURN",
        "query": "Что делать, если в кондоминиуме закончилась иностранная квота 49%?",
        "expected_intent": "property_acquisition_alternative",
        "expected_issues": ["thai_quota_alternatives", "leasehold_registration_condo", "corporate_holding_limits"],
        "expected_user_facts": {"property_type": "condominium", "quota_status": "foreign_quota_exhausted"},
        "expected_clarification": "Готовы ли вы рассматривать вариант долгосрочной аренды Leasehold на 30 лет с регистрацией в Land Office?",
        "relevant_statutes": ["Civil and Commercial Code Section 538", "Condominium Act B.E. 2522 Section 19"],
        "admissible_claims": [
            "При исчерпании квоты 49% квартира может быть оформлена иностранцем только по договору долгосрочной аренды (Leasehold) на срок до 30 лет.",
            "Регистрация договора аренды свыше 3 лет в Земельном департаменте обязательна."
        ],
        "forbidden_claims": [
            "Можно создать фиктивную тайскую компанию с тайскими номиналами для покупки тайской квоты без риска."
        ]
    },
    {
        "id": "TH_EVAL_04",
        "domain": "CONDO_PROPERTY",
        "complexity": "DIRTY_CONVERSATIONAL",
        "query": "Короче нашел студию в Бангкоке, риелтор говорит давай переводи баты на карту продавца и завтра в Лэнд Офис. Норм схема?",
        "expected_intent": "transaction_risk_verification",
        "expected_issues": ["fet_form_violation", "direct_transfer_risk", "foreign_ownership_disqualification"],
        "expected_user_facts": {"property_type": "condominium", "transaction_stage": "payment_requested"},
        "expected_clarification": "Проверяли ли вы в управляющей компании (Juristic Person) наличие справки об отсутствии задолженности (Debt-Free Certificate)?",
        "relevant_statutes": ["Condominium Act Section 19", "Condominium Act Section 29"],
        "admissible_claims": [
            "Перевод батов напрямую с тайской карты на карту продавца лишит вас права оформить квартиру во Freehold из-за отсутствия справки FET.",
            "Деньги должны быть переведены в иностранной валюте из-за рубежа с указанием назначения покупки кондоминиума."
        ],
        "forbidden_claims": [
            "Схема безопасна и стандартна."
        ]
    },

    # ── 2. LAND, HOUSES & VILLAS (5-8) ──────────────────────────────────────
    {
        "id": "TH_EVAL_05",
        "domain": "LAND_PROPERTY",
        "complexity": "SIMPLE_DIRECT",
        "query": "Может ли иностранец владеть землей в Таиланде под строительство дома?",
        "expected_intent": "land_ownership_inquiry",
        "expected_issues": ["foreigner_land_ownership_ban", "treaty_exceptions", "leasehold_and_superficies"],
        "expected_user_facts": {"role": "buyer", "property_type": "land"},
        "expected_clarification": "Планируете ли вы владеть только зданием дома, оформив землю в долгосрочную аренду Leasehold?",
        "relevant_statutes": ["Land Code B.E. 2497 Section 86", "Civil and Commercial Code Section 1410"],
        "admissible_claims": [
            "Статья 86 Земельного кодекса устанавливает прямой запрет на приобретение иностранцами земли в собственность (за исключением редких межгосударственных договоров).",
            "Иностранец может законно владеть самим зданием дома на праве 100% собственности через право суперфиция (ст. 1410 CCC)."
        ],
        "forbidden_claims": [
            "Иностранец может свободно купить земельный участок в личную собственность."
        ]
    },
    {
        "id": "TH_EVAL_06",
        "domain": "LAND_PROPERTY",
        "complexity": "COMPLEX_STRUCTURING",
        "query": "Как законно и безопасно оформить виллу на Пхукете иностранному покупателю?",
        "expected_intent": "villa_structuring",
        "expected_issues": ["leasehold_superficies_combination", "building_ownership", "renewal_enforceability"],
        "expected_user_facts": {"property_type": "villa", "location": "Phuket"},
        "expected_clarification": "Рассматриваете ли вы виллу для собственного проживания или для инвестиционной сдачи в аренду?",
        "relevant_statutes": ["Civil and Commercial Code Section 538", "Civil and Commercial Code Section 1410"],
        "admissible_claims": [
            "Оптимальной структурой является разделение: зарегистрированная аренда земли (Leasehold) на 30 лет плюс право суперфиция (Superficies) или разрешение на строительство на имя иностранца.",
            "Право собственности на здание является бессрочным вещным правом, зарегистрированным на обратной стороне чанота в Land Office."
        ],
        "forbidden_claims": [
            "Договор аренды на 90 лет регистрируется единовременно в земельном департаменте."
        ]
    },
    {
        "id": "TH_EVAL_07",
        "domain": "LAND_PROPERTY",
        "complexity": "MULTI_TURN",
        "query": "Я гражданин РФ, женат на тайке. Хотим купить землю и построить дом. Могу ли я быть совладельцем?",
        "expected_intent": "thai_spouse_land_acquisition",
        "expected_issues": ["thai_spouse_land_declaration", "sin_suan_tua_declaration", "usufruct_superficies_protection"],
        "expected_user_facts": {"role": "spouse", "nationality": "Russian", "spouse_nationality": "Thai"},
        "expected_clarification": "Готовы ли вы подписать в Land Office совместную декларацию о том, что средства на покупку земли являются личной собственностью супруги (Sin Suan Tua)?",
        "relevant_statutes": ["Land Department Regulation on Alien Spouses", "Civil and Commercial Code Section 1471", "Civil and Commercial Code Section 1417"],
        "admissible_claims": [
            "Тайская супруга имеет право купить землю, но оба супруга обязаны подписать в Land Office декларацию о том, что земля является ее личным имуществом (Sin Suan Tua).",
            "Для защиты инвестиций иностранного супруга на землю может быть зарегистрировано право узуфрукта (Usufruct) или суперфиций."
        ],
        "forbidden_claims": [
            "Земля будет зарегистрирована в совместную собственность (Sin Somros) по 50% на каждого."
        ]
    },
    {
        "id": "TH_EVAL_08",
        "domain": "LAND_PROPERTY",
        "complexity": "DIRTY_CONVERSATIONAL",
        "query": "Агент предлагает купить виллу через готовую компанию 51 на 49, говорит все так делают и проверено годами. В чем подвох?",
        "expected_intent": "nominee_company_risk",
        "expected_issues": ["nominee_shareholders_criminal_liability", "land_department_financial_audit", "company_revocation"],
        "expected_user_facts": {"scheme_proposed": "nominee_company_51_49", "property_type": "villa"},
        "expected_clarification": "Имеют ли тайские граждане-акционеры подтвержденный легальный доход для оплаты 51% акций?",
        "relevant_statutes": ["Foreign Business Act B.E. 2542 Section 36", "Land Code B.E. 2497 Section 113"],
        "admissible_claims": [
            "Использование подставных тайских номиналов является уголовным преступлением по ст. 36 Закона об иностранном бизнесе (до 3 лет лишения свободы).",
            "Земельный департамент проводит строгий финансовый аудит источников средств тайских акционеров при регистрации земли на компанию с участием иностранцев."
        ],
        "forbidden_claims": [
            "Покупка через компанию с номиналами абсолютно легальна и не несет рисков."
        ]
    },

    # ── 3. SHORT-TERM RENTAL & HOTEL REGULATIONS (9-11) ─────────────────────
    {
        "id": "TH_EVAL_09",
        "domain": "HOTEL_RENTAL",
        "complexity": "SIMPLE_DIRECT",
        "query": "Можно ли сдавать купленную квартиру в кондо посуточно через Airbnb в Таиланде?",
        "expected_intent": "daily_rental_legality",
        "expected_issues": ["hotel_act_licensing", "daily_rental_ban", "minimum_30_days_rental"],
        "expected_user_facts": {"property_type": "condominium", "rental_frequency": "daily"},
        "expected_clarification": "Готовы ли вы переориентироваться на помесячную аренду от 30 дней и более?",
        "relevant_statutes": ["Hotel Act B.E. 2547 Section 15", "Hotel Act Section 59"],
        "admissible_claims": [
            "Сдача жилья туристам на срок менее 30 дней признается гостиничной деятельностью и требует лицензии отеля по Закону о гостиницах B.E. 2547.",
            "Сдача без лицензии наказывается штрафом до 10 000 бат и/или лишением свободы до 1 года (ст. 59 Hotel Act)."
        ],
        "forbidden_claims": [
            "Квартиру в обычном жилом кондоминиуме можно свободно сдавать посуточно на Airbnb без каких-либо ограничений."
        ]
    },
    {
        "id": "TH_EVAL_10",
        "domain": "HOTEL_RENTAL",
        "complexity": "COMPLEX_STRUCTURING",
        "query": "Как законно сдавать виллу туристам посуточно, если у нас до 4 комнат?",
        "expected_intent": "non_hotel_exemption",
        "expected_issues": ["ministerial_regulation_non_hotel", "district_notification", "health_safety_standards"],
        "expected_user_facts": {"property_type": "villa", "rooms_count": 4, "purpose": "daily_tourist_rental"},
        "expected_clarification": "В каком округе/провинции расположена вилла для подачи уведомления районному регистратору?",
        "relevant_statutes": ["Ministerial Regulation under Hotel Act on Non-Hotel Accommodation", "Hotel Act B.E. 2547 Section 4"],
        "admissible_claims": [
            "Жилые помещения, имеющие не более 4 комнат и вмещающие не более 20 гостей, могут быть зарегистрированы как жилье вне отеля (Non-Hotel Accommodation).",
            "Для законной сдачи требуется подать официальное уведомление в районную администрацию (Amphoe) и получить сертификат соответствия."
        ],
        "forbidden_claims": [
            "Любая вилла освобождена от гостиничного законодательства автоматически."
        ]
    },
    {
        "id": "TH_EVAL_11",
        "domain": "HOTEL_RENTAL",
        "complexity": "MULTI_TURN",
        "query": "Что будет, если соседи по кондо пожалуются в полицию на посуточных жильцов?",
        "expected_intent": "enforcement_penalties",
        "expected_issues": ["police_raid_hotel_act", "juristic_fines", "court_precedents"],
        "expected_user_facts": {"property_type": "condominium", "dispute": "neighbor_complaints"},
        "expected_clarification": "Установлен ли в регламенте вашего кондоминиума штраф за посуточную сдачу со стороны управляющей компании?",
        "relevant_statutes": ["Hotel Act Section 59", "Supreme Court Landmark Precedents on Daily Condominium Rentals"],
        "admissible_claims": [
            "Полиция и чиновники районной администрации имеют право провести проверку, составить протокол об административном/уголовном правонарушении и опечатать помещение.",
            "Судебная практика Верховного Суда (San Deka) однозначно подтверждает незаконность посуточной сдачи в кондо без лицензии."
        ],
        "forbidden_claims": [
            "Полиция не имеет права вмешиваться в дела частной собственности внутри кондоминиума."
        ]
    },

    # ── 4. CORPORATE & FOREIGN BUSINESS (12-15) ─────────────────────────────
    {
        "id": "TH_EVAL_12",
        "domain": "CORPORATE_FOREIGN_BUSINESS",
        "complexity": "SIMPLE_DIRECT",
        "query": "Может ли иностранец быть единственным директором в тайской компании 51/49?",
        "expected_intent": "corporate_governance",
        "expected_issues": ["sole_foreign_director", "authorized_signatory", "dbd_scrutiny"],
        "expected_user_facts": {"company_structure": "thai_limited_company", "role": "director"},
        "expected_clarification": "Каким видом коммерческой деятельности планирует заниматься компания (услуги, торговля, производство)?",
        "relevant_statutes": ["Civil and Commercial Code Section 1144", "Foreign Business Act B.E. 2542"],
        "admissible_claims": [
            "Иностранец может быть назначен единственным директором-распорядителем (Authorized Director) с правом единоличной подписи и печати компании.",
            "Гражданский и коммерческий кодекс не запрещает иностранному гражданину осуществлять единоличное руководство тайским юридическим лицом."
        ],
        "forbidden_claims": [
            "По закону директором тайской компании обязан быть исключительно гражданин Таиланда."
        ]
    },
    {
        "id": "TH_EVAL_13",
        "domain": "CORPORATE_FOREIGN_BUSINESS",
        "complexity": "COMPLEX_STRUCTURING",
        "query": "Как иностранцу открыть компанию в Таиланде со 100% иностранным капиталом без тайских партнеров?",
        "expected_intent": "100_percent_foreign_ownership",
        "expected_issues": ["boi_promotion", "foreign_business_license", "us_treaty_of_amity"],
        "expected_user_facts": {"ownership_target": "100_percent_foreign"},
        "expected_clarification": "Подпадает ли ваш бизнес под приоритетные направления Совета по инвестициям (BOI) — технологии, софт, производство?",
        "relevant_statutes": ["Investment Promotion Act B.E. 2520", "Foreign Business Act Section 12"],
        "admissible_claims": [
            "100% иностранное владение возможно при получении сертификата Совета по инвестициям (BOI) для поощряемых отраслей экономики.",
            "Альтернативными путями являются получение лицензии FBL (Foreign Business License) или регистрация по специальным торговым договорам (Treaty of Amity для граждан США)."
        ],
        "forbidden_claims": [
            "Иностранцу категорически запрещено владеть 100% компании в Таиланде ни при каких условиях."
        ]
    },
    {
        "id": "TH_EVAL_14",
        "domain": "CORPORATE_FOREIGN_BUSINESS",
        "complexity": "MULTI_TURN",
        "query": "Как распределить акции компании так, чтобы у тайцев было 51%, но весь контроль и прибыль были у меня?",
        "expected_intent": "voting_preference_shares",
        "expected_issues": ["preference_shares_structure", "dividend_rights", "dbd_examination"],
        "expected_user_facts": {"equity_ratio": "51_49", "control_intent": "foreign_exclusive_control"},
        "expected_clarification": "Оформляется ли уставной капитал от 2 млн батов для последующего найма иностранного сотрудника и оформления Work Permit?",
        "relevant_statutes": ["Civil and Commercial Code Section 1108", "Foreign Business Act Section 36"],
        "admissible_claims": [
            "Законно использовать привилегированные акции (Preference Shares): обыкновенные акции иностранца дают 10 голосов на акцию, а акции тайских партнеров — 1 голос на 10 акций.",
            "Департамент развития бизнеса (DBD) требует подтверждения реальной оплаты тайскими акционерами своей доли капитала при уставном капитале свыше определенных лимитов."
        ],
        "forbidden_claims": [
            "Тайские акционеры могут подписать пустые бланки отказа от акций без какого-либо правового риска."
        ]
    },
    {
        "id": "TH_EVAL_15",
        "domain": "CORPORATE_FOREIGN_BUSINESS",
        "complexity": "DIRTY_CONVERSATIONAL",
        "query": "Что грозит тайцу, который согласился побыть номиналом в моей компании за небольшую плату?",
        "expected_intent": "nominee_penalties_inquiry",
        "expected_issues": ["criminal_liability_nominee", "anti_money_laundering", "corporate_dissolution"],
        "expected_user_facts": {"nominee_agreement": "paid_nominee"},
        "expected_clarification": "Владеет ли компания недвижимым имуществом или землей?",
        "relevant_statutes": ["Foreign Business Act B.E. 2542 Section 36", "Foreign Business Act Section 37"],
        "admissible_claims": [
            "Тайскому гражданину-номиналу грозит уголовная ответственность: лишение свободы на срок до 3 лет и/или штраф от 100 000 до 1 000 000 батов.",
            "Иностранцу, нанявшему номинала, грозит такое же уголовное наказание плюс принудительная ликвидация компании судом."
        ],
        "forbidden_claims": [
            "Номинальное владение влечет исключительно символический административный штраф в 500 батов."
        ]
    },

    # ── 5. TAXATION & REVENUE (16-19) ────────────────────────────────────────
    {
        "id": "TH_EVAL_16",
        "domain": "TAX_REVENUE",
        "complexity": "SIMPLE_DIRECT",
        "query": "Сколько дней нужно прожить в Таиланде, чтобы стать налоговым резидентом?",
        "expected_intent": "tax_residency_criteria",
        "expected_issues": ["180_days_rule", "calendar_year_basis", "tax_residence_certificate"],
        "expected_user_facts": {"jurisdiction": "Thailand"},
        "expected_clarification": "Получаете ли вы доход от источников в Таиланде или ввозите средства из-за рубежа?",
        "relevant_statutes": ["Revenue Code Section 41 Paragraph 3"],
        "admissible_claims": [
            "Налоговым резидентом признается лицо, находящееся в Таиланде в совокупности 180 дней и более в течение одного календарного года.",
            "Дни пребывания суммируются за период с 1 января по 31 декабря независимо от перерывов между визитами."
        ],
        "forbidden_claims": [
            "Налоговое резидентство наступает строго через 90 дней непрерывного пребывания."
        ]
    },
    {
        "id": "TH_EVAL_17",
        "domain": "TAX_REVENUE",
        "complexity": "COMPLEX_STRUCTURING",
        "query": "Как работает приказ P.161 и P.162 по налогу на ввоз иностранных доходов в Таиланд?",
        "expected_intent": "remittance_taxation",
        "expected_issues": ["order_paw_161", "order_paw_162_exemption", "pre_2024_savings"],
        "expected_user_facts": {"remittance_inquiry": True},
        "expected_clarification": "Были ли ввозимые денежные средства заработаны до 1 января 2024 года?",
        "relevant_statutes": ["Revenue Department Order Paw. 161/2566", "Revenue Department Clarification Paw. 162/2566"],
        "admissible_claims": [
            "Приказ P.161 облагает тайским НДФЛ иностранные доходы налогового резидента при их ввозе в Таиланд.",
            "Приказ P.162 прямо освобождает от налога сбережения и доходы, полученные до 1 января 2024 года, даже если они ввозятся сейчас."
        ],
        "forbidden_claims": [
            "Любые накопления за всю жизнь облагаются налогом 35% при пересечении границы."
        ]
    },
    {
        "id": "TH_EVAL_18",
        "domain": "TAX_REVENUE",
        "complexity": "MULTI_TURN",
        "query": "Я заплатил налог на доход в России по ставке 13%. Придется ли платить налог повторно при переводе в Таиланд?",
        "expected_intent": "dta_tax_credit",
        "expected_issues": ["double_taxation_agreement", "foreign_tax_credit", "tax_differential"],
        "expected_user_facts": {"tax_paid_country": "Russia", "rate_paid": "13%"},
        "expected_clarification": "Сохранились ли у вас официальные налоговые справки (2-НДФЛ / квитанции ФНС) с апостилем или нотариальным переводом?",
        "relevant_statutes": ["Double Taxation Agreement between Thailand and Russian Federation", "Revenue Code Section 48"],
        "admissible_claims": [
            "По Соглашению об избежании двойного налогообложения (DTA) уплаченный в РФ налог принимается к зачету (Foreign Tax Credit).",
            "Если тайская ставка НДФЛ на соответствующую сумму выше российской, доплачивается только разница."
        ],
        "forbidden_claims": [
            "DTA освобождает от необходимости подавать налоговую декларацию PND 90/91 в Таиланде."
        ]
    },
    {
        "id": "TH_EVAL_19",
        "domain": "TAX_REVENUE",
        "complexity": "DIRTY_CONVERSATIONAL",
        "query": "Какие налоги дерут в Land Office при оформлении сделки купли-продажи квартиры?",
        "expected_intent": "property_transfer_taxes",
        "expected_issues": ["transfer_fee_2_percent", "specific_business_tax_3_3", "withholding_tax", "stamp_duty"],
        "expected_user_facts": {"property_type": "condominium", "stage": "land_office_closing"},
        "expected_clarification": "Владел ли продавец квартирой более 5 лет или менее 5 лет?",
        "relevant_statutes": ["Revenue Code Section 91/2", "Land Department Transfer Fee Regulations"],
        "admissible_claims": [
            "Сбор за передачу прав (Transfer Fee) составляет 2% от государственной оценочной стоимости.",
            "Если продавец владел объектом менее 5 лет, взимается специальный налог на бизнес (SBT) 3.3% вместо гербового сбора 0.5%."
        ],
        "forbidden_claims": [
            "В Land Office оплачивается только НДС 7% и больше никаких сборов."
        ]
    },

    # ── 6. VISAS & IMMIGRATION STATUS (20-23) ────────────────────────────────
    {
        "id": "TH_EVAL_20",
        "domain": "IMMIGRATION_VISA",
        "complexity": "SIMPLE_DIRECT",
        "query": "Какие требования для получения 10-летней визы LTR для состоятельных инвесторов?",
        "expected_intent": "ltr_wealthy_global_citizen",
        "expected_issues": ["ltr_wealthy_citizen_criteria", "assets_1m_usd", "investment_500k_usd", "health_insurance"],
        "expected_user_facts": {"visa_category": "LTR", "role": "investor"},
        "expected_clarification": "Имеете ли вы подтвержденные чистые активы от $1 млн и инвестиции в недвижимость или гособлигации Таиланда от $500 тыс?",
        "relevant_statutes": ["Immigration Act B.E. 2522", "BOI LTR Visa Regulations Announcement"],
        "admissible_claims": [
            "Виза LTR выдается на 10 лет с разрешением на работу (Digital Work Permit) и освобождением от налога на зарубежные доходы.",
            "Требуются активы от $1 млн, подтвержденный годовой доход от $80 000 и инвестиции в Таиланде от $500 000."
        ],
        "forbidden_claims": [
            "Визу LTR может получить любой иностранец, купивший квартиру любой стоимости."
        ]
    },
    {
        "id": "TH_EVAL_21",
        "domain": "IMMIGRATION_VISA",
        "complexity": "COMPLEX_STRUCTURING",
        "query": "Можно ли легально работать на удаленке в зарубежной IT-компании по новой визе DTV?",
        "expected_intent": "dtv_digital_nomad_work",
        "expected_issues": ["dtv_criteria", "remote_work_exemption", "500k_baht_funds"],
        "expected_user_facts": {"visa_category": "DTV", "profession": "IT_remote_worker"},
        "expected_clarification": "Имеется ли у вас выписка из банка с остатком не менее 500 000 тайских батов на дату подачи заявления?",
        "relevant_statutes": ["Ministry of Foreign Affairs DTV Visa Announcement B.E. 2567"],
        "admissible_claims": [
            "Виза DTV (Destination Thailand Visa) дает право легальной удаленной работы на зарубежного работодателя или клиентов за пределами Таиланда.",
            "Срок действия визы составляет 5 лет с правом непрерывного пребывания до 180 дней за один въезд (с возможностью продления еще на 180 дней)."
        ],
        "forbidden_claims": [
            "Виза DTV позволяет трудоустроиться в тайскую местную компанию без Work Permit."
        ]
    },
    {
        "id": "TH_EVAL_22",
        "domain": "IMMIGRATION_VISA",
        "complexity": "MULTI_TURN",
        "query": "Дает ли покупка недвижимости в Таиланде автоматическое право на ВНЖ или гражданство?",
        "expected_intent": "real_estate_residency_link",
        "expected_issues": ["no_automatic_residency", "investment_visa_10m", "elite_programs"],
        "expected_user_facts": {"property_buyer": True, "goal": "residency_or_citizenship"},
        "expected_clarification": "Превышает ли общая сумма ваших инвестиций в недвижимость 10 миллионов батов (для инвестиционной визы на 1 год)?",
        "relevant_statutes": ["Immigration Bureau Order on Investment Visa (10 Million Baht)", "Nationality Act B.E. 2508"],
        "admissible_claims": [
            "Покупка недвижимости не дает автоматического гражданства или постоянного вида на жительство (PR).",
            "При инвестициях от 10 млн батов в кондоминиум во Freehold можно претендовать на ежегодно продлеваемую визу инвестора."
        ],
        "forbidden_claims": [
            "Покупка любой квартиры автоматически дает паспорт гражданина Таиланда через 3 года."
        ]
    },
    {
        "id": "TH_EVAL_23",
        "domain": "IMMIGRATION_VISA",
        "complexity": "DIRTY_CONVERSATIONAL",
        "query": "У меня просрочилась виза на 40 дней, сижу в кондо боюсь выйти. Что делать и сколько штраф?",
        "expected_intent": "overstay_crisis_mitigation",
        "expected_issues": ["overstay_fine_500_per_day", "overstay_ban_blacklist", "voluntary_surrender"],
        "expected_user_facts": {"overstay_days": 40},
        "expected_clarification": "Готовы ли вы явиться в иммиграционный офис добровольно для оформления выезда?",
        "relevant_statutes": ["Immigration Act B.E. 2522 Section 81", "Ministry of Interior Blacklist Notification"],
        "admissible_claims": [
            "Штраф составляет 500 батов за каждый день оверстея (максимум 20 000 батов при добровольной сдаче).",
            "При добровольной явке до 90 дней оверстея запрет на въезд (Blacklist) не налагается при условии оплаты штрафа и немедленного вылета."
        ],
        "forbidden_claims": [
            "Можно просто не платить штраф и улететь без проблем."
        ]
    },

    # ── 7. LABOR & EMPLOYMENT (24-26) ────────────────────────────────────────
    {
        "id": "TH_EVAL_24",
        "domain": "LABOR_EMPLOYMENT",
        "complexity": "SIMPLE_DIRECT",
        "query": "Какое выходное пособие положено сотруднику при увольнении со стажем 4 года в Таиланде?",
        "expected_intent": "severance_pay_calculation",
        "expected_issues": ["lpa_section_118_scales", "severance_180_days", "termination_notice"],
        "expected_user_facts": {"tenure_years": 4, "termination_type": "without_cause"},
        "expected_clarification": "Было ли увольнение вызвано дисциплинарным проступком по ст. 119 Закона о защите труда?",
        "relevant_statutes": ["Labor Protection Act B.E. 2541 Section 118", "Labor Protection Act Section 119"],
        "admissible_claims": [
            "По ст. 118 Закона о защите труда при стаже от 3 до 6 лет сотруднику положено выходное пособие в размере не менее 180 дней последней зарплаты.",
            "Также работодатель обязан предоставить уведомление за один расчетный период либо выплатить компенсацию вместо срока предупреждения."
        ],
        "forbidden_claims": [
            "При любом стаже выплачивается только оклад за 2 недели."
        ]
    },
    {
        "id": "TH_EVAL_25",
        "domain": "LABOR_EMPLOYMENT",
        "complexity": "COMPLEX_STRUCTURING",
        "query": "Какие обязательные условия нужны компании для оформления Work Permit иностранному сотруднику?",
        "expected_intent": "work_permit_prerequisites",
        "expected_issues": ["capital_2m_per_foreigner", "ratio_4_thai_to_1_foreigner", "minimum_salary_rules"],
        "expected_user_facts": {"hiring_target": "expat_employee"},
        "expected_clarification": "Оплачен ли уставный капитал компании в размере не менее 2 миллионов батов?",
        "relevant_statutes": ["Emergency Decree on Managing the Work of Aliens B.E. 2560", "Ministry of Interior Minimum Wage Regulations"],
        "admissible_claims": [
            "На каждого иностранного сотрудника компания обязана иметь 2 миллиона батов оплаченного уставного капитала и трудоустроить минимум 4 тайских сотрудников с уплатой взносов в Social Security.",
            "Для граждан РФ и Европы установлена минимальная планка официальной зарплаты от 50 000 батов в месяц."
        ],
        "forbidden_claims": [
            "Любая компания с капиталом в 100 000 батов может без ограничений нанимать экспатов."
        ]
    },
    {
        "id": "TH_EVAL_26",
        "domain": "LABOR_EMPLOYMENT",
        "complexity": "MULTI_TURN",
        "query": "Может ли иностранец работать гидом или водителем такси в Таиланде?",
        "expected_intent": "prohibited_occupations",
        "expected_issues": ["alien_prohibited_professions_list", "tour_guide_ban", "commercial_transport_ban"],
        "expected_user_facts": {"target_job": "tour_guide_or_taxi"},
        "expected_clarification": "Рассматриваете ли вы управленческую должность в туристической компании вместо работы линейным гидом?",
        "relevant_statutes": ["Royal Decree on Prohibited Occupations for Foreigners (List of 40 Professions)"],
        "admissible_claims": [
            "Профессии экскурсовода (Tour Guide) и водителя пассажирского транспорта строго запрещены для иностранцев королевским указом.",
            "Нарушение влечет депортацию, штраф и включение в черный список."
        ],
        "forbidden_claims": [
            "Иностранец может оформить официальный Work Permit на работу водителем тук-тука."
        ]
    },

    # ── 8. FAMILY, MARRIAGE & ESTATE (27-30) ─────────────────────────────────
    {
        "id": "TH_EVAL_27",
        "domain": "FAMILY_ESTATE",
        "complexity": "SIMPLE_DIRECT",
        "query": "Как правильно составить брачный договор в Таиланде, чтобы он имел законную силу?",
        "expected_intent": "prenuptial_agreement_formalities",
        "expected_issues": ["section_1465_ccc", "marriage_registration_annex", "two_witnesses"],
        "expected_user_facts": {"legal_action": "prenuptial_agreement"},
        "expected_clarification": "Заключается ли брачный договор ДО официальной регистрации брака в районном отделе Amphoe?",
        "relevant_statutes": ["Civil and Commercial Code Section 1465", "Civil and Commercial Code Section 1466"],
        "admissible_claims": [
            "Брачный договор должен быть заключен до брака и внесен в реестр браков (Amphoe) одновременно с регистрацией брака.",
            "Договор, заключенный после свадьбы, является ничтожным по закону Таиланда (ст. 1466 CCC)."
        ],
        "forbidden_claims": [
            "Брачный контракт можно составить и заверить задним числом через 5 лет после свадьбы."
        ]
    },
    {
        "id": "TH_EVAL_28",
        "domain": "FAMILY_ESTATE",
        "complexity": "COMPLEX_STRUCTURING",
        "query": "Как наследуется квартира иностранца в кондоминиуме после его смерти, если есть тайское завещание?",
        "expected_intent": "condo_inheritance_will",
        "expected_issues": ["court_probate_procedure", "estate_executor", "heir_quota_eligibility"],
        "expected_user_facts": {"asset": "condominium", "document": "thai_will"},
        "expected_clarification": "Является ли наследник по завещанию иностранным гражданином, соответствующим требованиям ст. 19 Закона о кондоминиумах?",
        "relevant_statutes": ["Civil and Commercial Code Section 1656", "Condominium Act Section 19(7)"],
        "admissible_claims": [
            "Для вступления в наследство требуется решение тайского суда о назначении распорядителя наследства (Estate Executor).",
            "Иностранный наследник имеет право переоформить квартиру на себя, если укладывается в 49% квоту, либо обязан реализовать ее в течение года."
        ],
        "forbidden_claims": [
            "Тайский нотариус сам переписывает право собственности без судебного решения."
        ]
    },
    {
        "id": "TH_EVAL_29",
        "domain": "FAMILY_ESTATE",
        "complexity": "MULTI_TURN",
        "query": "Разделяется ли квартира в кондо, купленная мной до брака, при разводе с тайской супругой?",
        "expected_intent": "divorce_property_division",
        "expected_issues": ["sin_suan_tua_vs_sin_somros", "premarital_assets", "title_deed_date"],
        "expected_user_facts": {"asset_acquired": "before_marriage", "event": "divorce"},
        "expected_clarification": "Сохранился ли договор купли-продажи и чанот с датой регистрации, предшествующей свидетельству о браке?",
        "relevant_statutes": ["Civil and Commercial Code Section 1471", "Civil and Commercial Code Section 1474"],
        "admissible_claims": [
            "Имущество, приобретенное до брака, является личной собственностью (Sin Suan Tua) и не подлежит разделу при разводе.",
            "Разделу 50/50 подлежит только совместное имущество (Sin Somros), нажитое в период брака."
        ],
        "forbidden_claims": [
            "При разводе тайский суд автоматически забирает 100% любого имущества в пользу тайской стороны."
        ]
    },
    {
        "id": "TH_EVAL_30",
        "domain": "FAMILY_ESTATE",
        "complexity": "DIRTY_CONVERSATIONAL",
        "query": "Хочу составить завещание на виллу и счета в Бангкок Банке чисто от руки на коленке, прокатит в суде?",
        "expected_intent": "holographic_will_validity",
        "expected_issues": ["holographic_will_requirements", "section_1657_ccc", "entirely_handwritten_signature"],
        "expected_user_facts": {"will_type": "handwritten"},
        "expected_clarification": "Готовы ли вы написать весь текст от начала до конца собственноручно, с указанием даты и личной подписи?",
        "relevant_statutes": ["Civil and Commercial Code Section 1657"],
        "admissible_claims": [
            "Собственноручное завещание (Holographic Will) законно по ст. 1657 CCC, если весь текст без исключения написан от руки завещателем, датирован и подписан.",
            "Печатный текст с подписью от руки требует обязательного присутствия двух дееспособных свидетелей (ст. 1656 CCC)."
        ],
        "forbidden_claims": [
            "Завещание без печати МИД и трёх министерств не имеет никакой юридической силы."
        ]
    }
]
