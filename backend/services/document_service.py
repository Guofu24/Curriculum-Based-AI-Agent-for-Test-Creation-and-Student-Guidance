from sqlalchemy.ext.asyncio import AsyncSession

from services.textbook_service import TextbookService


class DocumentService(TextbookService):
    """
    Thin alias around the legacy TextbookService so new document-oriented APIs
    can coexist with the old textbook routes.
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db)
