from pydantic import BaseModel, Field  # <--- ДОДАНО Field
from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID  # Імпорт для роботи з UUID

# --- USER ---
class UserBase(BaseModel):
    # <--- НОВА ЛОГІКА: Перевірка правильного формату email
    email: str = Field(..., pattern=r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")

class UserCreate(UserBase):
    name: str
    # bcrypt only uses the first 72 bytes, so cap the length
    password: str = Field(..., min_length=8, max_length=72)
    department: Optional[str] = None

class User(UserBase):
    id: UUID  # UUID для відповіді
    name: str
    role: str
    department: Optional[str] = None
    class Config:
        from_attributes = True

class LoginRequest(BaseModel):
    email: str
    password: str

# --- ROOM ---
class RoomBase(BaseModel):
    name: str
    capacity: int
    location: Optional[str] = None
    # --- НОВІ ПОЛЯ ---
    description: Optional[str] = None
    area: Optional[float] = None
    price_per_hour: Optional[float] = None

class RoomCreate(RoomBase):
    pass

class Room(RoomBase):
    id: UUID  # UUID для відповіді
    class Config:
        from_attributes = True

# --- BOOKING ---
class BookingBase(BaseModel):
    # Для вхідних даних (створення) залишаємо str, щоб не ламати логіку запису
    room_id: str  
    user_id: str
    start_time: datetime
    end_time: datetime
    services: Optional[str] = ""
    comment: Optional[str] = ""
    title: Optional[str] = "Зустріч"
    participants_count: Optional[int] = 1

class BookingCreate(BookingBase):
    pass

class BookingUpdate(BaseModel):
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    services: Optional[str] = None
    comment: Optional[str] = None
    status: Optional[Literal["pending", "confirmed", "rejected"]] = None

class Booking(BookingBase):
    id: UUID       # <--- ВАЖЛИВО: UUID
    room_id: UUID  # <--- ВАЖЛИВО: Перевизначаємо як UUID (було str в Base)
    user_id: UUID  # <--- ВАЖЛИВО: Перевизначаємо як UUID (було str в Base)
    status: str
    
    class Config:
        from_attributes = True


# --- AI ASSISTANT ---
class AssistantMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=2000)

class AssistantRequest(BaseModel):
    messages: List[AssistantMessage] = Field(..., min_length=1, max_length=12)

class AssistantProposal(BaseModel):
    room_id: str
    room_name: str
    start_time: str
    end_time: str
    title: str
    participants_count: int
    services: str
    comment: str
    requires_approval: bool

class AssistantResponse(BaseModel):
    reply: str
    proposal: Optional[AssistantProposal] = None
