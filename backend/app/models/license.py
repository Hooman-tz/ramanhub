from sqlalchemy import Boolean, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class License(Base):
    """Data license. id is a short text slug, e.g. 'CC-BY-4.0'."""

    __tablename__ = "licenses"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    url: Mapped[str] = mapped_column(String)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
