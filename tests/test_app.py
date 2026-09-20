from importlib import import_module

from fastapi.testclient import TestClient

from app import app

app_module = import_module("app.main")
client = TestClient(app)


def test_index_serves_built_frontend():
    response = client.get("/")

    assert response.status_code == 200
    assert "PuddingTrackRater" in response.text


def test_assets_are_served():
    stylesheet = next((app_module.STATIC_DIR / "assets").glob("*.css"))
    response = client.get(f"/assets/{stylesheet.name}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")


def test_parse_kml_requires_file():
    response = client.post("/api/parse_kml")

    assert response.status_code == 400
    assert response.json() == {
        "code": 400,
        "msg": "缺少kml_file参数",
        "data": {},
    }


def test_parse_kml_returns_metrics(monkeypatch):
    expected_metrics = app_module.RouteMetrics(
        total_distance_km=12.3,
        total_elevation_m=456.0,
        total_time_h=3.5,
        speed_mean_km_h=3.51,
        speed_std_km_h=0.42,
        tired_score=789.0,
        tired_level=1.2,
        elev_score=34.0,
        elev_level=0.8,
    )
    monkeypatch.setattr(app_module, "rate_kml", lambda contents: expected_metrics)

    response = client.post(
        "/api/parse_kml",
        files={
            "kml_file": (
                "route.kml",
                b"<kml />",
                "application/vnd.google-earth.kml+xml",
            )
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "code": 200,
        "msg": "操作成功",
        "data": expected_metrics.model_dump(),
    }


def test_parse_kml_end_to_end():
    kml = b"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document><Placemark><LineString><coordinates>
    120.0000,30.0000,10 120.0010,30.0010,20
    120.0020,30.0020,15 120.0030,30.0030,30
  </coordinates></LineString></Placemark></Document>
</kml>"""

    response = client.post(
        "/api/parse_kml",
        files={
            "kml_file": (
                "route.kml",
                kml,
                "application/vnd.google-earth.kml+xml",
            )
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total_distance_km"] > 0
    assert data["total_elevation_m"] > 0
    assert data["total_time_h"] is None


def test_parse_kml_reports_parser_errors(monkeypatch):
    def fail_to_parse(contents):
        raise ValueError("invalid kml")

    monkeypatch.setattr(app_module, "rate_kml", fail_to_parse)

    response = client.post(
        "/api/parse_kml",
        files={
            "kml_file": (
                "route.kml",
                b"invalid",
                "application/vnd.google-earth.kml+xml",
            )
        },
    )

    assert response.status_code == 500
    assert response.json() == {
        "code": 500,
        "msg": "解析KML文件异常",
        "data": {},
    }


def test_unknown_route_uses_api_error_shape():
    response = client.get("/missing")

    assert response.status_code == 404
    assert response.json() == {"code": 404, "msg": "接口不存在", "data": {}}


def test_wrong_method_uses_api_error_shape():
    response = client.get("/api/parse_kml")

    assert response.status_code == 405
    assert response.json() == {"code": 405, "msg": "请求方式错误", "data": {}}
