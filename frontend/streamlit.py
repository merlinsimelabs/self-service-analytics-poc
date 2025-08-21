import streamlit as st
import requests
import pandas as pd
import altair as alt

BACKEND_URL = "http://localhost:8000/api"

st.set_page_config(layout="wide")
st.title("Self-Service Analytics")


@st.cache_data(ttl=60)
def get_datasets():
    """Fetches the list of available datasets from the backend API."""
    try:
        response = requests.get(f"{BACKEND_URL}/datasets")
        if response.status_code == 200:
            return response.json()
        else:
            st.error(
                f"Failed to fetch dataset list. Status "
                f"code: {response.status_code}")
            return []
    except requests.exceptions.RequestException as e:
        st.error(
            f"Connection Error: Could not connect to the backend. "
            f"Details: {e}")
        return []


with st.expander("Upload a new dataset", expanded=True):
    with st.form("upload_form", clear_on_submit=True):
        user_defined_name = st.text_input(
            "Enter a unique name for your dataset")
        catalog_desc = st.text_area(
            "Describe the dataset (the catalog)")
        uploaded_file = st.file_uploader(
            "Upload a ZIP file (CSV/XLSX)", type="zip")

        submitted = st.form_submit_button("Upload & Process Dataset")

        if submitted:
            if uploaded_file and catalog_desc and user_defined_name:
                with st.spinner("Processing dataset..."):
                    files = {
                        "file": (uploaded_file.name, uploaded_file.getvalue(),
                                 uploaded_file.type)}
                    data = {"catalog": catalog_desc,
                            "user_defined_name": user_defined_name}
                    try:
                        response = requests.post(f"{BACKEND_URL}/upload-zip",
                                                 files=files, data=data)
                        if response.status_code == 200:
                            st.success(response.json()['message'])
                            st.cache_data.clear()
                        elif response.status_code == 409:
                            st.error(
                                f"Upload Failed: {response.json()['detail']}")
                        else:
                            st.error(
                                f"Upload failed with status {
                                    response.status_code}: "
                                f"{response.text}")
                    except requests.exceptions.RequestException as e:
                        st.error(
                            f"Connection Error: Could not connect to the "
                            f"backend. Details: {e}")
            else:
                st.warning("Please provide a name, description, and ZIP file.")

st.header("Ask a Question")
datasets = get_datasets()

if not datasets:
    st.info("Upload a dataset to begin analyzing.")
else:
    dataset_options = {
                        ds['user_defined_name']: ds['dataset_id']
                        for ds in datasets
                    }
    selected_name = st.selectbox("1. Choose the dataset :",
                                 options=dataset_options.keys())
    question = st.text_area("2. Enter your question :")

    if st.button("Generate Report"):
        if selected_name and question:
            dataset_id = dataset_options[selected_name]
            with st.spinner("Generating SQL and fetching results..."):
                payload = {"dataset_id": dataset_id, "question": question}
                try:
                    response = requests.post(
                        f"{BACKEND_URL}/query", json=payload)
                    if response.status_code == 200:
                        st.session_state['query_result'] = response.json()
                    else:
                        st.error(f"Query failed: {response.text}")
                except requests.exceptions.RequestException as e:
                    st.error(
                        f"Connection Error: Could not connect to the backend. "
                        f"Details: {e}")
        else:
            st.warning("Please choose a dataset and provide a question.")

if 'query_result' in st.session_state:
    result = st.session_state['query_result']
    st.subheader("Generated SQL Query")
    st.code(result.get("sql_query", ""), language="sql")
    st.subheader("Result Visualization")

    chart_info = result.get("chart_suggestion", {})
    chart_type = chart_info.get("chart_type", "table").lower()
    results_data = result.get("results", [])

    if not results_data:
        st.warning("Query returned no data to display.")
    else:
        results_df = pd.DataFrame(results_data)
        try:
            if chart_type == "bar" and results_df.shape[1] >= 2:
                col1, col2 = results_df.columns[0], results_df.columns[1]
                if pd.api.types.is_numeric_dtype(results_df[col1]):
                    value_col, label_col = col1, col2
                else:
                    label_col, value_col = col1, col2
                chart = alt.Chart(results_df).mark_bar().encode(
                    x=alt.X(f'{value_col}:Q', title=str(value_col)),
                    y=alt.Y(f'{label_col}:N', title=str(label_col), sort='-x'),
                    tooltip=[label_col, value_col]
                ).interactive()
                st.altair_chart(chart, use_container_width=True)

            elif chart_type in ["line", "area"] and results_df.shape[1] >= 2:
                col1, col2 = results_df.columns[0], results_df.columns[1]
                if pd.api.types.is_numeric_dtype(results_df[col1]):
                    value_col, label_col = col1, col2
                else:
                    label_col, value_col = col1, col2
                chart = alt.Chart(results_df).mark_line().encode(
                    x=alt.X(f'{label_col}:N', title=str(label_col)),
                    y=alt.Y(f'{value_col}:Q', title=str(value_col)),
                    tooltip=[label_col, value_col]
                ).interactive()
                st.altair_chart(chart, use_container_width=True)

            elif chart_type == "pie" and results_df.shape[1] >= 2:
                label_col = next((
                    col for col in results_df.columns if not
                    pd.api.types.is_numeric_dtype(results_df[col])), None)
                value_col = next((
                    col for col in results_df.columns if
                    pd.api.types.is_numeric_dtype(results_df[col]) and
                    'id' not in col.lower()), None)
                if label_col and value_col:
                    pie_chart = alt.Chart(results_df).mark_arc().encode(
                        theta=alt.Theta(field=value_col,
                                        type='quantitative',
                                        title=value_col),
                        color=alt.Color(field=label_col,
                                        type='nominal',
                                        title=label_col),
                        tooltip=[label_col, value_col]
                    ).interactive()
                    st.altair_chart(pie_chart, use_container_width=True)
                else:
                    st.write("Could not determine appropriate columns for a "
                             "pie chart. Displaying as a table.")
                    st.dataframe(results_df)

            elif chart_type == "scatter" and results_df.shape[1] >= 2:
                x_col = results_df.columns[0]
                y_col = results_df.columns[1]
                tooltip_cols = list(results_df.columns)
                scatter_chart = (
                    alt.Chart(results_df)
                    .mark_circle(size=60)
                    .encode(
                        x=alt.X(x_col, title=str(x_col)),
                        y=alt.Y(y_col, title=str(y_col)),
                        tooltip=tooltip_cols
                    )
                    .interactive()
                )
                st.altair_chart(scatter_chart, use_container_width=True)

            else:
                st.dataframe(results_df)
        except Exception as e:
            st.error(
                f"Could not render the suggested chart. Displaying data "
                f"as a table instead. Error: {e}")
            st.dataframe(results_df)

        with st.expander("View Raw Data"):
            st.dataframe(results_df)
