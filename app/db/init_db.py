from app.db.models import Base
from app.db.session import sync_engine


def init_db() -> None:
    Base.metadata.create_all(bind=sync_engine)


if __name__ == "__main__":
    init_db()
