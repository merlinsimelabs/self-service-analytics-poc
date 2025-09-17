from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from .config import engine
from uuid import uuid4
from typing import List, Dict, Any
import json
from .database import get_db
from typing import Optional
from fastapi import Depends
from .utils import UniformResponse
from datetime import datetime
from sqlalchemy.orm import Session


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
    chart_type: Optional[str] = None 
    chart_config: Optional[dict]
    

@router.post("/dashboards", status_code=201)
async def create_dashboard(dashboard: DashboardCreate):
    try:
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
        return UniformResponse(
            data={"dashboard_id": dashboard_id, **dashboard.dict()},
            message="Dashboard created successfully"
        )
    except Exception as e:
        return UniformResponse(
            data_status="error",
            status=500,
            message="Failed to create dashboard",
            error={"detail": str(e)}
        )

@router.get("/dashboards")
async def get_dashboards(user_id: str):
    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                "SELECT dashboard_id, dashboard_name FROM dashboards WHERE user_id = :user_id"
            ), {"user_id": user_id}).fetchall()
        dashboards_data = [{"dashboard_id": row[0], "dashboard_name": row[1]} for row in result]
        return UniformResponse(data=dashboards_data, message="Dashboards retrieved successfully")
    except Exception as e:
        return UniformResponse(
            data_status="error",
            status=500,
            message="Failed to retrieve dashboards",
            error={"detail": str(e)}
        )
@router.get("/dashboards/{dashboard_id}")
async def get_dashboard(dashboard_id: str):
    try:
        with engine.connect() as conn:
            dashboard = conn.execute(text(
                "SELECT * FROM dashboards WHERE dashboard_id = :dashboard_id"
            ), {"dashboard_id": dashboard_id}).fetchone()
            if not dashboard:
                return UniformResponse(
                    data_status="error",
                    status=404,
                    message="Dashboard not found",
                    error={"detail": "Dashboard with this ID does not exist"}
                )
            charts = conn.execute(text(
                "SELECT * FROM dashboard_charts WHERE dashboard_id = :dashboard_id"
            ), {"dashboard_id": dashboard_id}).fetchall()
        
        dashboard_data = dict(dashboard._mapping)
        # Convert datetime objects in dashboard_data to string
        for key, value in dashboard_data.items():
            if isinstance(value, datetime):
                dashboard_data[key] = value.isoformat()

        charts_data = []
        for chart in charts:
            chart_dict = dict(chart._mapping)
            # Convert datetime objects in chart_dict to string
            for key, value in chart_dict.items():
                if isinstance(value, datetime):
                    chart_dict[key] = value.isoformat()
            
            if 'chart_config' in chart_dict and chart_dict['chart_config']:
                try:
                    chart_dict['chart_config'] = json.loads(chart_dict['chart_config'])
                except json.JSONDecodeError:
                    pass # Keep as string if decoding fails or is not JSON
            charts_data.append(chart_dict)

        return UniformResponse(
            data={
                "dashboard": dashboard_data,
                "charts": charts_data
            },
            message="Dashboard retrieved successfully"
        )
    except Exception as e:
        return UniformResponse(
            data_status="error",
            status=500,
            message="Failed to retrieve dashboard",
            error={"detail": str(e)}
        )

@router.put("/dashboards/{dashboard_id}")
async def update_dashboard(dashboard_id: str, dashboard: DashboardUpdate):
    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                "UPDATE dashboards SET dashboard_name = :dashboard_name "
                "WHERE dashboard_id = :dashboard_id"
            ), {"dashboard_name": dashboard.dashboard_name, "dashboard_id": dashboard_id})
            conn.commit()
            if result.rowcount == 0:
                return UniformResponse(
                    data_status="error",
                    status=404,
                    message="Dashboard not found",
                    error={"detail": "Dashboard with this ID does not exist"}
                )
        return UniformResponse(message="Dashboard updated successfully")
    except Exception as e:
        return UniformResponse(
            data_status="error",
            status=500,
            message="Failed to update dashboard",
            error={"detail": str(e)}
        )

@router.delete("/dashboards/{dashboard_id}")
async def delete_dashboard(dashboard_id: str):
    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                "DELETE FROM dashboards WHERE dashboard_id = :dashboard_id"
            ), {"dashboard_id": dashboard_id})
            conn.commit()
            if result.rowcount == 0:
                return UniformResponse(
                    data_status="error",
                    status=404,
                    message="Dashboard not found",
                    error={"detail": "Dashboard with this ID does not exist"}
                )
        return UniformResponse(message="Dashboard deleted successfully")
    except Exception as e:
        return UniformResponse(
            data_status="error",
            status=500,
            message="Failed to delete dashboard",
            error={"detail": str(e)}
        )

@router.post("/dashboards/{dashboard_id}/charts", status_code=201)
async def add_chart_to_dashboard(dashboard_id: str, chart: ChartCreate):
    try:
        chart_id = str(uuid4())
        with engine.connect() as conn:
            # First check if dashboard exists
            dashboard_exists = conn.execute(text(
                "SELECT 1 FROM dashboards WHERE dashboard_id = :dashboard_id"
            ), {"dashboard_id": dashboard_id}).fetchone()
            if not dashboard_exists:
                return UniformResponse(
                    data_status="error",
                    status=404,
                    message="Dashboard not found",
                    error={"detail": "Dashboard with this ID does not exist"}
                )

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
        return UniformResponse(
            data={"chart_id": chart_id, **chart.dict()},
            message="Chart added to dashboard successfully"
        )
    except Exception as e:
        return UniformResponse(
            data_status="error",
            status=500,
            message="Failed to add chart to dashboard",
            error={"detail": str(e)}
        )

@router.put("/charts/{chart_id}")
async def update_chart(chart_id: str, chart_update_data: ChartUpdate):
    try:
        with engine.begin() as conn:  # engine.begin() auto-commits or rolls back
            existing_chart = conn.execute(
                text("SELECT chart_id, chart_type, chart_config FROM dashboard_charts WHERE chart_id = :chart_id"),
                {"chart_id": chart_id}
            ).fetchone()

            if not existing_chart:
                return UniformResponse(
                    data_status="error",
                    status=404,
                    message="Chart not found"
                )

            # Parse current config from DB
            current_config = {}
            if existing_chart.chart_config:
                try:
                    current_config = json.loads(existing_chart.chart_config)
                except Exception:
                    current_config = {}

            # Merge with update
            new_config = chart_update_data.chart_config or current_config

            # ✅ Force to JSON string no matter what
            chart_config_str = json.dumps(new_config, default=str)

            conn.execute(
                text("""
                    UPDATE dashboard_charts
                    SET chart_type = :chart_type,
                        chart_config = :chart_config
                    WHERE chart_id = :chart_id
                """),
                {
                    "chart_type": chart_update_data.chart_type or existing_chart.chart_type,
                    "chart_config": chart_config_str,
                    "chart_id": chart_id
                }
            )

        return UniformResponse(
            message="Chart updated successfully",
            status=200,
            data_status="success"
        )

    except Exception as e:
        return UniformResponse(
            data_status="error",
            status=500,
            message="Failed to update chart",
            error={"detail": str(e)}
        )
@router.delete("/charts/{chart_id}")
async def delete_chart(chart_id: str):
    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                "DELETE FROM dashboard_charts WHERE chart_id = :chart_id"
            ), {"chart_id": chart_id})
            conn.commit()
            if result.rowcount == 0:
                return UniformResponse(
                    data_status="error",
                    status=404,
                    message="Chart not found",
                    error={"detail": "Chart with this ID does not exist"}
                )
        return UniformResponse(message="Chart deleted successfully")
    except Exception as e:
        return UniformResponse(
            data_status="error",
            status=500,
            message="Failed to delete chart",
            error={"detail": str(e)}
        )