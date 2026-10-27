import os
from openai import OpenAI

# Initialize the OpenAI client pointing to Google Gemini's endpoint
client = OpenAI(
    api_key=os.environ.get("GEMINI_API_KEY"),
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
)

# =====================================================================
# 1. PYDANTIC SCHEMAS (Deterministic Data Contracts)
# =====================================================================

class ContractualTriggerRule(BaseModel):
    rule_id: str = Field(
        description="Unique ID, e.g., 'RULE_01_ATA_NOTICE' or 'RULE_02_OBSTACLE'"
    )
    trigger_category: Literal[
        "ÄTA / Change Order (Likställd ÄTA)",
        "Delay / Obstacle (Hinder & Tidsförlängning)",
        "Loyalty / Clarification Duty (Underrättelseplikt / Lojalitetsplikt)",
        "Passivity Trap / Objection Required (Reklamation / Passivitetsverkan)",
        "Defect / Liability (Felansvar)"
    ]
    base_standard_clause: str = Field(
        description="Reference to the base standard contract, e.g., 'AB 04 Kap. 2 § 7'"
    )
    overridden_by_custom_terms: bool = Field(
        description="True if the Kontrakt or AF-del modifies the base standard rule"
    )
    override_clause_reference: Optional[str] = Field(
        description="Reference to the overriding clause in the main contract/AF, or None"
    )
    effective_rule_logic: str = Field(
        description="Clear synthesis of the final binding rule after applying contractual hierarchy"
    )
    deadline_type: Literal["FIXED_DAYS", "WITHOUT_UNREASONABLE_DELAY", "IMMEDIATE"]
    deadline_days: Optional[int] = Field(
        description="Exact number of calendar days if FIXED_DAYS. If 'utan dröjsmål', default to 5 as a safe operational buffer."
    )
    required_recipient: str = Field(
        description="Exact role/person who must receive formal notice per the contract (e.g., 'Beställarens ombud')"
    )
    required_channel: str = Field(
        description="Formal communication channel required (e.g., 'Written email to ombud, NOT site minutes')"
    )
    consequence_of_non_compliance: str = Field(
        description="Legal/commercial consequence if missed (e.g., 'Preklusion - loss of right to compensation')"
    )

class ContractPlaybook(BaseModel):
    project_name: str
    compiled_rules: List[ContractualTriggerRule]


class TriggerMatchAnalysis(BaseModel):
    is_trigger_detected: bool = Field(
        description="True if the communication contains an explicit or latent contractual trigger or procedural flaw"
    )
    matched_rule_id: Optional[str] = Field(
        description="The rule_id from the ContractPlaybook that applies, or None"
    )
    severity: Literal["CRITICAL_PRECLUSION_RISK", "PROCEDURAL_FLAW_WARNING", "LOW_MONITOR", "SAFE"]
    verbatim_evidence_quote: Optional[str] = Field(
        description="Exact word-for-word substring from the email/minutes that triggered this alert. DO NOT paraphrase."
    )
    procedural_defect_spotted: Optional[str] = Field(
        description="If the sender tried to notify, did they send it to the wrong person or wrong channel per the rule?"
    )
    legal_and_commercial_reasoning: str = Field(
        description="Concise explanation connecting the operational fact in the email to the specific rule in the playbook"
    )
    recommended_days_to_act: int = Field(
        description="Number of days from the email timestamp within which formal notice must be sent"
    )
    draft_formal_notice: Optional[str] = Field(
        description="Ready-to-send formal written notice addressed to the correct recipient, citing the exact contract clauses"
    )


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
# 3. PIPELINE EXECUTION FUNCTIONS
# =====================================================================

def compile_contract_playbook(base_clauses_text: str, custom_contract_text: str) -> ContractPlaybook:
    """Node 1: Compiles raw contract text and overrides into a structured JSON Playbook."""
    user_content = f"""
    --- DOCUMENT 1:CUSTOM CONTRACT TERMS (RANK 1 PRIORITY) ---
    {custom_contract_text}

    --- DOCUMENT 2: BASE STANDARD TERMS (RANK 2 PRIORITY) ---
    {base_clauses_text}
    """
    
    response = client.beta.chat.completions.parse(
        model="gpt-4o-2024-08-06", # Or latest structured-output supporting model
        messages=[
            {"role": "system", "content": NODE_1_SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ],
        response_format=ContractPlaybook,
        temperature=0.0 # Zero temperature for deterministic legal extraction
    )
    return response.choices[0].message.parsed


def calculate_deterministic_deadline(email_date_str: str, days_to_add: int) -> str:
    """Deterministic Python helper so the LLM never does mental calendar math."""
    email_dt = datetime.fromisoformat(email_date_str)
    deadline_dt = email_dt + timedelta(days=days_to_add)
    return deadline_dt.strftime("%Y-%m-%d")


def analyze_project_communication(playbook: ContractPlaybook, email_data: dict) -> dict:
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

    response = client.beta.chat.completions.parse(
        model="gemini-2.5-flash",
        messages=[
            {"role": "system", "content": NODE_2_3_SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ],
        response_format=TriggerMatchAnalysis,
        temperature=0.0
    )
    
    analysis: TriggerMatchAnalysis = response.choices[0].message.parsed
    
    # Combine LLM semantic analysis with deterministic Python date calculation
    result = analysis.model_dump()
    if analysis.is_trigger_detected:
        result["calculated_hard_deadline"] = calculate_deterministic_deadline(
            email_data["timestamp"], 
            analysis.recommended_days_to_act
        )
    else:
        result["calculated_hard_deadline"] = None
        
    return result


# =====================================================================
# 4. MOCK TEST RUN (Demonstrating Hierarchy + Procedural Trap)
# =====================================================================

if __name__ == "__main__":
    # Mock Base Standard Clauses (e.g., excerpts modeled on AB 04 principles)
    mock_base_standard = """
    AB 04 Kap. 2 § 7 (Underrättelse om likställd ÄTA):
    Om entreprenören anser att ett förhållande utgör likställd ÄTA-arbete ska han 
    utan dröjsmål och innan arbetet påbörjas inhämta beställarens synpunkter. 
    Underlåtenhet medför att rätten till ersättning går förlorad (preklusion).
    
    AB 04 Kap. 4 § 4 (Underrättelse om hinder):
    Part ska utan dröjsmål underrätta motparten om han anser att hinder föreligger 
    som berättigar till tidsförlängning.
    """

    # Mock Custom Contract (Särskilda Kontraktsvillkor) that overrides the base standard!
    mock_custom_contract = """
    ENTREPRENADKONTRAKT - PROJEKT KVARTERET KRONAN
    § 1. Ombud och behörighet
    Beställarens ombud är Anna Lindqvist (anna.lindqvist@fastighetsbolaget.se). 
    Endast Ombudet har behörighet att motta formella underrättelser om ÄTA och hinder. 
    Byggledare på plats (t.ex. Erik Svensson) saknar behörighet att beställa ÄTA eller motta reklamationer/hinderanmälan.
    
    § 2. Ändring av AB 04 Kap. 2 § 7 och Kap. 4 § 4 (Preklusionsfrist)
    Med ändring av AB 04 ska begreppet "utan dröjsmål" avseende ÄTA-anmälan och hinderanmälan 
    ersättas med en strikt frist om senast sju (7) kalenderdagar från det att entreprenören 
    insåg eller borde ha insett förhållandet. Anmälan ska ske skriftligen via e-post direkt till Beställarens ombud.
    """

    # Mock Email containing BOTH a latent ÄTA/Obstacle AND a procedural recipient mistake
    mock_email = {
        "timestamp": "2026-10-27",
        "sender": "Johan (Platschef, Entreprenören AB)",
        "recipient": "Erik Svensson (Byggledare, Fastighetsbolaget)", # TRAP: Sent to Byggledare, NOT Ombud!
        "channel": "Email",
        "subject": "Schaktning vid hus B - gammal betongkulvert",
        "body": (
            "Tjena Erik! När vi grävde för grunden vid Hus B imorse stötte vi på en gammal "
            "armerad betongkulvert som inte fanns med på era ritningar. Vi blir tvungna att "
            "ta in bilningsutrustning imorgon bitti för att få bort den, vilket kommer kosta "
            "runt 85 000 kr extra och förskjuta tidsplanen med 3 dagar. Tänkte bara så du vet!"
        )
    }

    print("1. Compiling Contract Playbook (Resolving Hierarchy)...")
    playbook = compile_contract_playbook(mock_base_standard, mock_custom_contract)
    print(playbook.model_dump_json(indent=2))

    print("\n2. Analyzing Incoming Project Email...")
    alert = analyze_project_communication(playbook, mock_email)
    print(json.dumps(alert, indent=2, ensure_ascii=False))
