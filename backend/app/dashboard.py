from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from .config import engine
from uuid import uuid4
from typing import List, Dict, Any
import json
router = APIRouter()

class DashboardCreate(BaseModel):
    user_id: str
    dataset_id: str
    dashboard_name: str

class DashboardUpdate(BaseModel):
    dashboard_name: str

class ChartCreate(BaseModel):
    chart_type: str
    sql_query: str
    chart_config: Dict[str, Any]

class ChartUpdate(BaseModel):
    chart_config: Dict[str, Any]

@router.post("/dashboards", status_code=201)
async def create_dashboard(dashboard: DashboardCreate):
    dashboard_id = str(uuid4())
    with engine.connect() as conn:
        conn.execute(text(
            "INSERT INTO dashboards (dashboard_id, user_id, dataset_id, dashboard_name) "
            "VALUES (:dashboard_id, :user_id, :dataset_id, :dashboard_name)"
        ), {
            "dashboard_id": dashboard_id,
            "user_id": dashboard.user_id,
            "dataset_id": dashboard.dataset_id,
            "dashboard_name": dashboard.dashboard_name
        })
        conn.commit()
    return {"dashboard_id": dashboard_id, **dashboard.dict()}

@router.get("/dashboards")
async def get_dashboards(user_id: str):
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT dashboard_id, dashboard_name FROM dashboards WHERE user_id = :user_id"
        ), {"user_id": user_id}).fetchall()
    return [{"dashboard_id": row[0], "dashboard_name": row[1]} for row in result]

@router.get("/dashboards/{dashboard_id}")
async def get_dashboard(dashboard_id: str):
    with engine.connect() as conn:
        dashboard = conn.execute(text(
            "SELECT * FROM dashboards WHERE dashboard_id = :dashboard_id"
        ), {"dashboard_id": dashboard_id}).fetchone()
        if not dashboard:
            raise HTTPException(status_code=404, detail="Dashboard not found")
        charts = conn.execute(text(
            "SELECT * FROM dashboard_charts WHERE dashboard_id = :dashboard_id"
        ), {"dashboard_id": dashboard_id}).fetchall()
    return {
        "dashboard": dict(dashboard._mapping),
        "charts": [dict(chart._mapping) for chart in charts]
    }

@router.put("/dashboards/{dashboard_id}")
async def update_dashboard(dashboard_id: str, dashboard: DashboardUpdate):
    with engine.connect() as conn:
        conn.execute(text(
            "UPDATE dashboards SET dashboard_name = :dashboard_name "
            "WHERE dashboard_id = :dashboard_id"
        ), {"dashboard_name": dashboard.dashboard_name, "dashboard_id": dashboard_id})
        conn.commit()
    return {"message": "Dashboard updated successfully"}

@router.delete("/dashboards/{dashboard_id}")
async def delete_dashboard(dashboard_id: str):
    with engine.connect() as conn:
        conn.execute(text(
            "DELETE FROM dashboards WHERE dashboard_id = :dashboard_id"
        ), {"dashboard_id": dashboard_id})
        conn.commit()
    return {"message": "Dashboard deleted successfully"}

@router.post("/dashboards/{dashboard_id}/charts", status_code=201)
async def add_chart_to_dashboard(dashboard_id: str, chart: ChartCreate):
    chart_id = str(uuid4())
    with engine.connect() as conn:
        conn.execute(text(
            "INSERT INTO dashboard_charts (chart_id, dashboard_id, chart_type, sql_query, chart_config) "
            "VALUES (:chart_id, :dashboard_id, :chart_type, :sql_query, :chart_config)"
        ), {
            "chart_id": chart_id,
            "dashboard_id": dashboard_id,
            "chart_type": chart.chart_type,
            "sql_query": chart.sql_query,
            "chart_config": json.dumps(chart.chart_config)
        })
        conn.commit()
    return {"chart_id": chart_id, **chart.dict()}

@router.put("/charts/{chart_id}")
async def update_chart(chart_id: str, chart: ChartUpdate):
    with engine.connect() as conn:
        conn.execute(text(
            "UPDATE dashboard_charts SET chart_config = :chart_config "
            "WHERE chart_id = :chart_id"
        ), {"chart_config": chart.chart_config, "chart_id": chart_id})
        conn.commit()
    return {"message": "Chart updated successfully"}

@router.delete("/charts/{chart_id}")
async def delete_chart(chart_id: str):
    with engine.connect() as conn:
        conn.execute(text(
            "DELETE FROM dashboard_charts WHERE chart_id = :chart_id"
        ), {"chart_id": chart_id})
        conn.commit()
    return {"message": "Chart deleted successfully"}