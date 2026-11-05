import os
import json
import requests
from datetime import datetime, timedelta
from typing import List, Literal, Optional
from pydantic import BaseModel, Field
from openai import OpenAI
import anthropic

# =====================================================================
# 1. PYDANTIC SCHEMAS (Deterministic Data Contracts)
# =====================================================================

class ContractualTriggerRule(BaseModel):
    rule_id: str = Field(description="Unique ID, e.g., 'RULE_01_ATA_NOTICE' or 'RULE_02_OBSTACLE'")
    trigger_category: Literal[
        "ÄTA / Change Order (Likställd ÄTA)",
        "Delay / Obstacle (Hinder & Tidsförlängning)",
        "Loyalty / Clarification Duty (Underrättelseplikt / Lojalitetsplikt)",
        "Passivity Trap / Objection Required (Reklamation / Passivitetsverkan)",
        "Defect / Liability (Felansvar)"
    ]
    base_standard_clause: str = Field(description="Reference to the base standard contract, e.g., 'AB 04 Kap. 2 § 7'")
    overridden_by_custom_terms: bool = Field(description="True if the Kontrakt or AF-del modifies the base standard rule")
    override_clause_reference: Optional[str] = Field(description="Reference to the overriding clause in the main contract/AF, or None")
    effective_rule_logic: str = Field(description="Clear synthesis of the final binding rule after applying contractual hierarchy")
    deadline_type: Literal["FIXED_DAYS", "WITHOUT_UNREASONABLE_DELAY", "IMMEDIATE"]
    deadline_days: Optional[int] = Field(description="Exact number of calendar days if FIXED_DAYS. If 'utan dröjsmål', default to 5 as a safe operational buffer.")
    required_recipient: str = Field(description="Exact role/person who must receive formal notice per the contract")
    required_channel: str = Field(description="Formal communication channel required")
    consequence_of_non_compliance: str = Field(description="Legal/commercial consequence if missed")

class ContractPlaybook(BaseModel):
    project_name: str
    compiled_rules: List[ContractualTriggerRule]

class TriggerMatchAnalysis(BaseModel):
    is_trigger_detected: bool = Field(description="True if the communication contains an explicit or latent contractual trigger")
    matched_rule_id: Optional[str] = Field(description="The rule_id from the ContractPlaybook that applies, or None")
    severity: Literal["CRITICAL_PRECLUSION_RISK", "PROCEDURAL_FLAW_WARNING", "LOW_MONITOR", "SAFE"]
    verbatim_evidence_quote: Optional[str] = Field(description="Exact word-for-word substring from the email/minutes. DO NOT paraphrase.")
    procedural_defect_spotted: Optional[str] = Field(description="Did they send it to the wrong person or channel?")
    legal_and_commercial_reasoning: str = Field(description="Concise explanation connecting the operational fact to the rule")
    recommended_days_to_act: int = Field(description="Number of days from the email timestamp within which formal notice must be sent")
    draft_formal_notice: Optional[str] = Field(description="Ready-to-send formal written notice addressed to the correct recipient")

# =====================================================================
# 2. SYSTEM PROMPTS (Node 1 & Node 2/3)
# =====================================================================

NODE_1_SYSTEM_PROMPT = """
You are a Senior Legal Engineer specializing in commercial and construction contract law (specifically standard frameworks like AB 04 / ABT 06 and bespoke commercial agreements).

Your task is to compile a deterministic 'ContractPlaybook' of all notification triggers, time-bars (preklusionsfrister), and passive objection duties from the provided contract documents.

CRITICAL LEGAL ENGINEERING RULES:
1. HIERARCHY OF DOCUMENTS (Tolkningsföreträde):
   Always read the Base Standard Clauses alongside the Custom Contract Terms (Kontraktsvillkor / AF-del). If the Custom Contract modifies a deadline, recipient, or form requirement in the Base Standard, the Custom Contract prevails. You MUST set `overridden_by_custom_terms = True` and synthesize the final binding rule in `effective_rule_logic`.
2. FORMALITIES MATTER:
   Pay extreme attention to *who* is authorized to receive notices (e.g., 'Beställarens ombud' vs. a regular project leader) and *how* notices must be delivered.
3. PASSIVITY & LOYALTY TRAPS:
   Do not only extract outbound claim triggers. Also extract rules where a party's silence or failure to object to meeting minutes/instructions creates binding acceptance or breaches the contractual duty of loyalty/clarification (underrättelseplikt).
4. OPERATIONALIZING VAGUE DEADLINES:
   If a rule states notice must be given "utan dröjsmål" (without unreasonable delay), classify `deadline_type` as "WITHOUT_UNREASONABLE_DELAY" and set `deadline_days = 5` as a strict internal risk buffer.
"""

NODE_2_3_SYSTEM_PROMPT = """
You are an AI Operational Risk & Contract Compliance Agent monitoring live project communications against a compiled 'ContractPlaybook'.

Your job is to analyze incoming emails or site meeting minutes and detect latent legal triggers, preclusion risks, passive traps, and procedural defects.

CRITICAL ANALYSIS RULES:
1. TRANSLATE CASUAL LANGUAGE TO LEGAL TRIGGERS:
   Operational staff rarely use legal terms. A casual mention of "rock in the excavation pit", "waiting on drawings", or "swapping the tiles as discussed on site" may trigger strict notice duties for Obstacles (Hinder) or Change Orders (ÄTA).
2. CHECK PROCEDURAL VALIDITY (RECIPIENT & FORM):
   Even if a project manager *thinks* they are giving notice in the email, verify the email metadata (`To`, `From`, `Channel`) against the `required_recipient` and `required_channel` in the Playbook. If a notice is sent to a site engineer instead of the designated 'Ombud', flag `severity = "PROCEDURAL_FLAW_WARNING"` and explain that valid legal notice has NOT yet been served.
3. CATCH PASSIVITY TRAPS:
   If a counterparty writes "As agreed, this work is included in the fixed price" or sends ambiguous instructions, flag the risk of passivity and draft a reservation/clarification notice.
4. ZERO HALLUCINATION GROUNDING:
   `verbatim_evidence_quote` MUST be an exact, character-for-character substring copied from the input communication.
5. DRAFTING THE NOTICE:
   If a trigger is detected, draft a crisp, commercially pragmatic, legally watertight formal notice in the language of the contract (Swedish or English), explicitly citing both the base clause and any overriding contract clause.
"""

# =====================================================================
# 3. PIPELINE EXECUTION FUNCTIONS (MULTI-PROVIDER BYOK)
# =====================================================================

def get_structured_response(provider: str, api_key: str, system_prompt: str, user_content: str, schema_class: type[BaseModel]) -> BaseModel:
    """Helper to route the request to the correct LLM provider and return a validated Pydantic object."""
    
    # Force the LLM to adhere to the schema via prompting (Bulletproof strategy for all providers)
    schema_instructions = f"\n\nIMPORTANT: You MUST return ONLY valid JSON. The JSON must strictly match this schema:\n{json.dumps(schema_class.model_json_schema())}"
    final_system_prompt = system_prompt + schema_instructions

    if provider == "OpenAI":
        client = OpenAI(api_key=api_key)
        # Switched to gpt-4o-mini and native JSON mode to avoid .parse() strictness errors and 404s
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": final_system_prompt},
                {"role": "user", "content": user_content}
            ],
            temperature=0.0,
            response_format={"type": "json_object"}
        )
        raw_json = response.choices[0].message.content
        return schema_class.model_validate_json(raw_json)
        
    elif provider == "Gemini":
        # Switched to Google's Native REST API (requests) to completely bypass OpenAI compatibility wrapper bugs
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
        payload = {
            "contents": [
                {"role": "user", "parts": [{"text": final_system_prompt + "\n\nUser Input:\n" + user_content}]}
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.0
            }
        }
        resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"})
        
        if resp.status_code != 200:
            raise ValueError(f"Gemini API Error {resp.status_code}: {resp.text}")
            
        data = resp.json()
        try:
            raw_json = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            raise ValueError(f"Unexpected Gemini response structure: {data}")
            
        return schema_class.model_validate_json(raw_json)
        
    elif provider == "Claude":
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=4096,
            temperature=0.0,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
            tools=[{
                "name": "output_formatter",
                "description": "Output the final structured data.",
                "input_schema": schema_class.model_json_schema()
            }],
            tool_choice={"type": "tool", "name": "output_formatter"}
        )
        for block in response.content:
            if block.type == "tool_use" and block.name == "output_formatter":
                return schema_class.model_validate(block.input)
        raise ValueError("Claude did not return the expected structured output.")

    else:
        raise ValueError(f"Unsupported provider: {provider}")


def compile_contract_playbook(base_clauses_text: str, custom_contract_text: str, provider: str, api_key: str) -> ContractPlaybook:
    """Node 1: Compiles raw contract text and overrides into a structured JSON Playbook."""
    user_content = f"""
    --- DOCUMENT 1:CUSTOM CONTRACT TERMS (RANK 1 PRIORITY) ---
    {custom_contract_text}

    --- DOCUMENT 2: BASE STANDARD TERMS (RANK 2 PRIORITY) ---
    {base_clauses_text}
    """
    return get_structured_response(provider, api_key, NODE_1_SYSTEM_PROMPT, user_content, ContractPlaybook)

def calculate_deterministic_deadline(email_date_str: str, days_to_add: int) -> str:
    """Deterministic Python helper so the LLM never does mental calendar math."""
    email_dt = datetime.fromisoformat(email_date_str)
    deadline_dt = email_dt + timedelta(days=days_to_add)
    return deadline_dt.strftime("%Y-%m-%d")

def analyze_project_communication(playbook: ContractPlaybook, email_data: dict, provider: str, api_key: str) -> dict:
    """Nodes 2 & 3: Evaluates an incoming email against the compiled Playbook."""
    user_content = f"""
    --- COMPILED CONTRACT PLAYBOOK (JSON) ---
    {playbook.model_dump_json(indent=2)}

    --- INCOMING PROJECT COMMUNICATION ---
    Timestamp: {email_data['timestamp']}
    From: {email_data['sender']}
    To: {email_data['recipient']}
    Channel: {email_data['channel']}
    Subject: {email_data['subject']}
    Body:
    {email_data['body']}
    """

    analysis = get_structured_response(provider, api_key, NODE_2_3_SYSTEM_PROMPT, user_content, TriggerMatchAnalysis)
    
    result = analysis.model_dump()
    if analysis.is_trigger_detected:
        result["calculated_hard_deadline"] = calculate_deterministic_deadline(
            email_data["timestamp"], 
            analysis.recommended_days_to_act
        )
    else:
        result["calculated_hard_deadline"] = None
        
    return result

if __name__ == "__main__":
    print("Backend configured for BYOK (OpenAI, Gemini, Claude). Use app.py to interact.")
