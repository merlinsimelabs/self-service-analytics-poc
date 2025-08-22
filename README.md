# self-service-analytics-poc

A collaborative platform that lets users upload datasets, ask questions in natural language, and receive visual analytics reports instantly using ApexCharts

# Table of Contents

* About the Project
* Features
* Tech Stack
* Project Setup
* Configuration 
* Usage
* API Endpoints

# About the Project

A self-service analytics platform that allows users to query datasets using natural language and automatically generate SQL queries and chart suggestions. The platform supports interactive visualization using ApexCharts and provides an intuitive API for integration.

# Features

* Natural Language Queries: Users can ask questions in plain English. The system translates these into SQL queries.

* SQL Generation via LLM: Automatically generates PostgreSQL queries from user questions and dataset metadata.

* Dynamic Chart Suggestions: Generates suitable chart types with ApexCharts-compatible configuration.

* Data Visualization: Renders charts based on query results.

* Metadata Management: Stores table schema, column types, and relationships for generating accurate queries.

* Extensible & Modular: Built with FastAPI, SQLAlchemy, and Pydantic for easy extension and maintenance.


# Tech Stack

* Backend: Python, FastAPI

* Database: PostgreSQL

* LLM Integration: OpenAI GPT-4o-mini

* Data Processing: Pandas

* Visualization: ApexCharts

* ORM: SQLAlchemy

* Validation: Pydantic

# Project Setup 

* Clonning repository
    git clone https://github.com/merlinsimelabs/self-service-analytics-poc.git      
    cd self-service-analytics-poc

* Create virtual environment for frontend    
    python -m venv venv       
    On Windows: venv\Scripts\activate         

* Install dependencies:       
    pip install -r backend/requirements.txt       
 
* create .env file:         
    OPENAI_API_KEY=      

* Run with docker :     
    docker-compose up --build      
 
 
* To stop application :      
    docker-compose down     

* To run streamlit :       
    streamlit run frontend/streamlit.py       



