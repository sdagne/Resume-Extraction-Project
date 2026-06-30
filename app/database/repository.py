# app/database/repository.py

from typing import Generic, TypeVar, Type, Optional, List, Any
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import select, update, delete, func

from app.database.connection import Base
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ─── Generic Type Variable ─────────────────────────────────────────────────────
ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """
    Generic CRUD repository providing reusable database operations
    for any SQLAlchemy model. Extend this class for model-specific repos.
    """

    def __init__(self, model: Type[ModelType], db: Session):
        self.model = model
        self.db    = db

    # ─── Create ────────────────────────────────────────────────────────────────
    def create(self, data: dict) -> ModelType:
        """Create and persist a new record."""
        try:
            instance = self.model(**data)
            self.db.add(instance)
            self.db.flush()        # Get ID without full commit
            self.db.refresh(instance)
            logger.debug(f"Created {self.model.__name__}: {instance}")
            return instance
        except Exception as e:
            logger.error(f"Create failed for {self.model.__name__}: {e}")
            raise

    def bulk_create(self, data_list: List[dict]) -> List[ModelType]:
        """Create multiple records in a single transaction."""
        try:
            instances = [self.model(**data) for data in data_list]
            self.db.add_all(instances)
            self.db.flush()
            logger.debug(f"Bulk created {len(instances)} {self.model.__name__} records")
            return instances
        except Exception as e:
            logger.error(f"Bulk create failed for {self.model.__name__}: {e}")
            raise

    # ─── Read ──────────────────────────────────────────────────────────────────
    def get_by_id(self, record_id: UUID | str) -> Optional[ModelType]:
        """Fetch a single record by primary key."""
        try:
            return self.db.get(self.model, record_id)
        except Exception as e:
            logger.error(f"Get by ID failed for {self.model.__name__}: {e}")
            raise

    def get_all(
        self,
        skip: int = 0,
        limit: int = 100,
        order_by: Optional[str] = None,
        descending: bool = True,
    ) -> List[ModelType]:
        """Fetch all records with optional pagination and ordering."""
        try:
            stmt = select(self.model)

            if order_by and hasattr(self.model, order_by):
                col = getattr(self.model, order_by)
                stmt = stmt.order_by(col.desc() if descending else col.asc())

            stmt = stmt.offset(skip).limit(limit)
            return list(self.db.scalars(stmt).all())
        except Exception as e:
            logger.error(f"Get all failed for {self.model.__name__}: {e}")
            raise

    def get_by_field(
        self,
        field: str,
        value: Any,
        first_only: bool = True,
    ) -> Optional[ModelType] | List[ModelType]:
        """Fetch record(s) by any model field."""
        try:
            if not hasattr(self.model, field):
                raise ValueError(f"Field '{field}' not found on {self.model.__name__}")

            stmt = select(self.model).where(
                getattr(self.model, field) == value
            )

            if first_only:
                return self.db.scalars(stmt).first()
            return list(self.db.scalars(stmt).all())
        except Exception as e:
            logger.error(f"Get by field failed for {self.model.__name__}: {e}")
            raise

    def filter_by(self, filters: dict) -> List[ModelType]:
        """
        Fetch records matching all given field=value pairs.

        Usage:
            repo.filter_by({"status": "completed", "pdf_type": "digital"})
        """
        try:
            stmt = select(self.model)
            for field, value in filters.items():
                if hasattr(self.model, field):
                    stmt = stmt.where(getattr(self.model, field) == value)
            return list(self.db.scalars(stmt).all())
        except Exception as e:
            logger.error(f"Filter by failed for {self.model.__name__}: {e}")
            raise

    def exists(self, field: str, value: Any) -> bool:
        """Check if a record with given field=value exists."""
        try:
            stmt = select(
                func.count(getattr(self.model, "id"))
            ).where(getattr(self.model, field) == value)
            count = self.db.scalar(stmt)
            return (count or 0) > 0
        except Exception as e:
            logger.error(f"Exists check failed for {self.model.__name__}: {e}")
            raise

    def count(self, filters: Optional[dict] = None) -> int:
        """Count records with optional filters."""
        try:
            stmt = select(func.count(getattr(self.model, "id")))
            if filters:
                for field, value in filters.items():
                    if hasattr(self.model, field):
                        stmt = stmt.where(getattr(self.model, field) == value)
            return self.db.scalar(stmt) or 0
        except Exception as e:
            logger.error(f"Count failed for {self.model.__name__}: {e}")
            raise

    # ─── Update ────────────────────────────────────────────────────────────────
    def update(self, record_id: UUID | str, data: dict) -> Optional[ModelType]:
        """Update a record by ID with given field values."""
        try:
            stmt = (
                update(self.model)
                .where(getattr(self.model, "id") == record_id)
                .values(**data)
                .returning(self.model)
            )
            result = self.db.scalars(stmt).first()
            self.db.flush()
            logger.debug(f"Updated {self.model.__name__} id={record_id}")
            return result
        except Exception as e:
            logger.error(f"Update failed for {self.model.__name__} id={record_id}: {e}")
            raise

    def update_instance(self, instance: ModelType, data: dict) -> ModelType:
        """Update an already-loaded model instance."""
        try:
            for key, value in data.items():
                if hasattr(instance, key):
                    setattr(instance, key, value)
            self.db.flush()
            self.db.refresh(instance)
            return instance
        except Exception as e:
            logger.error(f"Update instance failed for {self.model.__name__}: {e}")
            raise

    # ─── Delete ────────────────────────────────────────────────────────────────
    def delete(self, record_id: UUID | str) -> bool:
        """Hard delete a record by ID. Returns True if deleted."""
        try:
            stmt = (
                delete(self.model)
                .where(getattr(self.model, "id") == record_id)
            )
            result = self.db.execute(stmt)
            self.db.flush()
            deleted = result.rowcount > 0
            if deleted:
                logger.debug(f"Deleted {self.model.__name__} id={record_id}")
            return deleted
        except Exception as e:
            logger.error(f"Delete failed for {self.model.__name__} id={record_id}: {e}")
            raise

    def delete_instance(self, instance: ModelType) -> None:
        """Delete an already-loaded model instance."""
        try:
            self.db.delete(instance)
            self.db.flush()
        except Exception as e:
            logger.error(f"Delete instance failed for {self.model.__name__}: {e}")
            raise
