import os
import re
import json
from datetime import datetime, timedelta
import pandas as pd
import streamlit as st

# Importera scheman och funktioner från vår backend-fil (notice_tracker.py)
# Detta är hjärnan i systemet där AI:n kopplas in och reglerna definieras.
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
    /* Styling för att markera exakta textcitat från bevisningen */
    .highlight-quote {
        background-color: #ffeeba;
        padding: 2px 6px;
        border-radius: 4px;
        border-left: 4px solid #d39e00;
        font-weight: 600;
        color: #212529;
    }
    /* Röd varningstag för regler som ändrats i AF-delen */
    .override-badge {
        background-color: #f8d7da;
        color: #721c24;
        padding: 3px 8px;
        border-radius: 12px;
        font-size: 0.8em;
        font-weight: 600;
    }
    /* Grön tag för regler där standardavtalet gäller */
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
# (Detta är texten som fylls i automatiskt i textrutorna på första sidan)
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

# Fiktiva e-postmeddelanden som vi kan testa systemet med
MOCK_INBOX = [
    {
        "id": "MSG-101",
        "label": "🔴 [Fälla 1: Fel mottagare] Oförutsedd betongkulvert",
        "timestamp": "2026-10-27",
        "sender": "Johan Berg (Platschef, Entreprenören AB)",
        "recipient": "Erik Svensson (Byggledare, Fastighetsbolaget)",
        "channel": "E-post",
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
        "label": "🟠 [Fälla 2: Passivitet / Lojalitetsrisk] Byggmötesprotokoll #14",
        "timestamp": "2026-10-27",
        "sender": "Erik Svensson (Byggledare, Fastighetsbolaget)",
        "recipient": "Johan Berg (Platschef, Entreprenören AB)",
        "channel": "Distribuerat Byggmötesprotokoll",
        "subject": "Protokoll Byggmöte #14 - Kvarteret Kronan",
        "body": (
            "Punkt 14.3 Ventilation: Noterades att fläktrummet i källaren måste flyttas 2 meter "
            "söderut p.g.a. ändrad takhöjd. Parterna är överens om att Entreprenören utför denna "
            "omdragning av kanaler inom ramen för befintlig kontraktssumma utan rätt till tidsförlängning."
        ),
    },
    {
        "id": "MSG-103",
        "label": "🟡 [Dold risk för försening] Försenade fasadritningar",
        "timestamp": "2026-10-27",
        "sender": "Sara Nordin (Arbetsledare, Entreprenören AB)",
        "recipient": "Anna Lindqvist (Beställarens Ombud)",
        "channel": "E-post",
        "subject": "Angående detaljritningar för fasadinfästning",
        "body": (
            "Hej Anna, vi väntar fortfarande på de reviderade konstruktionsritningarna för "
            "fasadinfästningen på plan 4 som skulle kommit i fredags. Våra montörer står "
            "snart utan arbete på den etappen om vi inte får underlaget senast imorgon."
        ),
    },
    {
        "id": "MSG-104",
        "label": "🟢 [Ingen risk / Säkert] Samordning av kranleverans",
        "timestamp": "2026-10-27",
        "sender": "Johan Berg (Platschef, Entreprenören AB)",
        "recipient": "Erik Svensson (Byggledare, Fastighetsbolaget)",
        "channel": "E-post",
        "subject": "Leverans av mobilkran torsdag morgon",
        "body": (
            "Hej Erik, ville bara bekräfta att mobilkranen anländer kl 06:30 på torsdag "
            "enligt ordinarie tidplan. Grind B hålls öppen. Ingen påverkan på övriga moment eller budget."
        ),
    }
]

# =====================================================================
# SIDOMENY: INSTÄLLNINGAR & ARKITEKTURINFO
# =====================================================================
with st.sidebar:
    st.title("⚙️ Inställningar (API-nyckel)")
    st.markdown("Välj din föredragna AI-leverantör och ange din API-nyckel för att köra motorn. Nyckeln sparas endast säkert under denna session.")
    
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

    st.divider()
    st.subheader("🏗️ Systemarkitektur (Hur det fungerar)")
    st.caption("""
    **Nod 1 (Kompilatorn):** Hanterar *tolkningsföreträde* mellan standardavtal (t.ex. AB 04) och särskilda kontraktsvillkor (AF-del). Sammanställer detta till en bindande och strukturerad regelbok (JSON).
    
    **Nod 2 (Analys & Bevis):** Skannar löpande projektkommunikation efter dolda avtalsrisker. Säkerställer bevisvärde genom att extrahera exakta citat från texten.
    
    **Nod 3 (Formkrav & Tidsfrister):** Kontrollerar mottagarens behörighet samt beräknar via traditionell kod (ej AI) sista datum för preklusion/förlorad rätt.
    """)

# =====================================================================
# HUVUDRUBRIK
# =====================================================================
st.title("⚖️ ClauseWatch: Automatisk Avtalsbevakning")
st.caption("*Av Alfred Stengard*")
st.markdown(
    "**Överbryggar klyftan mellan statiska avtalsvillkor och den dagliga projektkommunikationen.**"
)

# Skapa två flikar för användaren
tab1, tab2 = st.tabs([
    "📜 Steg 1: Kompilera Avtalsregler (Nod 1)", 
    "📬 Steg 2: Övervaka Projektets Inkorg (Nod 2 & 3)"
])

# =====================================================================
# FLIK 1: NOD 1 (KOMPILERA AVTALET)
# =====================================================================
with tab1:
    st.subheader("Kompilera avtalsregler och hantera tolkningsföreträde")
    st.markdown(
        "Mata in standardavtalet (t.ex. **AB 04**) tillsammans med de projektspecifika ändringarna (**Kontraktsvillkor / AF-del**). "
        "Systemet tillämpar *tolkningsföreträde* automatiskt och skapar en strukturerad och bindande regelbok."
    )

    # Visa två textrutor jämte varandra
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

    # Knappen som startar processen i Node 1
    if st.button("🚀 Kompilera Avtalsregler", type="primary"):
        if not st.session_state.get("api_key"):
            st.error("Vänligen ange din API-nyckel i sidomenyn till vänster för att köra analysen.")
        else:
            with st.spinner(f"Analyserar och sammanställer regler via {st.session_state['provider']}..."):
                # Här anropar vi AI-motorn från notice_tracker.py
                playbook = compile_contract_playbook(
                    base_text, 
                    custom_text,
                    st.session_state["provider"],
                    st.session_state["api_key"]
                )
                # Spara resultatet i sessionen så vi minns det på nästa flik
                st.session_state["playbook"] = playbook
                st.success(f"Lyckades! Kompilerade {len(playbook.compiled_rules)} bindande regler för {playbook.project_name}.")

    # Om vi har kompilerat regler, visa dem på skärmen
    if "playbook" in st.session_state:
        pb: ContractPlaybook = st.session_state["playbook"]
        st.divider()
        st.markdown(f"### 📋 Aktiva Avtalsregler: `{pb.project_name}`")

        for rule in pb.compiled_rules:
            # Sätt en röd eller grön bricka beroende på om regeln blivit ändrad i AF-delen
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
                if rule.override_clause_reference:
                    st.caption(f"Ändrad av: {rule.override_clause_reference} | Konsekvens/Risk: {rule.consequence_of_non_compliance}")

# =====================================================================
# FLIK 2: NOD 2 & 3 (ÖVERVAKA INKORGEN LIVE)
# =====================================================================
with tab2:
    if "playbook" not in st.session_state:
        st.warning("⚠️ Vänligen kompilera avtalsreglerna i **Steg 1** först, så att systemet har ett regelverk att utvärdera meddelandena mot.")
    else:
        st.subheader("Övervakning av Inkommande Projektkommunikation")
        
        inbox_col, analysis_col = st.columns([1, 1.3], gap="large")

        with inbox_col:
            st.markdown("#### 📥 Välj Inkommande Meddelande")
            selected_label = st.radio(
                "Projektflöde (Demo):",
                options=[m["label"] for m in MOCK_INBOX],
                index=0
            )
            selected_msg = next(m for m in MOCK_INBOX if m["label"] == selected_label)

            st.markdown("#### 📄 Meddelande & Innehåll")
            with st.container(border=True):
                st.markdown(f"**Datum/Tid:** `{selected_msg['timestamp']}`")
                st.markdown(f"**Från:** `{selected_msg['sender']}`")
                st.markdown(f"**Till:** `{selected_msg['recipient']}`")
                st.markdown(f"**Kanal:** `{selected_msg['channel']}`")
                st.markdown(f"**Ämne:** **{selected_msg['subject']}**")
                st.divider()
                
                # Om vi redan har analyserat detta meddelande och hittat ett specifikt textcitat, markera det med gult i brödtexten!
                body_display = selected_msg["body"]
                current_analysis = st.session_state.get(f"analysis_{selected_msg['id']}")
                
                if current_analysis and current_analysis.get("verbatim_evidence_quote"):
                    quote = current_analysis["verbatim_evidence_quote"]
                    if quote in body_display:
                        body_display = body_display.replace(
                            quote, f'<span class="highlight-quote">{quote}</span>'
                        )
                st.markdown(body_display, unsafe_allow_html=True)

            analyze_btn = st.button("🔍 Utvärdera Meddelande mot Avtalsregler", type="primary", use_container_width=True)

        with analysis_col:
            st.markdown("#### 🧠 Juridisk & Operativ Riskanalys")
            
            # Starta bedömningen om användaren klickar på knappen
            if analyze_btn:
                if not st.session_state.get("api_key"):
                    st.error("Vänligen ange din API-nyckel i sidomenyn.")
                else:
                    with st.spinner(f"Analyserar dolda avtalsrisker via {st.session_state['provider']}..."):
                        # Kör analysen från notice_tracker.py
                        res = analyze_project_communication(
                            st.session_state["playbook"], 
                            selected_msg,
                            st.session_state["provider"],
                            st.session_state["api_key"]
                        )
                        # Gör en extra formell kontroll för att garantera att citatet från AI:n verkligen finns ord-för-ord i e-postmeddelandet (Zero Hallucination Check)
                        quote = res.get("verbatim_evidence_quote")
                        res["grounding_verified"] = bool(quote and quote in selected_msg["body"])
                        
                        # Spara resultatet
                        st.session_state[f"analysis_{selected_msg['id']}"] = res

            result = st.session_state.get(f"analysis_{selected_msg['id']}")
            
            if not result:
                st.info("Klicka på **Utvärdera Meddelande mot Avtalsregler** till vänster för att granska detta meddelande.")
            else:
                # 1. Visa färgkodad varningsbanner baserat på allvarlighetsgrad
                sev = result["severity"]
                if sev == "CRITICAL_PRECLUSION_RISK":
                    st.error(f"🚨 **KRITISK PREKLUSIONSRISK UPPTÄCKT** (Matchad Regel: `{result['matched_rule_id']}`)")
                elif sev == "PROCEDURAL_FLAW_WARNING":
                    st.warning(f"⚠️ **FORMKRAVSFEL / OGILTIG UNDERRÄTTELSE** (Matchad Regel: `{result['matched_rule_id']}`)")
                elif sev == "LOW_MONITOR":
                    st.info(f"ℹ️ **LÅG RISK / BEVAKA** (Matchad Regel: `{result['matched_rule_id']}`)")
                else:
                    st.success("✅ **INGEN AVTALSRISK UPPTÄCKT (SÄKERT)**")

                # 2. Nyckeltal (Datum + Beviskontroll)
                if result["is_trigger_detected"]:
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Sista dag för formell underrättelse", result["calculated_hard_deadline"], f"{result['recommended_days_to_act']} dagars frist")
                    m2.metric("Matchad Avtalsregel", result["matched_rule_id"])
                    m3.metric(
                        "Bevis för textcitat", 
                        "100% Verifierad" if result["grounding_verified"] else "Misslyckades",
                        "Citatkontroll genomförd"
                    )

                    # 3. Varning gällande fel mottagare / behörighet (om tillämpligt)
                    if result.get("procedural_defect_spotted"):
                        st.warning(f"**Varning gällande formkrav/behörighet:** {result['procedural_defect_spotted']}")

                    # 4. Detaljerad Juridisk bedömning
                    with st.container(border=True):
                        st.markdown("**Juridisk & Kommersiell Analys:**")
                        st.write(result["legal_and_commercial_reasoning"])
                        st.caption(f'**Extraherat textcitat (Bevis):** *"{result["verbatim_evidence_quote"]}"*')

                    # 5. Färdigt utkast på svarsmejl/formell notis
                    if result.get("draft_formal_notice"):
                        st.markdown("#### ✉️ Automatiskt utkast för formell underrättelse (Redo att skickas)")
                        st.code(result["draft_formal_notice"], language="markdown")
                else:
                    st.write(result["legal_and_commercial_reasoning"])
