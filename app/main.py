import io
import logging
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.rater import Rater

LOGGER = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent / "static" / "dist"

CODE_SUCCESS = status.HTTP_200_OK
CODE_PARAM_ERROR = status.HTTP_400_BAD_REQUEST
CODE_NOT_FOUND = status.HTTP_404_NOT_FOUND
CODE_METHOD_ERROR = status.HTTP_405_METHOD_NOT_ALLOWED
CODE_VALIDATION_ERROR = 422
CODE_SERVER_ERROR = status.HTTP_500_INTERNAL_SERVER_ERROR


class RouteMetrics(BaseModel):
    total_distance_km: float
    total_elevation_m: float
    total_time_h: float | None = None
    speed_mean_km_h: float | None = None
    speed_std_km_h: float | None = None
    tired_score: float
    tired_level: float
    elev_score: float
    elev_level: float


class ApiResponse(BaseModel):
    code: int = CODE_SUCCESS
    msg: str = "操作成功"
    data: RouteMetrics


class ErrorResponse(BaseModel):
    code: int
    msg: str
    data: dict[str, Any] = Field(default_factory=dict)


def api_response(code: int, msg: str, data: Any = None) -> JSONResponse:
    content = {"code": code, "msg": msg, "data": {} if data is None else data}
    return JSONResponse(status_code=code, content=jsonable_encoder(content))


def rate_kml(contents: bytes) -> RouteMetrics:
    rater = Rater.from_kml(io.BytesIO(contents))
    return RouteMetrics(**rater.get_metrics())


def create_app() -> FastAPI:
    application = FastAPI(
        title="PuddingTrackRater",
        description="解析 KML 轨迹并计算路线难度指标。",
        version="1.0.0",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origin_regex=".*",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        request: Request, error: StarletteHTTPException
    ) -> JSONResponse:
        del request
        messages = {
            CODE_NOT_FOUND: "接口不存在",
            CODE_METHOD_ERROR: "请求方式错误",
        }
        return api_response(
            code=error.status_code,
            msg=messages.get(error.status_code, str(error.detail)),
        )

    @application.exception_handler(RequestValidationError)
    async def handle_validation_exception(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        del request
        return api_response(
            code=CODE_VALIDATION_ERROR,
            msg="请求参数错误",
            data={"errors": error.errors()},
        )

    @application.exception_handler(Exception)
    async def handle_unexpected_exception(
        request: Request, error: Exception
    ) -> JSONResponse:
        del request
        LOGGER.error(
            "服务器内部异常",
            exc_info=(type(error), error, error.__traceback__),
        )
        return api_response(code=CODE_SERVER_ERROR, msg="服务器内部异常")

    @application.get("/", include_in_schema=False, response_class=FileResponse)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @application.post(
        "/api/parse_kml",
        response_model=ApiResponse,
        responses={
            CODE_PARAM_ERROR: {"model": ErrorResponse},
            CODE_VALIDATION_ERROR: {"model": ErrorResponse},
            CODE_SERVER_ERROR: {"model": ErrorResponse},
        },
    )
    async def parse_kml(
        kml_file: Annotated[UploadFile | None, File()] = None,
    ) -> ApiResponse | JSONResponse:
        if kml_file is None:
            return api_response(code=CODE_PARAM_ERROR, msg="缺少kml_file参数")

        try:
            contents = await kml_file.read()
            metrics = await run_in_threadpool(rate_kml, contents)
            return ApiResponse(data=metrics)
        except Exception:
            LOGGER.exception("解析KML文件异常")
            return api_response(code=CODE_SERVER_ERROR, msg="解析KML文件异常")
        finally:
            await kml_file.close()

    application.mount(
        "/assets",
        StaticFiles(directory=STATIC_DIR / "assets"),
        name="assets",
    )
    return application


app = create_app()
