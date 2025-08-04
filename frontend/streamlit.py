import streamlit as st
import requests

BACKEND_URL = "http://localhost:8000"

st.title("Self-Service Analytics")


st.header("Upload Dataset")
uploaded_file = st.file_uploader("Upload ZIP file", type="zip")
schema_file = st.file_uploader("Optional schema (JSON)", type="json")

if st.button("Upload to Backend"):
    if uploaded_file:
        files = {"file": uploaded_file}
        if schema_file:
            files["schema_file"] = schema_file

        response = requests.post(f"{BACKEND_URL}/upload-zip", files=files)

        if response.status_code == 200:
            st.success("Upload successful!")
            st.json(response.json())
        else:
            st.error(f"Upload failed: {response.text}")
    else:
        st.warning("Please upload a ZIP file.")

# Query
st.header("Query Dataset")
dataset_id = st.text_input("Enter Dataset ID")
question = st.text_area("Enter your question")

if st.button("Run Query"):
    payload = {"dataset_id": dataset_id, "question": question}
    response = requests.post(f"{BACKEND_URL}/query", json=payload)

    if response.status_code == 200:
        result = response.json()
        st.subheader("Generated SQL")
        st.code(result["sql"], language="sql")

        st.subheader("Chart Type Suggested")
        st.write(result["chart_type"])

        st.subheader("Query Results")
        st.dataframe(result["result"])
    else:
        st.error(f"Query failed: {response.text}")
