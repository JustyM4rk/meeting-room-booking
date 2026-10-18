from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

# 1. Рядок підключення до БД
#    Формат: "postgresql://USER:PASSWORD@HOST:PORT/DB_NAME"
#    Ці дані ми взяли з вашого docker-compose.yml
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/booking_db")

# 2. Створення "рушія" (engine)
#    Це головний об'єкт SQLAlchemy для роботи з БД
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300
)

# 3. Створення "фабрики" сесій
#    Сесія - це ваш "посередник" для спілкування з БД
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 4. Створення базового класу для моделей
#    Всі наші класи-таблиці (models) будуть наслідувати його
Base = declarative_base()


# 5. Залежність FastAPI: одна сесія БД на запит
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
