#!/usr/bin/env python3
"""
backend/i18n.py
Reactive Multi-Lingual Translation & UI Strings Engine for Consultant+.
Order of Priority: English (Default) > Thai > Russian > Chinese.
"""

from typing import Dict, Any

TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "app_title": {
        "en": "Consultant+ — Legal AI Advisor",
        "th": "Consultant+ — ที่ปรึกษากฎหมายไทยอัจฉริยะ",
        "ru": "КонсультантПлюс Таиланд — Правовой ИИ-советник",
        "zh": "Consultant+ — 泰国法律人工智能顾问"
    },
    "app_subtitle": {
        "en": "Official Statutes, Royal Gazettes & Supreme Court Judgments",
        "th": "รวบรวมพระราชบัญญัติ ราชกิจจานุเบกษา และคำพิพากษาศาลฎีกา",
        "ru": "Королевские указы, законы, официальный вестник и решения Верховного Суда",
        "zh": "官方成文法典、皇家公报及最高法院判决库"
    },
    "search_placeholder": {
        "en": "Ask a legal question or search Section/Act (e.g., 'Civil Code Section 1523', 'Foreign business license')...",
        "th": "พิมพ์คำถามทางกฎหมาย หรือค้นหามาตรา/พ.ร.บ. (เช่น 'มาตรา 1523', 'ใบอนุญาตประกอบธุรกิจคนต่างด้าว')...",
        "ru": "Задайте юридический вопрос или введите статью/закон (напр., 'Статья 1523 ГК', 'Покупка кондоминиума иностранцем')...",
        "zh": "输入法律问题或搜索法条（如：'民商法典第1523条'、'外商经营许可证'）..."
    },
    "btn_search": {
        "en": "Analyze Legal Query",
        "th": "วิเคราะห์ข้อกฎหมาย",
        "ru": "Анализировать вопрос",
        "zh": "检索分析法条"
    },
    "btn_switch_lang": {
        "en": "Language",
        "th": "เปลี่ยนภาษา",
        "ru": "Язык",
        "zh": "切换语言"
    },
    "sources_found": {
        "en": "Official Legal Sources Cited",
        "th": "แหล่งอ้างอิงกฎหมายอย่างเป็นทางการ",
        "ru": "Официальные источники и прецеденты",
        "zh": "援引官方权威法律条文"
    },
    "clarification_title": {
        "en": "Proactive Legal Clarifications Needed",
        "th": "ประเด็นที่ต้องชี้แจงเพิ่มเติมเพื่อความแม่นยำทางกฎหมาย",
        "ru": "Уточняющие вопросы для точной правовой квалификации",
        "zh": "为确保法律准确性需进一步澄清的事实"
    },
    "legal_disclaimer": {
        "en": "Disclaimer: This system provides statutory citations and jurisprudence for guidance. For litigation, consult a licensed Thai attorney.",
        "th": "ข้อสงวนสิทธิ์: ระบบนี้ให้บริการข้อมูลตัวบทกฎหมายและคำพิพากษาเพื่อเป็นแนวทาง หากมีข้อพิพาทโปรดปรึกษาทนายความผู้ได้รับอนุญาต",
        "ru": "Предупреждение: Система предоставляет ссылки на нормы права и судебные решения. Для судебных дел обратитесь к лицензированному тайскому адвокату.",
        "zh": "免责声明：本系统提供法定法条及判例指引，具体诉讼业务请咨询泰国执业律师。"
    },
    "domain_criminal": {
        "en": "Criminal Law",
        "th": "กฎหมายอาญา",
        "ru": "Уголовное право",
        "zh": "刑法"
    },
    "domain_civil": {
        "en": "Civil & Commercial Code",
        "th": "ประมวลกฎหมายแพ่งและพาณิชย์",
        "ru": "Гражданский и коммерческий кодекс",
        "zh": "民商法典"
    },
    "domain_land": {
        "en": "Land & Property Law",
        "th": "กฎหมายที่ดินและอสังหาริมทรัพย์",
        "ru": "Земельное право и недвижимость",
        "zh": "土地与不动产法"
    },
    "domain_corporate": {
        "en": "Foreign Business & Corporate Law",
        "th": "กฎหมายธุรกิจและการลงทุนของคนต่างด้าว",
        "ru": "Корпоративное право и иностранные инвестиции",
        "zh": "外资与公司法"
    }
}


def get_text(key: str, lang: str = "en") -> str:
    """Returns localized string without page reload."""
    lang = lang.lower()
    if lang not in ["en", "th", "ru", "zh"]:
        lang = "en"
    entry = TRANSLATIONS.get(key, {})
    return entry.get(lang, entry.get("en", key))


def get_all_ui_strings(lang: str = "en") -> Dict[str, str]:
    """Returns full UI bundle for client-side dynamic rendering."""
    lang = lang.lower()
    if lang not in ["en", "th", "ru", "zh"]:
        lang = "en"
    return {k: v.get(lang, v.get("en", k)) for k, v in TRANSLATIONS.items()}
