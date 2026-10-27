import os
import re
import json
from datetime import datetime, timedelta
import pandas as pd
import streamlit as st
from openai import OpenAI

# Import schemas and functions from your backend file (notice_tracker.py)
from notice_tracker import (
    ContractPlaybook,
    ContractualTriggerRule,
    TriggerMatchAnalysis,
    compile_contract_playbook,
    analyze_project_communication,
)

# =====================================================================
# PAGE CONFIGURATION & STYLING
# =====================================================================
st.set_page_config(
    page_title="PreclusionGuard AI | Operational Contract Intelligence",
    page_icon="⚖️",
    layout="wide",
)

st.markdown("""
<style>
    .highlight-quote {
        background-color: #ffeeba;
        padding: 2px 6px;
        border-radius: 4px;
        border-left: 4px solid #d39e00;
        font-weight: 600;
        color: #212529;
    }
    .override-badge {
        background-color: #f8d7da;
        color: #721c24;
        padding: 3px 8px;
        border-radius: 12px;
        font-size: 0.8em;
        font-weight: 600;
    }
    .standard-badge {
        background-color: #d4edda;
        color: #155724;
        padding: 3px 8px;
        border-radius: 12px;
        font-size: 0.8em;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

# =====================================================================
# DEFAULT SYNTHETIC DATA (AB 04 + Custom Overrides + 4 Inbox Scenarios)
# =====================================================================

DEFAULT_BASE_STANDARD = """AB 04 Kap. 2 § 7 (Underrättelse om likställd ÄTA):
Om entreprenören anser att ett förhållande utgör likställd ÄTA-arbete ska han utan dröjsmål och innan arbetet påbörjas inhämta beställarens synpunkter. Underlåtenhet medför att rätten till ersättning går förlorad (preklusion).

AB 04 Kap. 4 § 4 (Underrättelse om hinder):
Part ska utan dröjsmål underrätta motparten om han anser att hinder föreligger som berättigar till tidsförlängning.

AB 04 Kap. 2 § 1 & Allmän lojalitetsplikt (Underrättelse- och klargörandeplikt):
Upptäcker part motstridigheter i handlingar eller får part en tvetydig anvisning från motparten föreligger en kontraktuell lojalitetsplikt att utan dröjsmål påtala detta för att undvika passivitetsverkan."""

DEFAULT_CUSTOM_CONTRACT = """ENTREPRENADKONTRAKT - PROJEKT KVARTERET KRONAN (SÄRSKILDA KONTRAKTSVILLKOR / AF-DEL)

§ 1. Ombud och behörighet (Ändring av standardbehörighet)
Beställarens ombud är Anna Lindqvist (anna.lindqvist@fastighetsbolaget.se). Endast Ombudet har behörighet att motta formella underrättelser om ÄTA, hinder och reklamationer. Byggledare på plats (t.ex. Erik Svensson) saknar behörighet att beställa ÄTA eller motta formella underrättelser med rättsverkan.

§ 2. Skärpt preklusionsfrist (Ändring av AB 04 Kap. 2 § 7 och Kap. 4 § 4)
Med ändring av AB 04 ska begreppet "utan dröjsmål" avseende ÄTA-anmälan och hinderanmälan ersättas med en strikt preklusionsfrist om senast sju (7) kalenderdagar från det att entreprenören insåg eller borde ha insett förhållandet. Anmälan ska ske skriftligen via e-post direkt till Beställarens ombud.

§ 3. Passivitetsverkan vid byggmötesprotokoll
Invändning mot uppgift eller ekonomisk allokering i byggmötesprotokoll ska framställas skriftligen till Beställarens ombud senast fem (5) kalenderdagar efter att protokollet distribuerats, vid äventyr av att protokollets innehåll annars anses bindande godkänt."""

MOCK_INBOX = [
    {
        "id": "MSG-101",
        "label": "🔴 [Trap 1: Wrong Recipient] Unforeseen Concrete Culvert",
        "timestamp": "2026-10-27",
        "sender": "Johan Berg (Platschef, Entreprenören AB)",
        "recipient": "Erik Svensson (Byggledare, Fastighetsbolaget)",
        "channel": "Email",
        "subject": "Schaktning vid hus B - gammal betongkulvert",
        "body": (
            "Tjena Erik! När vi grävde för grunden vid Hus B imorse stötte vi på en gammal "
            "armerad betongkulvert som inte fanns med på era ritningar. Vi blir tvungna att "
            "ta in bilningsutrustning imorgon bitti för att få bort den, vilket kommer kosta "
            "runt 85 000 kr extra och förskjuta tidsplanen med 3 dagar. Tänkte bara så du vet!"
        ),
    },
    {
        "id": "MSG-102",
        "label": "🟠 [Trap 2: Passivity / Loyalty Risk] Site Meeting Minutes #14",
        "timestamp": "2026-10-27",
        "sender": "Erik Svensson (Byggledare, Fastighetsbolaget)",
        "recipient": "Johan Berg (Platschef, Entreprenören AB)",
        "channel": "Distributed Site Meeting Minutes (Byggmötesprotokoll)",
        "subject": "Protokoll Byggmöte #14 - Kvarteret Kronan",
        "body": (
            "Punkt 14.3 Ventilation: Noterades att fläktrummet i källaren måste flyttas 2 meter "
            "söderut p.g.a. ändrad takhöjd. Parterna är överens om att Entreprenören utför denna "
            "omdragning av kanaler inom ramen för befintlig kontraktssumma utan rätt till tidsförlängning."
        ),
    },
    {
        "id": "MSG-103",
        "label": "🟡 [Latent Delay Trigger] Delayed Facade Blueprints",
        "timestamp": "2026-10-27",
        "sender": "Sara Nordin (Arbetsledare, Entreprenören AB)",
        "recipient": "Anna Lindqvist (Beställarens Ombud)",
        "channel": "Email",
        "subject": "Angående detaljritningar för fasadinfästning",
        "body": (
            "Hej Anna, vi väntar fortfarande på de reviderade konstruktionsritningarna för "
            "fasadinfästningen på plan 4 som skulle kommit i fredags. Våra montörer står "
            "snart utan arbete på den etappen om vi inte får underlaget senast imorgon."
        ),
    },
    {
        "id": "MSG-104",
        "label": "🟢 [True Negative / Safe] Crane Delivery Coordination",
        "timestamp": "2026-10-27",
        "sender": "Johan Berg (Platschef, Entreprenören AB)",
        "recipient": "Erik Svensson (Byggledare, Fastighetsbolaget)",
        "channel": "Email",
        "subject": "Leverans av mobilkran torsdag morgon",
        "body": (
            "Hej Erik, ville bara bekräfta att mobilkranen anländer kl 06:30 på torsdag "
            "enligt ordinarie tidplan. Grind B hålls öppen. Ingen påverkan på övriga moment eller budget."
        ),
    }
]

# =====================================================================
# SIDEBAR: CONFIGURATION & ARCHITECTURE INFO
# =====================================================================
with st.sidebar:
    st.title("⚙️ Engine Settings")
    api_key_input = st.text_input(
        "OpenAI API Key", 
        value=os.environ.get("OPENAI_API_KEY", ""), 
        type="password",
        help="Required to run live LLM extraction."
    )
    if api_key_input:
        os.environ["OPENAI_API_KEY"] = api_key_input

    st.divider()
    st.subheader("🏗️ Pipeline Architecture")
    st.caption("""
    **Node 1 (Compiler):** Resolves hierarchy between Base Standard (AB 04) and Custom Contract Terms (*Tolkningsföreträde*) into a typed Pydantic `ContractPlaybook`.
    
    **Node 2 (Triage & Grounding):** Scans operational messages for latent triggers, verifying exact substring quotes.
    
    **Node 3 (Procedural & Date Engine):** Checks recipient authority (*Behörighet*) + runs deterministic Python date math.
    """)

# =====================================================================
# MAIN HEADER
# =====================================================================
st.title("⚖️ PreclusionGuard: Cross-Document Notice & Loyalty Tracker")
st.markdown(
    "**Bridging the gap between static contract playbooks and live operational project communications.**"
)

tab1, tab2 = st.tabs([
    "📜 Step 1: Contract Playbook Compiler (Node 1)", 
    "📬 Step 2: Live Project Inbox Monitor (Nodes 2 & 3)"
])

# =====================================================================
# TAB 1: NODE 1 (CONTRACT COMPILER)
# =====================================================================
with tab1:
    st.subheader("Compile Contractual Trigger Matrix & Resolve Hierarchy")
    st.markdown(
        "Feed the base framework (e.g., **AB 04**) alongside the project-specific overrides (**Kontraktsvillkor / AF-del**). "
        "Node 1 enforces *tolkningsföreträde* and compiles a structured JSON ruleset."
    )

    col_left, col_right = st.columns(2)
    with col_left:
        custom_text = st.text_area(
            "🥇 Priority 1: Custom Contract & Appendices (Kontrakt / AF-del)",
            value=DEFAULT_CUSTOM_CONTRACT,
            height=260
        )
    with col_right:
        base_text = st.text_area(
            "🥈 Priority 2: Base Standard Terms (e.g., AB 04)",
            value=DEFAULT_BASE_STANDARD,
            height=260
        )

    if st.button("🚀 Compile Contract Playbook (Run Node 1)", type="primary"):
        if not os.environ.get("OPENAI_API_KEY"):
            st.error("Please enter your OpenAI API Key in the sidebar to run live compilation.")
        else:
            with st.spinner("Resolving document hierarchy and extracting structured rules..."):
                playbook = compile_contract_playbook(base_text, custom_text)
                st.session_state["playbook"] = playbook
                st.success(f"Compiled {len(playbook.compiled_rules)} binding rules for {playbook.project_name}!")

    # Display Compiled Playbook if available
    if "playbook" in st.session_state:
        pb: ContractPlaybook = st.session_state["playbook"]
        st.divider()
        st.markdown(f"### 📋 Active Rule Matrix: `{pb.project_name}`")

        for rule in pb.compiled_rules:
            badge_html = (
                '<span class="override-badge">⚡ Overridden by Custom Contract</span>'
                if rule.overridden_by_custom_terms
                else '<span class="standard-badge">✓ Base Standard Applies</span>'
            )
            with st.expander(f"**{rule.rule_id}** — {rule.trigger_category} ({rule.base_standard_clause})", expanded=True):
                st.markdown(badge_html, unsafe_allow_html=True)
                c1, c2, c3 = st.columns(3)
                c1.metric("Strict Deadline", f"{rule.deadline_days} Days", rule.deadline_type)
                c2.markdown(f"**Required Recipient:**\n`{rule.required_recipient}`")
                c3.markdown(f"**Required Channel:**\n`{rule.required_channel}`")
                
                st.markdown(f"**Synthesized Binding Rule:** {rule.effective_rule_logic}")
                if rule.override_clause_reference:
                    st.caption(f"Modified by: {rule.override_clause_reference} | Risk: {rule.consequence_of_non_compliance}")

# =====================================================================
# TAB 2: NODES 2 & 3 (LIVE INBOX MONITOR)
# =====================================================================
with tab2:
    if "playbook" not in st.session_state:
        st.warning("⚠️ Please compile the Contract Playbook in **Step 1** first so the Inbox Agent has rules to evaluate against.")
    else:
        st.subheader("Live Project Communications Monitor")
        
        inbox_col, analysis_col = st.columns([1, 1.3], gap="large")

        with inbox_col:
            st.markdown("#### 📥 Select Incoming Communication")
            selected_label = st.radio(
                "Project Feed:",
                options=[m["label"] for m in MOCK_INBOX],
                index=0
            )
            selected_msg = next(m for m in MOCK_INBOX if m["label"] == selected_label)

            st.markdown("#### 📄 Message Envelope & Raw Content")
            with st.container(border=True):
                st.markdown(f"**Timestamp:** `{selected_msg['timestamp']}`")
                st.markdown(f"**From:** `{selected_msg['sender']}`")
                st.markdown(f"**To:** `{selected_msg['recipient']}`")
                st.markdown(f"**Channel:** `{selected_msg['channel']}`")
                st.markdown(f"**Subject:** **{selected_msg['subject']}**")
                st.divider()
                
                # If analysis has run for this message, highlight the exact quote!
                body_display = selected_msg["body"]
                current_analysis = st.session_state.get(f"analysis_{selected_msg['id']}")
                
                if current_analysis and current_analysis.get("verbatim_evidence_quote"):
                    quote = current_analysis["verbatim_evidence_quote"]
                    if quote in body_display:
                        body_display = body_display.replace(
                            quote, f'<span class="highlight-quote">{quote}</span>'
                        )
                st.markdown(body_display, unsafe_allow_html=True)

            analyze_btn = st.button("🔍 Evaluate Against Contract Playbook (Run Nodes 2 & 3)", type="primary", use_container_width=True)

        with analysis_col:
            st.markdown("#### 🧠 Legal & Operational Risk Intelligence")
            
            if analyze_btn:
                if not os.environ.get("OPENAI_API_KEY"):
                    st.error("Please enter your OpenAI API Key in the sidebar.")
                else:
                    with st.spinner("Analyzing latent triggers, recipient authority, and preclusion clocks..."):
                        res = analyze_project_communication(st.session_state["playbook"], selected_msg)
                        # Deterministic Substring Verification Check
                        quote = res.get("verbatim_evidence_quote")
                        res["grounding_verified"] = bool(quote and quote in selected_msg["body"])
                        st.session_state[f"analysis_{selected_msg['id']}"] = res

            result = st.session_state.get(f"analysis_{selected_msg['id']}")
            
            if not result:
                st.info("Click **Evaluate Against Contract Playbook** on the left to inspect this message.")
            else:
                # 1. Top Status Banner
                sev = result["severity"]
                if sev == "CRITICAL_PRECLUSION_RISK":
                    st.error(f"🚨 **CRITICAL PRECLUSION RISK DETECTED** (Matched Rule: `{result['matched_rule_id']}`)")
                elif sev == "PROCEDURAL_FLAW_WARNING":
                    st.warning(f"⚠️ **PROCEDURAL FLAW / INVALID NOTICE DETECTED** (Matched Rule: `{result['matched_rule_id']}`)")
                elif sev == "LOW_MONITOR":
                    st.info(f"ℹ️ **LOW RISK / MONITOR** (Matched Rule: `{result['matched_rule_id']}`)")
                else:
                    st.success("✅ **NO CONTRACTUAL TRIGGER DETECTED (SAFE)**")

                # 2. Key Metrics Row (Deterministic Date + Grounding Check)
                if result["is_trigger_detected"]:
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Hard Preclusion Deadline", result["calculated_hard_deadline"], f"{result['recommended_days_to_act']} Days Window")
                    m2.metric("Matched Playbook Rule", result["matched_rule_id"])
                    m3.metric(
                        "Substring Grounding", 
                        "100% Verified" if result["grounding_verified"] else "Failed",
                        "Zero Hallucination Check"
                    )

                    # 3. Procedural Defect Alert (if any)
                    if result.get("procedural_defect_spotted"):
                        st.warning(f"**Procedural Authority Trap Spotted:** {result['procedural_defect_spotted']}")

                    # 4. Legal & Commercial Reasoning
                    with st.container(border=True):
                        st.markdown("**Legal & Commercial Analysis:**")
                        st.write(result["legal_and_commercial_reasoning"])
                        st.caption(f"**Extracted Evidence Substring:** *\"{result['verbatim_evidence_quote']}\"*")

                    # 5. Ready-to-Send Formal Notice
                    if result.get("draft_formal_notice"):
                        st.markdown("#### ✉️ Auto-Drafted Formal Notice (Ready to Send)")
                        st.code(result["draft_formal_notice"], language="markdown")
                else:
                    st.write(result["legal_and_commercial_reasoning"])