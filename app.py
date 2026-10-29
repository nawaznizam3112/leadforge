import json
import os
import time
from datetime import datetime
from io import BytesIO

import pandas as pd
import streamlit as st

import ai
import db
import verify

st.set_page_config(page_title="LeadForge", page_icon="🎯", layout="wide")
db.init()

# ---------------- Access gate ----------------
def _password():
    pw = os.getenv("APP_PASSWORD", "")
    if pw:
        return pw
    try:
        return st.secrets.get("APP_PASSWORD", "")
    except Exception:
        return ""


PASSWORD = _password()
if PASSWORD:
    if st.session_state.get("authed") is not True:
        st.title("🎯 LeadForge")
        pw = st.text_input("Password", type="password")
        if st.button("Log in"):
            st.session_state.authed = pw == PASSWORD
            st.rerun()
        st.stop()

# ---------------- Sidebar ----------------
PACKAGES = {  # editable pricing guide (USD)
    "Sample (10 leads)": (10, 0),
    "Starter (100 leads)": (100, 499),
    "Growth (300 leads)": (300, 1199),
    "Scale (1,000 leads)": (1000, 3000),
    "Monthly refresh (200 leads/mo)": (200, 799),
}
with st.sidebar:
    st.title("🎯 LeadForge")
    api_key = st.text_input("Gemini API key", type="password", value=os.getenv("GEMINI_API_KEY", ""),
                            help="Free at aistudio.google.com/apikey")
    model = st.text_input("Model", value=ai.DEFAULT_MODEL)
    hourly = st.number_input("Your reviewer cost $/hour", 0.0, 200.0, 10.0)
    page = st.radio("Go to", ["Dashboard", "Clients & Orders", "Build List", "Review Queue",
                              "Deliver", "Sales Machine", "Compliance", "Sale Readiness"])


def need_key():
    if not api_key:
        st.error("Add your Gemini API key in the sidebar.")
        st.stop()


def suppressed_set():
    return {r["value"] for r in db.q("SELECT value FROM suppression")}


def order_picker(label="Order", statuses=None):
    sql = ("SELECT o.id, o.title, c.name AS client FROM orders o "
           "LEFT JOIN clients c ON c.id=o.client_id ORDER BY o.id DESC")
    orders = db.q(sql)
    if not orders:
        st.info("Create an order first (Clients & Orders).")
        st.stop()
    labels = {f"#{o['id']} · {o['client'] or '—'} · {o['title']}": o["id"] for o in orders}
    return labels[st.selectbox(label, list(labels))]


# ======================================================================
if page == "Dashboard":
    st.header("Dashboard")
    o = db.q("SELECT COUNT(*) n, COALESCE(SUM(CASE WHEN paid=1 THEN price_usd END),0) rev FROM orders")[0]
    l = db.q("SELECT COUNT(*) n, SUM(status IN ('verified','auto_verified')) ok, "
             "SUM(status='needs_review') rev FROM leads")[0]
    mrr = db.q("SELECT COALESCE(SUM(price_usd),0) m FROM orders WHERE plan='monthly' AND active=1 AND paid=1")[0]["m"]
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Orders", o["n"])
    c2.metric("Revenue (paid)", f"${o['rev']:,.0f}")
    c3.metric("MRR", f"${mrr:,.0f}")
    c4.metric("Leads sourced", l["n"] or 0)
    c5.metric("Awaiting review", l["rev"] or 0)
    st.subheader("Pipeline")
    rows = db.q("SELECT o.id, c.name client, o.title, o.status, o.target_count, o.price_usd, o.paid "
                "FROM orders o LEFT JOIN clients c ON c.id=o.client_id ORDER BY o.id DESC")
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.download_button("⬇️ Backup database", open(db.DB_PATH, "rb").read(),
                       f"leadforge_backup_{datetime.now():%Y%m%d}.db")
    st.caption("Streamlit Community Cloud storage is temporary. Use a host with a persistent disk "
               "(see README) and download backups regularly.")

# ======================================================================
elif page == "Clients & Orders":
    st.header("Clients & Orders")
    t1, t2, t3 = st.tabs(["New client", "New order", "All orders"])
    with t1:
        with st.form("client"):
            name = st.text_input("Contact name")
            company = st.text_input("Company")
            email = st.text_input("Email")
            if st.form_submit_button("Add client") and name:
                db.x("INSERT INTO clients(name,company,email) VALUES(?,?,?)", (name, company, email))
                st.success("Client added")
    with t2:
        clients = db.q("SELECT * FROM clients ORDER BY id DESC")
        if not clients:
            st.info("Add a client first.")
        else:
            cmap = {f"{c['name']} ({c['company'] or '—'})": c["id"] for c in clients}
            cid = cmap[st.selectbox("Client", list(cmap))]
            pkg = st.selectbox("Package", list(PACKAGES))
            count, price = PACKAGES[pkg]
            title = st.text_input("Order title", value=pkg)
            brief = st.text_area("Client's request in plain words",
                                 placeholder="e.g. Heads of IT at 50-500 employee maritime logistics "
                                             "companies in Europe using legacy ERP")
            c1, c2, c3 = st.columns(3)
            target = c1.number_input("Target leads", 1, 5000, count)
            price_in = c2.number_input("Price USD", 0.0, 100000.0, float(price))
            plan = c3.selectbox("Billing", ["one_time", "monthly"], index=1 if "Monthly" in pkg else 0)
            if st.button("Create order", type="primary") and brief:
                icp = {"brief": brief}
                if api_key:
                    try:
                        icp.update(ai.brief_to_icp(brief, api_key, model))
                    except Exception as e:
                        st.warning(f"Saved brief only (AI structuring failed: {e})")
                db.x("INSERT INTO orders(client_id,title,icp_json,target_count,price_usd,plan,status) "
                     "VALUES(?,?,?,?,?,?,?)", (cid, title, json.dumps(icp), target, price_in, plan, "draft"))
                st.success("Order created. Go to **Build List**.")
                st.json(icp)
    with t3:
        rows = db.q("SELECT o.id, c.name client, o.title, o.plan, o.status, o.price_usd, o.paid, o.active "
                    "FROM orders o LEFT JOIN clients c ON c.id=o.client_id ORDER BY o.id DESC")
        if rows:
            edited = st.data_editor(pd.DataFrame(rows), hide_index=True, use_container_width=True,
                                    disabled=["id", "client", "title", "plan", "status"], key="orders_ed")
            if st.button("Save paid/active flags"):
                for _, r in edited.iterrows():
                    db.x("UPDATE orders SET paid=?, active=?, price_usd=? WHERE id=?",
                         (int(r["paid"]), int(r["active"]), float(r["price_usd"]), int(r["id"])))
                st.success("Saved")

# ======================================================================
elif page == "Build List":
    st.header("Build List")
    oid = order_picker()
    order = db.q("SELECT * FROM orders WHERE id=?", (oid,))[0]
    icp = json.loads(order["icp_json"] or "{}")
    with st.expander("Ideal Customer Profile (editable JSON)", expanded=False):
        icp_txt = st.text_area("ICP", json.dumps(icp, indent=2), height=250)
    have = db.q("SELECT COUNT(*) n FROM leads WHERE order_id=?", (oid,))[0]["n"]
    st.write(f"**{have}/{order['target_count']}** leads sourced so far.")
    run_verify = st.checkbox("Auto-verify against source pages after sourcing", value=True)

    if st.button("🔍 Source leads with AI", type="primary"):
        need_key()
        try:
            icp = json.loads(icp_txt)
        except Exception:
            st.error("ICP JSON is invalid")
            st.stop()
        supp = suppressed_set()
        known = {r["domain"] for r in db.q("SELECT domain FROM leads WHERE order_id=?", (oid,))}
        bar, status_box = st.progress(0.0), st.empty()
        added, tries = 0, 0
        need = order["target_count"] - have
        while added < need and tries < 12:
            tries += 1
            status_box.info(f"Searching... batch {tries} · added {added}/{need}")
            try:
                batch = ai.discover_batch(icp, known, k=8, api_key=api_key, model=model)
            except Exception as e:
                status_box.warning(f"Batch failed ({e}); retrying...")
                time.sleep(5)
                continue
            for b in batch:
                dom = verify.domain_of(b.get("website", ""))
                email = (b.get("email") or "").lower()
                if not dom or dom in known or dom in supp or email in supp or not b.get("contact_name"):
                    continue
                known.add(dom)
                res = verify.check_lead(b) if run_verify else {
                    "confidence": 0, "status": "new", "flags": "", "notes": "", "email": email}
                db.x("INSERT INTO leads(order_id,company,website,domain,contact_name,title,email,country,"
                     "source_url,confidence,status,flags,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (oid, b.get("company"), b.get("website"), dom, b.get("contact_name"), b.get("title"),
                      res["email"], b.get("country"), b.get("source_url"), res["confidence"],
                      res["status"], res["flags"], res["notes"] or b.get("why_fit", "")))
                added += 1
                bar.progress(min(1.0, added / max(need, 1)))
                if added >= need:
                    break
            time.sleep(2)  # be gentle with free-tier rate limits
        db.x("UPDATE orders SET status='review' WHERE id=?", (oid,))
        status_box.success(f"Added {added} leads. Next: **Review Queue**.")

    leads = db.q("SELECT company, contact_name, title, email, confidence, status, flags FROM leads "
                 "WHERE order_id=? ORDER BY confidence DESC", (oid,))
    if leads:
        st.dataframe(pd.DataFrame(leads), use_container_width=True, hide_index=True)

# ======================================================================
elif page == "Review Queue":
    st.header("Human Review Queue")
    st.caption("This is your edge: a person confirms every lead before delivery. "
               "Open the source link, confirm the person/title/email, then set the status.")
    oid = order_picker()
    only_pending = st.checkbox("Only show needs_review / new", value=True)
    sql = "SELECT id, company, contact_name, title, email, source_url, confidence, flags, notes, status " \
          "FROM leads WHERE order_id=?"
    if only_pending:
        sql += " AND status IN ('needs_review','new','auto_verified')"
    leads = db.q(sql + " ORDER BY confidence DESC", (oid,))
    if not leads:
        st.success("Nothing to review.")
    else:
        df = pd.DataFrame(leads)
        edited = st.data_editor(
            df, hide_index=True, use_container_width=True, height=520,
            disabled=["id", "company", "confidence", "flags", "source_url"],
            column_config={
                "status": st.column_config.SelectboxColumn(
                    options=["new", "needs_review", "auto_verified", "verified", "rejected"]),
                "source_url": st.column_config.LinkColumn("source"),
            }, key=f"review_{oid}")
        minutes = st.number_input("Minutes spent on this review session (for margin tracking)", 0.0, 600.0, 0.0)
        if st.button("💾 Save review", type="primary"):
            for _, r in edited.iterrows():
                if verify.valid_syntax(r["email"]) or not r["email"]:
                    db.x("UPDATE leads SET contact_name=?, title=?, email=?, notes=?, status=? WHERE id=?",
                         (r["contact_name"], r["title"], (r["email"] or "").lower(), r["notes"],
                          r["status"], int(r["id"])))
            db.x("UPDATE orders SET review_minutes=review_minutes+? WHERE id=?", (minutes, oid))
            st.success("Saved")
        if st.button("✅ Approve all auto_verified"):
            db.x("UPDATE leads SET status='verified' WHERE order_id=? AND status='auto_verified'", (oid,))
            st.rerun()

# ======================================================================
elif page == "Deliver":
    st.header("Deliver")
    oid = order_picker()
    order = db.q("SELECT o.*, c.name client FROM orders o LEFT JOIN clients c ON c.id=o.client_id "
                 "WHERE o.id=?", (oid,))[0]
    supp = suppressed_set()
    leads = [l for l in db.q("SELECT * FROM leads WHERE order_id=? AND status='verified'", (oid,))
             if (l["email"] or "") not in supp and l["domain"] not in supp]
    allrev = db.q("SELECT status, COUNT(*) n FROM leads WHERE order_id=? GROUP BY status", (oid,))
    st.write({r["status"]: r["n"] for r in allrev})
    st.metric("Deliverable (verified, not suppressed)", f"{len(leads)} / {order['target_count']}")
    if leads:
        cols = ["company", "website", "contact_name", "title", "email", "country", "source_url", "confidence"]
        df = pd.DataFrame(leads)[cols]
        total_rev = sum(r["n"] for r in allrev if r["status"] in ("verified", "rejected"))
        rejected = next((r["n"] for r in allrev if r["status"] == "rejected"), 0)
        report = pd.DataFrame({
            "Metric": ["Leads delivered", "Reviewed by a human", "Rejected during QA", "Avg confidence",
                       "Delivery date", "Replacement guarantee"],
            "Value": [len(df), total_rev, rejected, round(df["confidence"].mean(), 1),
                      f"{datetime.now():%Y-%m-%d}", "Bad contact replaced free within 14 days"]})
        buf = BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            df.to_excel(w, sheet_name="Leads", index=False)
            report.to_excel(w, sheet_name="Verification report", index=False)
        st.download_button("⬇️ Download XLSX (with report)", buf.getvalue(),
                           f"leads_order_{oid}.xlsx")
        st.download_button("⬇️ Download CSV", df.to_csv(index=False), f"leads_order_{oid}.csv")
        extra = st.number_input("Extra direct costs for this order (API, tools) $", 0.0, 10000.0,
                                float(order["cost_usd"]))
        if st.button("Mark order delivered"):
            db.x("UPDATE orders SET status='delivered', delivered_at=datetime('now'), cost_usd=? WHERE id=?",
                 (extra, oid))
            st.success("Delivered. Remember to send the privacy notice + opt-out contact (see Compliance).")
        margin = order["price_usd"] - extra - order["review_minutes"] / 60 * hourly
        st.metric("Order gross margin", f"${margin:,.0f}",
                  f"{(margin / order['price_usd'] * 100) if order['price_usd'] else 0:.0f}%")
        st.dataframe(df, use_container_width=True, hide_index=True)

# ======================================================================
elif page == "Sales Machine":
    st.header("Sales Machine — get your first 10 clients")
    focus = st.text_input("Your focus niche (specialize to win)",
                          placeholder="e.g. lead lists for B2B SaaS companies selling to healthcare IT")
    if st.button("Generate landing page, emails, DMs, objection handlers", type="primary"):
        need_key()
        with st.spinner("Writing..."):
            st.session_state.sales = ai.sales_assets(focus or "niche B2B markets", api_key, model)
    if st.session_state.get("sales"):
        st.markdown(st.session_state.sales)
        st.download_button("⬇️ Download (Markdown)", st.session_state.sales, "sales_assets.md")
    st.subheader("Pricing guide")
    st.table(pd.DataFrame([{"Package": k, "Leads": v[0], "Price $": v[1],
                            "$/lead": round(v[1] / v[0], 2) if v[1] else 0} for k, v in PACKAGES.items()]))
    st.markdown("""**Playbook:** offer a free 10-lead sample (create a Sample order) → show the source URL for every
contact → upsell Starter → convert to **Monthly refresh** (recurring revenue is what buyers pay a premium for).""")

# ======================================================================
elif page == "Compliance":
    st.header("Compliance & Suppression")
    st.warning("Not legal advice. Have a lawyer review your Terms, Privacy Policy and DPA before launch.")
    st.markdown("""
**Built-in safeguards**
- Business contact data only, taken from public company pages. **No LinkedIn scraping, no private/personal emails.**
- Every lead stores its **source URL** (provable origin).
- **Suppression list** blocks opted-out people/domains from every future order and delivery.
- Humans confirm each lead; AI never invents contacts (names must appear on the source page).

**Your checklist**
1. Publish a Privacy Policy + opt-out contact; honour removal requests within 30 days (add them below).
2. EU/UK: rely on *legitimate interest* for B2B, keep a documented assessment; avoid sole traders/personal emails.
3. Canada (CASL) and Germany are strict on cold email; Tell clients to include sender ID + unsubscribe (CAN-SPAM).
4. Sign a Data Processing Agreement with clients; don't resell the same list to competitors without disclosure.
5. India (DPDP Act), California (CCPA): keep a deletion process.
""")
    new = st.text_area("Add to suppression list (emails or domains, one per line)")
    if st.button("Add") and new.strip():
        for v in new.splitlines():
            if v.strip():
                try:
                    db.x("INSERT INTO suppression(value,reason) VALUES(?,?)", (v.strip().lower(), "opt-out"))
                except Exception:
                    pass
        st.success("Added")
    st.dataframe(pd.DataFrame(db.q("SELECT value, reason, created FROM suppression ORDER BY id DESC")),
                 use_container_width=True, hide_index=True)

# ======================================================================
elif page == "Sale Readiness":
    st.header("Sale Readiness — what buyers will ask for")
    rev = db.q("SELECT COALESCE(SUM(price_usd),0) r, COALESCE(SUM(cost_usd),0) c, "
               "COALESCE(SUM(review_minutes),0) m FROM orders WHERE paid=1")[0]
    labor = rev["m"] / 60 * hourly
    profit = rev["r"] - rev["c"] - labor
    mrr = db.q("SELECT COALESCE(SUM(price_usd),0) m FROM orders WHERE plan='monthly' AND active=1 AND paid=1")[0]["m"]
    rec_share = (mrr * 12 / rev["r"] * 100) if rev["r"] else 0
    cl = db.q("SELECT c.id, SUM(o.price_usd) r, COUNT(o.id) n FROM clients c JOIN orders o ON o.client_id=c.id "
              "WHERE o.paid=1 GROUP BY c.id")
    n_clients = len(cl)
    repeat = sum(1 for c in cl if c["n"] > 1) / n_clients * 100 if n_clients else 0
    top = max((c["r"] for c in cl), default=0) / rev["r"] * 100 if rev["r"] else 0
    qa = db.q("SELECT SUM(status='verified') v, SUM(status='rejected') r FROM leads")[0]
    acc = (qa["v"] or 0) / ((qa["v"] or 0) + (qa["r"] or 0)) * 100 if (qa["v"] or 0) + (qa["r"] or 0) else 0
    tat = db.q("SELECT AVG(julianday(delivered_at)-julianday(created)) d FROM orders WHERE delivered_at IS NOT NULL")[0]["d"]

    a, b, c, d = st.columns(4)
    a.metric("Revenue (paid)", f"${rev['r']:,.0f}")
    b.metric("Net profit (est.)", f"${profit:,.0f}")
    c.metric("MRR / ARR", f"${mrr:,.0f} / ${mrr * 12:,.0f}")
    d.metric("Clients", n_clients)
    e, f, g, h = st.columns(4)
    e.metric("Recurring share", f"{rec_share:.0f}%")
    f.metric("Repeat clients", f"{repeat:.0f}%")
    g.metric("Top-client concentration", f"{top:.0f}%")
    h.metric("QA pass rate", f"{acc:.0f}%")
    st.metric("Avg turnaround (days)", f"{tat:.1f}" if tat else "—")

    st.subheader("Rough valuation guide")
    st.write(f"Small service/data businesses commonly sell for ~2–3.5× annual profit. If you ran at today's pace "
             f"for a year, profit ≈ **${profit * 12:,.0f}** → indicative range "
             f"**${profit * 12 * 2:,.0f} – ${profit * 12 * 3.5:,.0f}**. "
             f"(Based on lifetime figures annualised crudely; real valuations depend on trailing 12 months, "
             f"recurring revenue, concentration and documentation.)")
    st.markdown("""**To raise the multiple:** push recurring share above 50%, no client above 25% of revenue,
documented SOPs (see `docs/SOP.md`), a trained reviewer who isn't you, QA pass rate >95%,
and 12+ months of clean records. List on Acquire.com / Flippa / Empire Flippers when ready.""")
    summary = (f"# LeadForge data-room summary ({datetime.now():%Y-%m-%d})\n\n"
               f"- Revenue: ${rev['r']:,.0f}\n- Net profit est.: ${profit:,.0f}\n- MRR: ${mrr:,.0f}\n"
               f"- Clients: {n_clients} | Repeat: {repeat:.0f}% | Top client share: {top:.0f}%\n"
               f"- QA pass rate: {acc:.0f}% | Avg turnaround: {tat or 0:.1f} days\n")
    st.download_button("⬇️ Data-room summary", summary, "data_room_summary.md")
