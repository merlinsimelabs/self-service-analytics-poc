import streamlit as st
import requests
import pandas as pd

BACKEND_URL = "http://localhost:8000/api"

st.title("Self-Service Analytics")


st.header("Upload Dataset")
uploaded_file = st.file_uploader("Upload ZIP file", type="zip")
catalog_desc = st.text_area(
    "Provide a brief description of the dataset (the catalog)")


if st.button("Upload to Backend"):
    if uploaded_file and catalog_desc:
        # Use a dictionary for the files part
        files = {"file": (
            uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
        # Use a dictionary for the form data part
        data = {"catalog": catalog_desc}

        # The endpoint is /upload-zip
        response = requests.post(
            f"{BACKEND_URL}/upload-zip", files=files, data=data)

        if response.status_code == 200:
            st.success("Upload successful!")
            st.json(response.json())
        else:
            st.error(f"Upload failed: {response.text}")
    else:
        st.warning(
            "Please upload a ZIP file and provide a catalog description.")

# Query
st.header("Query Dataset")
dataset_id = st.text_input("Enter Dataset ID")
question = st.text_area("Enter your question")

if st.button("Run Query"):
    if not dataset_id or not question:
        st.warning("Please provide both a Dataset ID and a question.")
    else:
        payload = {"dataset_id": dataset_id, "question": question}
        # The endpoint is /query
        response = requests.post(f"{BACKEND_URL}/query", json=payload)

        if response.status_code == 200:
            result = response.json()
            st.subheader("Generated SQL")
            st.code(result["sql_query"], language="sql")

            # --- FIX STARTS HERE ---
            st.subheader("Chart Suggestion")
            chart_info = result["chart_suggestion"]
            st.write(f"**Chart Type:** {chart_info['chart_type']}")
            st.write(f"**Reasoning:** {chart_info['reasoning']}")

            st.subheader("Query Results")
            # Access the 'results' key (plural)
            results_data = result["results"]
            if results_data:
                st.dataframe(pd.DataFrame(results_data))
            else:
                st.write("Query returned no results.")
            # --- FIX ENDS HERE ---
        else:
            st.error(f"Query failed: {response.text}")
