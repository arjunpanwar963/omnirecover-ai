import streamlit as st
import pandas as pd
import plotly.express as px
from backend.engine import OmniRecoverEngine

# --- RAZORPAY BRANDING CSS INJECTION ---
st.markdown("""
<style>
    /* Main Background */
    .stApp {
        background-color: #0A101D;
        color: #F0F2F5;
    }
    
    /* Sidebar Background */
    [data-testid="stSidebar"] {
        background-color: #161F33;
    }
    
    /* Primary Action Buttons (Razorpay Blue) */
    button[kind="primary"] {
        background-color: #2D68FE !important;
        border: none !important;
        color: white !important;
        border-radius: 6px !important;
        font-weight: 600 !important;
    }
    
    button[kind="primary"]:hover {
        background-color: #1A54EA !important;
    }
    
    /* Metric Cards Styling */
    div[data-testid="metric-container"] {
        background-color: #161F33;
        border: 1px solid #2B3754;
        border-radius: 8px;
        padding: 15px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    
    /* Metric Value Text Color */
    div[data-testid="stMetricValue"] {
        color: #2D68FE;
    }
    
    /* Tab Headers */
    .stTabs [data-baseweb="tab-list"] {
        background-color: transparent;
    }
    .stTabs [data-baseweb="tab"] {
        color: #8C9BB5;
    }
    .stTabs [aria-selected="true"] {
        color: #2D68FE !important;
        border-bottom-color: #2D68FE !important;
    }
    
    /* Headers */
    h1, h2, h3 {
        color: #FFFFFF !important;
    }
</style>
""", unsafe_allow_html=True)
# ---------------------------------------
st.set_page_config(page_title="OmniRecover AI Dashboard", layout="wide")

st.title("OmniRecover AI: Multi-Channel Autonomous Recovery Engine")
st.caption("Unified payment degradation recovery engine with zero-trust safety guardrails.")

engine = OmniRecoverEngine()

if st.button("Run Batch Diagnostic & Recovery Engine (50 Records)", type="primary"):
    with st.spinner("Processing batch records through agent pipeline..."):
        results = engine.run_batch_recovery()
        st.session_state['results'] = results

if 'results' in st.session_state:
    results = st.session_state['results']
    summary = results['summary']
    breakdown = results['category_breakdown']
    audit_trail = results['audit_trail']

    st.markdown("---")
    
    # 1. Key Metrics Row
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Revenue at Risk", f"₹{summary['total_risk_inr']:,.2f}")
    m2.metric("Total Revenue Recovered", f"₹{summary['total_recovered_inr']:,.2f}")
    m3.metric("Recovery Rate", f"{summary['recovery_rate_pct']}%")
    m4.metric("Escalated / Opt-Outs", f"{summary['escalated_opt_outs']} Records")

    st.markdown("---")

    # 2. Charts Row
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Revenue Recovery by Failure Category")
        df_cat = pd.DataFrame([
            {"Category": k.replace("_", " ").title(), "At Risk": v["at_risk"], "Recovered": v["recovered"]}
            for k, v in breakdown.items()
        ])
        fig = px.bar(df_cat, x="Category", y=["At Risk", "Recovered"], barmode="group",
                     labels={"value": "INR (₹)", "variable": "Metric"})
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.subheader("Agent Actions & Guardrails Applied")
        df_audit = pd.DataFrame(audit_trail)
        fig_status = px.pie(df_audit, names="status", title="Status Distribution", hole=0.4,
                            color_discrete_map={"RECOVERED": "#2ecc71", "ESCALATED_OPT_OUT": "#e74c3c"})
        st.plotly_chart(fig_status, use_container_width=True)

    # 3. Audit Log & Exceptions Table
    st.subheader("Immutable Decision Audit Trail")
    st.dataframe(df_audit, use_container_width=True)