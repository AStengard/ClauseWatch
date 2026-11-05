import os
import re
import json
from datetime import datetime, timedelta
import pandas as pd
import streamlit as st

from notice_tracker import (
    ContractPlaybook,
    ContractualTriggerRule,
    TriggerMatchAnalysis,
    compile_contract_playbook,
    analyze_project_communication,
)

# =====================================================================
# SIDKONFIGURATION & DESIGN (CSS)
# =====================================================================
st.set_page_config(
    page_title="ClauseWatch | Operativ Kontraktsbevakning",
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
# STANDARDDATA FÖR DEMONSTRATION
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
        "label": "🔴 [Fälla 1: Fel mottagare] Oförutsedd betongkulvert",
        "timestamp": "2026-10-27",
        "sender": "Johan Berg (Platschef, Entreprenören AB)",
        "recipient": "Erik Svensson (Byggledare, Fastighetsbolaget)",
        "channel": "E-post",
        "subject": "Schaktning vid hus B - gammal betongkulvert",
        "body": "Tjena Erik! När vi grävde för grunden vid Hus B imorse stötte vi på en gammal armerad betongkulvert som inte fanns med på era ritningar. Vi blir tvungna att ta in bilningsutrustning imorgon bitti för att få bort den, vilket kommer kosta runt 85 000 kr extra och förskjuta tidsplanen med 3 dagar. Tänkte bara så du vet!"
    },
    {
        "id": "MSG-102",
        "label": "🟠 [Fälla 2: Passivitet / Lojalitetsrisk] Byggmötesprotokoll #14",
        "timestamp": "2026-10-27",
        "sender": "Erik Svensson (Byggledare, Fastighetsbolaget)",
        "recipient": "Johan Berg (Platschef, Entreprenören AB)",
        "channel": "Distribuerat Byggmötesprotokoll",
        "subject": "Protokoll Byggmöte #14 - Kvarteret Kronan",
        "body": "Punkt 14.3 Ventilation: Noterades att fläktrummet i källaren måste flyttas 2 meter söderut p.g.a. ändrad takhöjd. Parterna är överens om att Entreprenören utför denna omdragning av kanaler inom ramen för befintlig kontraktssumma utan rätt till tidsförlängning."
    },
    {
        "id": "MSG-103",
        "label": "🟡 [Dold risk för försening] Försenade fasadritningar",
        "timestamp": "2026-10-27",
        "sender": "Sara Nordin (Arbetsledare, Entreprenören AB)",
        "recipient": "Anna Lindqvist (Beställarens Ombud)",
        "channel": "E-post",
        "subject": "Angående detaljritningar för fasadinfästning",
        "body": "Hej Anna, vi väntar fortfarande på de reviderade konstruktionsritningarna för fasadinfästningen på plan 4 som skulle kommit i fredags. Våra montörer står snart utan arbete på den etappen om vi inte får underlaget senast imorgon."
    },
    {
        "id": "MSG-104",
        "label": "🟢 [Ingen risk / Säkert] Samordning av kranleverans",
        "timestamp": "2026-10-27",
        "sender": "Johan Berg (Platschef, Entreprenören AB)",
        "recipient": "Erik Svensson (Byggledare, Fastighetsbolaget)",
        "channel": "E-post",
        "subject": "Leverans av mobilkran torsdag morgon",
        "body": "Hej Erik, ville bara bekräfta att mobilkranen anländer kl 06:30 på torsdag enligt ordinarie tidplan. Grind B hålls öppen. Ingen påverkan på övriga moment eller budget."
    }
]

# =====================================================================
# SIDOMENY
# =====================================================================
with st.sidebar:
    st.title("⚙️ Inställningar (API-nyckel)")
    
    provider = st.selectbox(
        "AI-leverantör",
        options=["OpenAI", "Gemini", "Claude"],
        index=0
    )
    
    api_key = st.text_input(
        f"{provider} API-nyckel", 
        type="password",
        help=f"Ange din {provider} API-nyckel här."
    )
    
    st.session_state["provider"] = provider
    st.session_state["api_key"] = api_key

# =====================================================================
# HUVUDRUBRIK
# =====================================================================
st.title("⚖️ ClauseWatch: Automatisk Avtalsbevakning")
st.caption("*Av Alfred Stengard*")

tab1, tab2 = st.tabs([
    "📜 Steg 1: Kompilera Avtalsregler (Nod 1)", 
    "📬 Steg 2: Övervaka Projektets Inkorg (Nod 2 & 3)"
])

# =====================================================================
# FLIK 1
# =====================================================================
with tab1:
    col_left, col_right = st.columns(2)
    with col_left:
        custom_text = st.text_area(
            "🥇 Prioritet 1: Kontraktsvillkor & AF-del",
            value=DEFAULT_CUSTOM_CONTRACT,
            height=260
        )
    with col_right:
        base_text = st.text_area(
            "🥈 Prioritet 2: Standardavtal (t.ex. AB 04)",
            value=DEFAULT_BASE_STANDARD,
            height=260
        )

    if st.button("🚀 Kompilera Avtalsregler", type="primary"):
        if not st.session_state.get("api_key"):
            st.error("Vänligen ange din API-nyckel i sidomenyn till vänster.")
        else:
            with st.spinner(f"Analyserar och sammanställer regler via {st.session_state['provider']}..."):
                try:
                    playbook = compile_contract_playbook(
                        base_text, 
                        custom_text,
                        st.session_state["provider"],
                        st.session_state["api_key"]
                    )
                    st.session_state["playbook"] = playbook
                    st.success(f"Lyckades! Kompilerade {len(playbook.compiled_rules)} bindande regler för {playbook.project_name}.")
                except Exception as e:
                    st.error(f"🛑 Ett fel uppstod! Information:

{str(e)}")

    if "playbook" in st.session_state:
        pb: ContractPlaybook = st.session_state["playbook"]
        st.divider()
        st.markdown(f"### 📋 Aktiva Avtalsregler: `{pb.project_name}`")

        for rule in pb.compiled_rules:
            badge_html = (
                '<span class="override-badge">⚡ Ändrad av Kontraktsvillkor (AF-del)</span>'
                if rule.overridden_by_custom_terms
                else '<span class="standard-badge">✓ Standardavtal gäller</span>'
            )
            with st.expander(f"**{rule.rule_id}** — {rule.trigger_category} ({rule.base_standard_clause})", expanded=True):
                st.markdown(badge_html, unsafe_allow_html=True)
                c1, c2, c3 = st.columns(3)
                c1.metric("Strikt Tidsfrist", f"{rule.deadline_days} Dagar", rule.deadline_type)
                c2.markdown(f"**Krävd Mottagare:**\n`{rule.required_recipient}`")
                c3.markdown(f"**Krävd Kanal:**\n`{rule.required_channel}`")
                st.markdown(f"**Sammanfattad Bindande Regel:** {rule.effective_rule_logic}")

# =====================================================================
# FLIK 2
# =====================================================================
with tab2:
    if "playbook" not in st.session_state:
        st.warning("⚠️ Vänligen kompilera avtalsreglerna i **Steg 1** först.")
    else:
        inbox_col, analysis_col = st.columns([1, 1.3], gap="large")

        with inbox_col:
            selected_label = st.radio("Projektflöde (Demo):", options=[m["label"] for m in MOCK_INBOX], index=0)
            selected_msg = next(m for m in MOCK_INBOX if m["label"] == selected_label)

            with st.container(border=True):
                st.markdown(f"**Datum/Tid:** `{selected_msg['timestamp']}`")
                st.markdown(f"**Från:** `{selected_msg['sender']}`")
                st.markdown(f"**Till:** `{selected_msg['recipient']}`")
                st.markdown(f"**Ämne:** **{selected_msg['subject']}**")
                st.divider()
                st.markdown(selected_msg["body"])

            analyze_btn = st.button("🔍 Utvärdera Meddelande mot Avtalsregler", type="primary", use_container_width=True)

        with analysis_col:
            if analyze_btn:
                if not st.session_state.get("api_key"):
                    st.error("Vänligen ange din API-nyckel i sidomenyn.")
                else:
                    with st.spinner(f"Analyserar dolda avtalsrisker via {st.session_state['provider']}..."):
                        try:
                            res = analyze_project_communication(
                                st.session_state["playbook"], 
                                selected_msg,
                                st.session_state["provider"],
                                st.session_state["api_key"]
                            )
                            st.session_state[f"analysis_{selected_msg['id']}"] = res
                        except Exception as e:
                            st.error(f"🛑 Ett fel uppstod under analysen:

{str(e)}")

            result = st.session_state.get(f"analysis_{selected_msg['id']}")
            
            if result:
                sev = result["severity"]
                if sev == "CRITICAL_PRECLUSION_RISK":
                    st.error(f"🚨 **KRITISK PREKLUSIONSRISK UPPTÄCKT** (Matchad Regel: `{result['matched_rule_id']}`)")
                elif sev == "PROCEDURAL_FLAW_WARNING":
                    st.warning(f"⚠️ **FORMKRAVSFEL / OGILTIG UNDERRÄTTELSE** (Matchad Regel: `{result['matched_rule_id']}`)")
                else:
                    st.success("✅ **INGEN AVTALSRISK UPPTÄCKT (SÄKERT)**")

                if result["is_trigger_detected"]:
                    m1, m2 = st.columns(2)
                    m1.metric("Sista dag för formell underrättelse", result["calculated_hard_deadline"])
                    m2.metric("Matchad Avtalsregel", result["matched_rule_id"])

                    with st.container(border=True):
                        st.markdown("**Juridisk & Kommersiell Analys:**")
                        st.write(result["legal_and_commercial_reasoning"])
