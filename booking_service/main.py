from typing import List
from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from datetime import datetime, timedelta

# --- Імпорти модулів ---
import models, schemas, crud, analytics, ml_engine
from database import SessionLocal, engine, get_db
from auth import create_access_token, get_current_user, require_admin
from email_service import send_email
# НОВЕ: Імпорт функцій планувальника
from scheduler import scheduler, schedule_booking_reminders, cancel_booking_reminders

# --- Налаштування безпеки (Bcrypt) ---
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- Створення таблиць ---
models.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Booking Service"
)

# --- Налаштування CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://main-project-nu-ecru.vercel.app", # Vercel
        "http://localhost:5173",                   # Локальний Vite
        "http://127.0.0.1:5173"                    # Локальний Vite (альтернатива)
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# НОВЕ: Запуск та зупинка планувальника разом із FastAPI
@app.on_event("startup")
def startup_event():
    scheduler.start()
    print("⏰ Планувальник завдань (APScheduler) запущено!")

@app.on_event("shutdown")
def shutdown_event():
    scheduler.shutdown()
    print("🛑 Планувальник завдань зупинено.")

# ==========================================
# API ENDPOINTS
# ==========================================

@app.get("/")
def read_root():
    return {"message": "Booking Service запущено!"}

# --- ЛОГІН ---
@app.post("/login/")
def login(creds: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == creds.email).first()
    # One generic message for both cases, so the endpoint does not reveal which emails exist
    if not user or not pwd_context.verify(creds.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Невірний email або пароль")
    
    return {
        "access_token": create_access_token(user),
        "token_type": "bearer",
        "user_id": user.id,
        "name": user.name,
        "role": user.role,
        "department": user.department
    }

# --- КІМНАТИ ---
@app.get("/rooms/", response_model=List[schemas.Room])
def read_rooms(skip: int = 0, limit: int = 100, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    return crud.get_rooms(db, skip=skip, limit=limit)

@app.post("/rooms/", response_model=schemas.Room)
def create_new_room(room: schemas.RoomCreate, db: Session = Depends(get_db), admin: models.User = Depends(require_admin)):
    db_room = crud.get_room_by_name(db, name=room.name)
    if db_room:
        raise HTTPException(status_code=400, detail="Кімната з такою назвою вже існує")
    return crud.create_room(db=db, room=room)

# --- КОРИСТУВАЧІ ---
# <--- НОВИЙ МАРШРУТ ДЛЯ ОТРИМАННЯ ВСІХ КОРИСТУВАЧІВ --->
@app.get("/users/", response_model=List[schemas.User])
def read_users(skip: int = 0, limit: int = 100, db: Session = Depends(get_db), admin: models.User = Depends(require_admin)):
    return crud.get_users(db, skip=skip, limit=limit)

@app.post("/users/", response_model=schemas.User)
def create_new_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    db_user = crud.get_user_by_email(db, email=user.email)
    if db_user:
        raise HTTPException(status_code=400, detail="Цей email вже зареєстровано")
    return crud.create_user(db=db, user=user)

# --- БРОНЮВАННЯ (Створення) ---
@app.post("/bookings/", response_model=schemas.Booking)
def create_new_booking(booking: schemas.BookingCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    # A user can only book for themselves (admins may book on behalf of others)
    if str(booking.user_id) != str(current_user.id) and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Не можна бронювати від імені іншого користувача")

    now = datetime.now()
    booking_start = booking.start_time
    booking_end = booking.end_time  

    if booking_start.tzinfo:
        booking_start = booking_start.replace(tzinfo=None)
    if booking_end.tzinfo:
        booking_end = booking_end.replace(tzinfo=None)
    
    if booking_start < (now - timedelta(minutes=15)):
        raise HTTPException(status_code=400, detail="Не можна бронювати час у далекому минулому!")
        
    if booking_end <= booking_start:
        raise HTTPException(status_code=400, detail="Час завершення має бути пізніше часу початку!")

    room = db.query(models.Room).filter(models.Room.id == booking.room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Кімнату не знайдено")

    is_available = crud.check_availability(
        db, 
        room_id=booking.room_id, 
        start_time=booking.start_time, 
        end_time=booking.end_time
    )
    
    if not is_available:
        raise HTTPException(status_code=409, detail="Кімната зайнята на цей час!")

    # Створюємо запис у БД
    db_booking = crud.create_booking(db=db, booking=booking)

    user = db.query(models.User).filter(models.User.id == db_booking.user_id).first()
    
    status_text = "⏳ Очікує підтвердження" if db_booking.status == "pending" else "✅ Підтверджено"
    subject = f"Деталі вашого бронювання: {room.name}"
    body = f"Привіт, {user.name}!\n\nВи успішно створили заявку на бронювання.\n\nДеталі:\n- Кімната: {room.name}\n- Початок: {db_booking.start_time.strftime('%d.%m.%Y %H:%M')}\n- Завершення: {db_booking.end_time.strftime('%d.%m.%Y %H:%M')}\n- Статус: {status_text}\n\nДякуємо, що користуєтесь нашою системою!"
    
    background_tasks.add_task(send_email, user.email, subject, body)

    # Плануємо нагадування, тільки якщо воно одразу підтверджене (тривалість < 3 год)
    if db_booking.status == "confirmed":
        schedule_booking_reminders(str(db_booking.id), user.email, user.name, room.name, db_booking.start_time)

    return db_booking

# --- БРОНЮВАННЯ (Список) ---
@app.get("/bookings/", response_model=List[schemas.Booking])
def read_bookings(skip: int = 0, limit: int = 100, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    return crud.get_bookings(db, skip=skip, limit=limit)

# --- АДМІНКА: ВИДАЛЕННЯ ---
@app.delete("/bookings/{booking_id}")
def delete_booking(booking_id: str, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    booking = db.query(models.Booking).filter(models.Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Бронювання не знайдено")
    if booking.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Це не ваше бронювання")

    deleted = crud.delete_booking(db, booking_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Бронювання не знайдено")
    
    # Скасовуємо нагадування при видаленні
    cancel_booking_reminders(booking_id)
    
    return {"message": "Успішно видалено"}

# --- АДМІНКА: РЕДАГУВАННЯ ---
@app.put("/bookings/{booking_id}", response_model=schemas.Booking)
def update_booking_info(booking_id: str, booking_update: schemas.BookingUpdate, background_tasks: BackgroundTasks, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    
    old_booking = db.query(models.Booking).filter(models.Booking.id == booking_id).first()
    if not old_booking:
        raise HTTPException(status_code=404, detail="Бронювання не знайдено")

    is_admin = current_user.role == "admin"
    if old_booking.user_id != current_user.id and not is_admin:
        raise HTTPException(status_code=403, detail="Це не ваше бронювання")

    old_status = old_booking.status
    # Only admins may approve or reject; otherwise a user could confirm their own long booking
    if booking_update.status is not None and booking_update.status != old_status and not is_admin:
        raise HTTPException(status_code=403, detail="Змінювати статус може лише адміністратор")

    # Re-validate the time range only if it actually changed
    new_start = booking_update.start_time or old_booking.start_time
    new_end = booking_update.end_time or old_booking.end_time
    if new_start.tzinfo:
        new_start = new_start.replace(tzinfo=None)
    if new_end.tzinfo:
        new_end = new_end.replace(tzinfo=None)
    if new_start != old_booking.start_time or new_end != old_booking.end_time:
        if new_end <= new_start:
            raise HTTPException(status_code=400, detail="Час завершення має бути пізніше часу початку!")
        if not crud.check_availability(db, old_booking.room_id, new_start, new_end, skip_booking_id=booking_id):
            raise HTTPException(status_code=409, detail="Кімната зайнята на цей час!")

    updated_booking = crud.update_booking(db, booking_id, booking_update)
    if not updated_booking:
        raise HTTPException(status_code=404, detail="Бронювання не знайдено")
    
    if booking_update.status and booking_update.status != old_status:
        user = db.query(models.User).filter(models.User.id == updated_booking.user_id).first()
        room = db.query(models.Room).filter(models.Room.id == updated_booking.room_id).first()
        
        status_text = "✅ Підтверджено" if updated_booking.status == 'confirmed' else "⛔ Відхилено"
        subject = f"Оновлення статусу бронювання: {room.name}"
        body = f"Привіт, {user.name}!\n\nСтатус вашого бронювання на {updated_booking.start_time.strftime('%d.%m.%Y %H:%M')} змінився.\n\nНовий статус: {status_text}\nКімната: {room.name}\n\nГарного дня!"
        
        background_tasks.add_task(send_email, user.email, subject, body)

        # Робота з нагадуваннями при зміні статусу
        if booking_update.status == 'confirmed':
            # Якщо адмін підтвердив - ставимо нагадування
            schedule_booking_reminders(str(updated_booking.id), user.email, user.name, room.name, updated_booking.start_time)
        elif booking_update.status == 'rejected':
            # Якщо відхилив - знімаємо будильники
            cancel_booking_reminders(str(updated_booking.id))

    return updated_booking

# ==========================================
# ANALYTICS & ML
# ==========================================

@app.get("/analytics/dashboard")
def get_dashboard_stats(db: Session = Depends(get_db), admin: models.User = Depends(require_admin)):
    return analytics.get_booking_stats(db)

@app.post("/ml/train")
def trigger_training(admin: models.User = Depends(require_admin)):
    ml_engine.train_model()
    return {"message": "Модель успішно перетренована!"}

@app.get("/ml/predict")
def predict_office_load(day: int, hour: int, current_user: models.User = Depends(get_current_user)):
    predicted_count = ml_engine.predict_load(day, hour)
    
    status = "🟢 Вільно"
    if predicted_count > 50:
        status = "🟡 Середнє навантаження"
    if predicted_count > 100:
        status = "🔴 Високе навантаження (перевантаження)"

    return {
        "day_of_week": day,
        "hour": hour,
        "predicted_bookings": predicted_count,
        "status": status
    }
