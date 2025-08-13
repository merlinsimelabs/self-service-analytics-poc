import streamlit as st
import requests
import pandas as pd
import altair as alt


BACKEND_URL = "http://localhost:8000/api"

st.set_page_config(layout="wide")
st.title("Self-Service Analytics")


with st.expander("Upload a new dataset", expanded=True):
    uploaded_file = st.file_uploader(
        "Upload a ZIP file containing CSV or XLSX files", type="zip"
    )
    catalog_desc = st.text_area(
        "Provide a brief description of the dataset (the catalog)",
        help="Example: This dataset contains sales transactions with customer "
        "and product details."
    )

    if st.button("Upload & Process Dataset"):
        if uploaded_file and catalog_desc:
            with st.spinner("Processing dataset... This may take a moment."):
                files = {
                    "file": (
                        uploaded_file.name,
                        uploaded_file.getvalue(),
                        uploaded_file.type
                    )
                }
                data = {"catalog": catalog_desc}
                try:
                    response = requests.post(
                        f"{BACKEND_URL}/upload-zip", files=files, data=data
                    )
                    if response.status_code == 200:
                        st.success("Dataset processed successfully!")
                        st.session_state['upload_result'] = response.json()
                    else:
                        st.error(f"Upload failed: {response.text}")
                except requests.exceptions.RequestException as e:
                    st.error(
                        f"Connection Error: Could not connect to the backend."
                        f"Details: {e}")
        else:
            st.warning(
                "Please upload a ZIP file and provide a catalog description.")

if 'upload_result' in st.session_state:
    upload_result = st.session_state['upload_result']
    st.info(
        f"Dataset ready. Use the following ID for querying:"
        f"`{upload_result['dataset_id']}`")

st.header("Ask a Question")
dataset_id = st.text_input("Enter the Dataset ID from above")
question = st.text_area("Enter your question in natural language")

if st.button("Generate Report"):
    if not dataset_id or not question:
        st.warning("Please provide both a Dataset ID and a question.")
    else:
        with st.spinner("Generating SQL and fetching results..."):
            payload = {"dataset_id": dataset_id, "question": question}
            try:
                response = requests.post(f"{BACKEND_URL}/query", json=payload)
                if response.status_code == 200:
                    st.session_state['query_result'] = response.json()
                else:
                    st.error(f"Query failed: {response.text}")
            except requests.exceptions.RequestException as e:
                st.error(
                    f"Connection Error: Could not connect to the backend."
                    f"Details: {e}")


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
                    x=alt.X(value_col, type='quantitative',
                            title=str(value_col)),
                    y=alt.Y(label_col, type='nominal',
                            title=str(label_col),
                            sort='-x'),
                    tooltip=[label_col, value_col]
                ).interactive()
                st.altair_chart(chart, use_container_width=True)

            elif chart_type in ["line", "area"] and results_df.shape[1] >= 2:
                col1, col2 = results_df.columns[0], results_df.columns[1]
                if pd.api.types.is_numeric_dtype(results_df[col1]):
                    value_col, label_col = col1, col2
                else:
                    label_col, value_col = col1, col2

                mark = (
                        alt.mark_area()
                        if chart_type == 'area'
                        else alt.mark_line()
                    )

                chart = alt.Chart(results_df).mark_line().encode(
                    x=alt.X(label_col, type='nominal', title=str(label_col)),
                    y=alt.Y(value_col,
                            type='quantitative',
                            title=str(value_col)),
                    tooltip=[label_col, value_col]
                ).interactive()
                st.altair_chart(chart, use_container_width=True)

            elif chart_type == "pie" and results_df.shape[1] >= 2:
                label_col = next(
                            (
                                col for col in results_df.columns
                                if not pd.api.types.is_numeric_dtype(
                                    results_df[col])
                            ),
                            None
                        )

                value_col = next(
                    (
                        col for col in results_df.columns
                        if pd.api.types.is_numeric_dtype(results_df[col])
                        and 'id' not in col.lower()
                    ),
                    None
                )

                if label_col and value_col:
                    pie_chart = alt.Chart(results_df).mark_arc().encode(
                        theta=alt.Theta(
                            field=value_col,
                            type='quantitative',
                            title=value_col),
                        color=alt.Color(
                            field=label_col, type='nominal', title=label_col),
                        tooltip=[label_col, value_col]
                    ).interactive()
                    st.altair_chart(pie_chart, use_container_width=True)
                else:
                    st.write("Could not determine appropriate columns for a "
                             "pie chart. Displaying as a table.")
                    st.dataframe(results_df)

            elif chart_type == "scatter" and results_df.shape[1] >= 2:
                scatter_chart = alt.Chart(
                    results_df).mark_circle(size=60).encode(
                    x=alt.X(results_df.columns[0], title=str(
                        results_df.columns[0])),
                    y=alt.Y(results_df.columns[1], title=str(
                        results_df.columns[1])),
                    tooltip=list(results_df.columns)
                ).interactive()
                st.altair_chart(scatter_chart, use_container_width=True)

            else:
                st.dataframe(results_df)

        except Exception as e:
            st.error(
                f"Could not render the suggested chart. Displaying data as a "
                f"table instead. Error: {e}")
            st.dataframe(results_df)

        with st.expander("View Raw Data"):
            st.dataframe(results_df)
