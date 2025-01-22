import streamlit as st
import pandas as pd
import os
import glob
import logging

# =========================
# 1. CONFIG & LOGGING SETUP
# =========================

st.set_page_config(page_title="CU Lookup Tool", layout="wide")

# Directory where your CSVs live; update if needed
DATA_DIR = "data"

# Attempt to find each CSV via glob
listings_file = glob.glob(os.path.join(DATA_DIR, "*Yurika*Listings*7-11-2024.csv"))
breakdowns_file = glob.glob(os.path.join(DATA_DIR, "*Yurika*Breakdowns*7-11-2024.csv"))
sc_desc_file = glob.glob(os.path.join(DATA_DIR, "*scdesc*7-11-2024.csv"))
backup_desc_file = glob.glob(os.path.join(DATA_DIR, "*Backup*Descriptions*.csv"))

# Check that all files are found
if not (listings_file and breakdowns_file and sc_desc_file and backup_desc_file):
    st.error("One or more CSV files are missing in the 'data/' folder.")
    st.stop()

# Pick the first matching file from each list
listings_path = listings_file[0]
breakdowns_path = breakdowns_file[0]
sc_desc_path = sc_desc_file[0]
backup_desc_path = backup_desc_file[0]

# Basic logging config
logging.basicConfig(
    filename="cu_sc_tool.log",
    level=logging.INFO,
    format="%(asctime)s - %(message)s"
)

def log_action(msg):
    logging.info(msg)

# ==============================
# 2. LOAD & PREPARE THE DATA
# ==============================
@st.cache_data
def load_data():
    """Loads the four CSVs and applies the same cleaning you had in Tkinter code."""
    listings = pd.read_csv(listings_path, encoding="utf-8")
    breakdowns = pd.read_csv(breakdowns_path, encoding="utf-8")
    sc_desc = pd.read_csv(sc_desc_path, encoding="utf-8")
    backup_desc = pd.read_csv(backup_desc_path, encoding="utf-8")
    
    # Remove extraneous "Unnamed:" columns from listings
    listings = listings.loc[:, ~listings.columns.str.contains("Unnamed:")]

    # Remove leading zeros from STOCK CODE
    breakdowns["STOCK CODE"] = breakdowns["STOCK CODE"].apply(
        lambda x: str(x).lstrip("0") if pd.notnull(x) else x
    )
    sc_desc["Stock Code1"] = sc_desc["Stock Code1"].apply(
        lambda x: str(x).lstrip("0") if pd.notnull(x) else x
    )

    # Remove "SC000" prefix from CU numbers in breakdowns
    def remove_sc000_prefix(val):
        if isinstance(val, str) and val.lower().startswith("sc000"):
            return val[5:]
        return val

    breakdowns["CU"] = breakdowns["CU"].apply(remove_sc000_prefix)
    breakdowns["CHILD CU"] = breakdowns["CHILD CU"].apply(remove_sc000_prefix)

    return listings, breakdowns, sc_desc, backup_desc

listings, breakdowns, sc_desc, backup_desc = load_data()

# =========================
# 3. HELPER FUNCTIONS
# =========================

def recursive_breakdown(cu):
    """
    Recursively gather STOCK CODE rows for a given CU from 'breakdowns'.
    Returns a dataframe with columns: [CU, CHILD CU, STOCK CODE, QTY, ...].
    """
    cu_str = str(cu)
    # If CU not present, return empty
    if cu_str not in breakdowns["CU"].values:
        return pd.DataFrame(columns=breakdowns.columns)

    subset = breakdowns[breakdowns["CU"] == cu_str]
    result = pd.DataFrame(columns=breakdowns.columns)

    for _, row in subset.iterrows():
        child_cu = row["CHILD CU"]
        stock_code = row["STOCK CODE"]

        # If row has a CHILD CU but no STOCK CODE, we break it down further
        if pd.isna(stock_code) and pd.notna(child_cu):
            deeper = recursive_breakdown(child_cu)
            result = pd.concat([result, deeper], ignore_index=True)
        # If we have a valid stock code, add this row to results
        elif pd.notna(stock_code):
            result = pd.concat([result, pd.DataFrame([row])], ignore_index=True)

    return result

def get_sc_description(sc_id):
    """
    Return the SC's description, UOI, and Price from sc_desc or fallback to backup_desc.
    If found in sc_desc, we prefer sc_desc. Otherwise, we try backup_desc for a description.
    Returns a dict with keys: {'Description': ..., 'UOI': ..., 'Price': ...}.
    """
    sc_str = str(sc_id)

    # Try main sc_desc
    main_info = sc_desc[sc_desc["Stock Code1"].astype(str) == sc_str]
    if not main_info.empty:
        return {
            "Description": main_info.iloc[0]["Description"],
            "UOI": main_info.iloc[0].get("UOI", ""),
            "Price": main_info.iloc[0].get("Price", "")
        }

    # Fallback to backup_desc
    backup_info = backup_desc[backup_desc["SC_backup"].astype(str) == sc_str]
    if not backup_info.empty:
        return {
            "Description": backup_info.iloc[0]["backupDescrip"],
            "UOI": "",
            "Price": ""
        }

    # Nothing found
    return {
        "Description": "No Description Found",
        "UOI": "",
        "Price": ""
    }

def get_cu_legend_info(cu):
    """
    Return all rows in 'listings' that match the given CU in 'Description 2'.
    (Adjust if your 'listings' is structured differently.)
    """
    return listings[listings["Description 2"].astype(str) == str(cu)]

# =========================
# 4. STREAMLIT UI
# =========================

st.title("CU Lookup Tool (Streamlit)")
st.write("""
1. **Search** in the listings for a CU or any relevant text.  
2. **Select** one row from the search results to see its CU info.  
3. **View** the CU legend (from listings) and the SC breakdown (with Price, UOI, QTY, etc.).  
4. Optionally, **download** the breakdown as CSV.  
""")

# ---- A) SEARCH UI ----
search_query = st.text_input("Search listings (case-insensitive):")
if st.button("Search"):
    log_action(f"User searched for: {search_query}")
    # Filter across all columns in listings
    results = listings[listings.apply(
        lambda row: row.astype(str).str.contains(search_query, case=False).any(),
        axis=1
    )]
    st.session_state["search_results"] = results
elif "search_results" not in st.session_state:
    st.session_state["search_results"] = pd.DataFrame()

# Show search results
if st.session_state["search_results"].empty:
    st.info("No search results. Enter a query and press Search.")
else:
    st.write("### Search Results")
    st.dataframe(st.session_state["search_results"], use_container_width=True)

    # Let user pick which row index to explore
    indices = st.session_state["search_results"].index.tolist()
    selected_index = st.selectbox("Select a row index for CU breakdown:", options=indices)

    if st.button("Show Details for Selected Row"):
        row_data = st.session_state["search_results"].loc[selected_index]

        # Identify the CU from your 'listings' row
        # Often 'Description 2' is your actual CU code. Adjust if needed.
        cu_id = row_data.get("Description 2", None)
        if pd.isna(cu_id):
            # fallback: maybe the first column is the CU
            cu_id = row_data.iloc[0]
        
        st.write(f"**Selected CU:** {cu_id}")

        # 1) Show CU Legend
        legend_df = get_cu_legend_info(cu_id)
        if legend_df.empty:
            st.warning("No CU legend found in listings for this CU.")
        else:
            st.write("### CU Legend (from `listings`)")
            st.dataframe(legend_df, use_container_width=True)

        # 2) Do the SC breakdown via recursion
        breakdown_df = recursive_breakdown(cu_id)
        if breakdown_df.empty:
            st.warning("No SC breakdown data found for this CU.")
        else:
            st.write("### SC Breakdown Details")

            # We'll create new columns for SC's "Description", "UOI", "Price"
            breakdown_df = breakdown_df.copy()  # avoid SettingWithCopy
            desc_list = []
            uoi_list = []
            price_list = []

            for _, b_row in breakdown_df.iterrows():
                sc_id = b_row["STOCK CODE"]
                # Use your helper function
                details = get_sc_description(sc_id)
                desc_list.append(details["Description"])
                uoi_list.append(details["UOI"])
                price_list.append(details["Price"])

            breakdown_df["SC Description"] = desc_list
            breakdown_df["UOI"] = uoi_list
            breakdown_df["Price"] = price_list

            # Show final table with relevant columns
            # You can reorder columns as you wish
            final_cols = [
                "CU",
                "CHILD CU",
                "STOCK CODE",
                "QTY",
                "SC Description",
                "UOI",
                "Price"
            ]
            # Some might not exist in the CSV if you named them differently, so check
            final_cols = [c for c in final_cols if c in breakdown_df.columns]
            breakdown_df = breakdown_df[final_cols]

            st.dataframe(breakdown_df, use_container_width=True)

            # 3) Optional: Download breakdown as CSV
            csv_bytes = breakdown_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="Download Breakdown as CSV",
                data=csv_bytes,
                file_name=f"CU_{cu_id}_breakdown.csv",
                mime="text/csv"
            )

# ---- HELP EXPANDER ----
with st.expander("Help / Instructions"):
    st.write("""
    **Steps to Use This Tool**  
    1. Type any text into the search box (top) and click **Search**.  
       - The app searches all columns of the `listings` CSV for partial matches (case-insensitive).  
    2. Choose a specific row from the search results (via the dropdown).  
    3. Click **Show Details for Selected Row**.  
       - The tool shows the "CU Legend" info from `listings` (all rows where `Description 2` equals your chosen CU).  
       - It then recursively looks up SC items in `breakdowns` to show the expanded list with QTY, Price, and more.  
    4. Click **Download Breakdown as CSV** if you need to save or share the data.  
    """)

st.write("---")
st.caption("Logs are written to `cu_sc_tool.log` locally or on the server. Adjust code as needed for your environment.")
