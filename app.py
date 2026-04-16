

import os, re, tempfile, hashlib
import xml.etree.ElementTree as ET
from lxml import etree
import pandas as pd
import streamlit as st

# ---------------------- Page setup ----------------------
st.set_page_config(page_title="General Proofreader", page_icon="📝", layout="wide")


# ---------------------- Password gate ----------------------
def _hash(s: str) -> str:
    return "sha256:" + hashlib.sha256(s.encode("utf-8")).hexdigest()

def check_password():
    """Protects the app if APP_PASSWORD_HASH is set in secrets.toml.
       For local dev without secrets, access is allowed."""
    PW_HASH = st.secrets.get("APP_PASSWORD_HASH")
    if not PW_HASH:
        return True
    if "pw_ok" not in st.session_state:
        st.session_state["pw_ok"] = False

    def _submit():
        pw = st.session_state.get("pw_input", "")
        st.session_state["pw_ok"] = (_hash(pw) == PW_HASH)

    if not st.session_state["pw_ok"]:
        st.markdown("<div style='height:10vh'></div>", unsafe_allow_html=True)
        st.title("🔒 General Proofreader")

        st.caption("Enter the password to continue")
        st.text_input("Password", type="password", key="pw_input", on_change=_submit)
        if st.session_state.get("pw_input") and not st.session_state["pw_ok"]:
            st.error("Incorrect password. Try again.")
        st.stop()
    return True

check_password()

# ---------------------- Styling (professional dark / high contrast) ----------------------
st.markdown("""
<style>
:root{
  --bg1:#0b1220; --bg2:#0e1628; --card:#0f172a; --text:#e8edf5;
  --muted:#cbd5e1; --accent:#8b5cf6; --border:#2b3a55; --shadow:0 8px 28px rgba(0,0,0,.45);
}
.stApp{ background:linear-gradient(135deg,var(--bg1),var(--bg2)); }
.main .block-container{ max-width:1200px; }
h1,h2,h3,h4,h5,h6{ color:var(--text) !important; }
[data-testid="stMarkdownContainer"], .stMarkdown p, .stMarkdown span{ color:var(--text) !important; opacity:1 !important; }

.section{
  background:var(--card); color:var(--text) !important; border:1px solid var(--border);
  border-radius:16px; padding:18px 18px 10px; box-shadow:var(--shadow); margin-bottom:22px;
}
.stButton > button, .stDownloadButton > button{
  background:var(--accent) !important; color:#fff !important; border:none; border-radius:10px;
  padding:.6rem 1rem; box-shadow:var(--shadow);
}
.stButton > button:hover, .stDownloadButton > button:hover{ filter:brightness(1.08); }

/* st.dataframe grid */
div[data-testid="stDataFrame"]{
  background:var(--card) !important; color:var(--text) !important;
  border:1px solid var(--border) !important; border-radius:12px; box-shadow:var(--shadow);
}
div[data-testid="stDataFrame"] *{ color:var(--text) !important; }
div[data-testid="stDataFrame"] thead{ background:#0b1220 !important; }
div[data-testid="stDataFrame"] tbody tr:nth-child(odd){ background:#0e1729 !important; }
div[data-testid="stDataFrame"] tbody tr:nth-child(even){ background:#0c1524 !important; }
div[data-testid="stDataFrame"] [data-testid="stBaseButton-secondary"] svg,
div[data-testid="stDataFrame"] [data-testid="stElementToolbar"] svg{
  filter:invert(1) contrast(1.4) brightness(1.1);
}
/* wrap long cell text */
div[data-testid="stDataFrame"] .blank, div[data-testid="stDataFrame"] td, div[data-testid="stDataFrame"] span{
  white-space:pre-wrap !important; word-break:break-word !important;
}
</style>
""", unsafe_allow_html=True)

st.title("📝 General Proofreader")

st.caption("Sequence • Answer Mapping • Option Integrity")

# ---------------------- Your original logic (kept) ----------------------
def extract_numbered_elements(root, tag_name):
    numbers, texts = [], []
    for elem in root.iter():
        if etree.QName(elem.tag).localname == tag_name:
            text = (elem.text or "").strip()
            texts.append(text)
            match = re.match(r"(\d+)[\.\s\t\u200B]+", text)
            numbers.append(int(match.group(1)) if match else None)
    return texts, numbers

def extract_answer_keys(root):
    flat_numbers, texts = [], []
    for elem in root.iter():
        if etree.QName(elem.tag).localname == "Answer":
            text = (elem.text or "").strip()
            texts.append(text)
            matches = re.findall(r"(\d+)\.\s*\(([a-eA-E])\)", text)
            for q, _opt in matches:
                flat_numbers.append(int(q))
    return texts, flat_numbers

def detect_issues(numbers):
    issues = {"missing": [], "duplicates": [], "sequence_errors": []}
    valid = [n for n in numbers if isinstance(n, int)]
    if valid:
        expected = list(range(1, max(valid) + 1))
        issues["missing"] = sorted(set(expected) - set(valid))
    issues["duplicates"] = sorted({x for x in valid if valid.count(x) > 1})
    for i in range(len(valid) - 1):
        if valid[i + 1] != valid[i] + 1:
            issues["sequence_errors"].append((valid[i], valid[i + 1]))
    return issues

def extract_questions_with_options(xml_file_path):
    tree = ET.parse(xml_file_path)
    root = tree.getroot()
    questions_data, current_question, current_qno, current_options = [], None, None, []
    for elem in root.iter():
        if elem.tag == "Question":
            if current_question and current_options:
                questions_data.append((current_qno, current_question, list(current_options)))
            current_question = elem.text.strip() if elem.text else ""
            current_qno = current_question.split('.')[0].strip() if '.' in current_question else "?"
            current_options = []
        elif elem.tag == "Option-2":
            current_options.append(elem.text.strip() if elem.text else "")
    if current_question and current_options:
        questions_data.append((current_qno, current_question, current_options))
    return questions_data

def validate_options_to_rows(questions_data):
    rows = []
    for qno, _qtext, option_blocks in questions_data:
        full_option_text = " ".join(option_blocks).replace('\n', ' ').replace('\t', ' ')
        pattern = re.compile(r"\(([a-z])\)\s*(.*?)\s*(?=\([a-z]\)|$)")
        matches = pattern.findall(full_option_text)

        extracted = {}
        for label, content in matches:
            if label in ['a', 'b', 'c', 'd']:
                extracted[label] = content.strip()

        issues = []
        all_labels = re.findall(r"\(([a-z])\)", full_option_text)
        invalid_labels = [lbl for lbl in all_labels if lbl not in ['a', 'b', 'c', 'd']]
        if invalid_labels:
            issues.append(f"❌ Invalid option labels found: {', '.join(sorted(set(invalid_labels)))}")

        missing = [opt for opt in ['a', 'b', 'c', 'd'] if opt not in extracted]
        if missing:
            issues.append(f"❌ Missing options: {', '.join(missing)}")

        for label, content in extracted.items():
            if not content.strip():
                issues.append(f"❌ Option {label} is empty")

        seen_content = {}
        for label, content in extracted.items():
            if content in seen_content:
                other = seen_content[content]
                issues.append(f"❌ Duplicate content in options {other} and {label}: '{content}'")
            else:
                seen_content[content] = label

        if issues:
            rows.append({"Q#": qno, "Issues": " | ".join(issues)})
    return rows

def mismatches_rows_from_root(root):
    # answers
    answer_dict = {}
    for tag in root.findall(".//Answer"):
        text = tag.text or ""
        text = re.sub(r"[\s\u200B\u200E\u202F]+", " ", text.strip())
        for qno, ans in re.findall(r"(\d+)\.\s*\(?([a-dA-D])\)?", text):
            answer_dict[int(qno)] = ans.lower()
    # explanations
    explanation_dict = {}
    for tag in root.findall(".//Explanations"):
        text = tag.text or ""
        text = re.sub(r"[\s\u200B\u200E\u202F]+", " ", text.strip())
        m = re.match(r"(\d+)\.\s*\(?([a-dA-D])\)?", text)
        if m:
            qno, ans = m.groups()
            explanation_dict[int(qno)] = ans.lower()
    # compare
    mismatches = []
    for qno, exp_ans in explanation_dict.items():
        key_ans = answer_dict.get(qno)
        if not key_ans:
            mismatches.append({"Q#": qno, "Answer Key": "—", "Explanation": f"({exp_ans})", "Issue": "Answer key missing"})
        elif key_ans != exp_ans:
            mismatches.append({"Q#": qno, "Answer Key": f"({key_ans})", "Explanation": f"({exp_ans})", "Issue": "Answer ≠ Explanation"})
    return mismatches

# --------- helpers to build TABLES that keep your original messages ---------
def build_metrics_df(tag, numbers, issues):
    return pd.DataFrame([
        {"Metric": f"Total numbered {tag}s found", "Value": len([n for n in numbers if n is not None])},
        {"Metric": f"Missing {tag} count", "Value": len(issues["missing"])},
        {"Metric": f"Duplicate {tag} count", "Value": len(issues["duplicates"])},
        {"Metric": "Sequence breaks", "Value": len(issues["sequence_errors"])},
    ])

def build_messages_df(tag, numbers, issues):
    rows = []
    rows.append({"Message": f"📌 Validation for {tag}s"})
    rows.append({"Message": "---------------------------------------------"})
    rows.append({"Message": f"Total numbered {tag}s found: {len([n for n in numbers if n is not None])}"})
    if issues["missing"]:
        rows.append({"Message": f"❌ Missing {tag} numbers: {issues['missing']}"})
    if issues["duplicates"]:
        rows.append({"Message": f"⚠️ Duplicate {tag} numbers: {issues['duplicates']}"})
    for prev, curr in issues["sequence_errors"]:
        rows.append({"Message": f"🔍 After {tag} number {prev}, found {curr} — sequence is incorrect."})
    return pd.DataFrame(rows)

# ---------------------- Sidebar controls ----------------------
with st.sidebar:
    st.header("Upload XML")
    uploaded = st.file_uploader("Choose an XML file", type=["xml"])
    run = st.button("Run Validation", type="primary", use_container_width=True)

# ---------------------- Main flow ----------------------
if run and uploaded:
    with st.spinner("Parsing and validating..."):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xml") as tmp:
            tmp.write(uploaded.read())
            xml_path = tmp.name
        try:
            lxml_tree = etree.parse(xml_path)
            lxml_root = lxml_tree.getroot()

            # Part 1: sequences
            _, q_numbers = extract_numbered_elements(lxml_root, "Question")
            q_issues = detect_issues(q_numbers)

            _, e_numbers = extract_numbered_elements(lxml_root, "Explanations")
            e_issues = detect_issues(e_numbers)

            _, a_numbers = extract_answer_keys(lxml_root)
            a_issues = detect_issues(a_numbers)

            # ===== Questions =====
            st.markdown('<div class="section">', unsafe_allow_html=True)
            st.subheader("📌 Validation for Questions")
            st.dataframe(build_metrics_df("Question", q_numbers, q_issues), use_container_width=True, hide_index=True)
            st.dataframe(build_messages_df("Question", q_numbers, q_issues), use_container_width=True, hide_index=True)
            st.markdown('</div>', unsafe_allow_html=True)

            # ===== Explanations (header keeps your “Explanationss”) =====
            st.markdown('<div class="section">', unsafe_allow_html=True)
            st.subheader("📌 Validation for Explanationss")
            st.dataframe(build_metrics_df("Explanations", e_numbers, e_issues), use_container_width=True, hide_index=True)
            st.dataframe(build_messages_df("Explanations", e_numbers, e_issues), use_container_width=True, hide_index=True)
            st.markdown('</div>', unsafe_allow_html=True)

            # ===== Answers =====
            st.markdown('<div class="section">', unsafe_allow_html=True)
            st.subheader("📌 Validation for Answers")
            st.dataframe(build_metrics_df("Answer", a_numbers, a_issues), use_container_width=True, hide_index=True)
            st.dataframe(build_messages_df("Answer", a_numbers, a_issues), use_container_width=True, hide_index=True)
            st.markdown('</div>', unsafe_allow_html=True)

            # Part 2: Option Integrity — table
            questions_data = extract_questions_with_options(xml_path)
            option_rows = validate_options_to_rows(questions_data)
            st.markdown('<div class="section">', unsafe_allow_html=True)
            st.subheader("🧪 Validating Question Options")
            if option_rows:
                st.dataframe(pd.DataFrame(option_rows), use_container_width=True, hide_index=True)
            else:
                st.dataframe(pd.DataFrame([{"Status": "No option issues found."}]), use_container_width=True, hide_index=True)
            st.markdown('</div>', unsafe_allow_html=True)

            # Part 3: Answer ↔ Explanation Mismatches — table
            mismatch_rows = mismatches_rows_from_root(lxml_root)
            st.markdown('<div class="section">', unsafe_allow_html=True)
            st.subheader("================= ANSWER MISMATCH REPORT =================")
            if mismatch_rows:
                st.dataframe(pd.DataFrame(mismatch_rows).sort_values("Q#"), use_container_width=True, hide_index=True)
            else:
                st.dataframe(pd.DataFrame([{"Result": "✅ All answers match correctly."}]), use_container_width=True, hide_index=True)
            st.markdown('</div>', unsafe_allow_html=True)

            # Optional: Download as text (keeps original sentence format)
            report_lines = []
            def _messages_text(tag, numbers, issues):
                df = build_messages_df(tag, numbers, issues)
                return "\n".join(df["Message"].tolist())

            report_lines.append(_messages_text("Question", q_numbers, q_issues))
            report_lines.append(_messages_text("Explanations", e_numbers, e_issues))
            report_lines.append(_messages_text("Answer", a_numbers, a_issues))
            if option_rows:
                report_lines.append("🧪 Validating Question Options\n---------------------------------------------")
                report_lines.extend([f"Q{r['Q#']}: {r['Issues']}" for r in option_rows])
            if mismatch_rows:
                report_lines.append("\n================= ANSWER MISMATCH REPORT =================\n")
                report_lines.append("❌ Mismatched Questions:")
                report_lines.extend([
                    f"Q{r['Q#']}: {'❌ Answer key missing, Explanation = ' + r['Explanation'] if r['Answer Key']=='—' else f'❌ Answer key = {r['Answer Key']}, Explanation = {r['Explanation']}'}"
                    for r in mismatch_rows
                ])
            st.download_button(
                "⬇️ Download Full Report (.txt)",
                data="\n".join(report_lines).encode("utf-8"),
                file_name="general_proofreader_report.txt",
                mime="text/plain",
                use_container_width=True,
            )
        finally:
            try: os.remove(xml_path)
            except Exception: pass
else:
    st.info("Upload an XML file in the sidebar and click **Run Validation**.")
