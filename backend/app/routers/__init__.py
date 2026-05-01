"""API routers package."""

from fastapi import APIRouter


def _strip_legacy_example_kw(method):
    """FastAPI compatibility shim: ignore legacy `example=` decorator metadata."""

    def wrapper(self, path: str, *args, **kwargs):
        kwargs.pop("example", None)
        return method(self, path, *args, **kwargs)

    return wrapper


APIRouter.get = _strip_legacy_example_kw(APIRouter.get)
APIRouter.post = _strip_legacy_example_kw(APIRouter.post)
APIRouter.put = _strip_legacy_example_kw(APIRouter.put)
APIRouter.patch = _strip_legacy_example_kw(APIRouter.patch)
APIRouter.delete = _strip_legacy_example_kw(APIRouter.delete)
