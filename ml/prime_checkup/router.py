"""JSON-only transport. Safe to mount on an existing FastAPI application."""
from fastapi import APIRouter, Body
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from .engine import build_plan
from .schemas import invalid_result, validation_errors
from .selection import plan_request, public_error, recommend_request, response_http_status


class ContractRoute(APIRoute):
    """Keep transport errors in the public contract, including when mounted."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def checked(request):
            try:
                return await handler(request)
            except RequestValidationError as exc:
                errors = validation_errors(exc.errors())
                if self.name == "predict_api":
                    result = invalid_result(errors)
                else:
                    stage = "recommendation" if self.name == "recommend_api" else "plan"
                    result = public_error(errors, stage)
                return JSONResponse(result, status_code=422)

        return checked


router = APIRouter(route_class=ContractRoute)


@router.post("/recommend")
def recommend_api(payload: object = Body(...)):
    result = recommend_request(payload)
    return JSONResponse(result, status_code=response_http_status(result))


@router.post("/plan")
def plan_api(payload: object = Body(...)):
    result = plan_request(payload)
    return JSONResponse(result, status_code=response_http_status(result))


@router.post("/predict")
def predict_api(patient: object = Body(...)):
    result = build_plan(patient)
    return JSONResponse(result, status_code=422 if result["status"] == "invalid" else 200)
