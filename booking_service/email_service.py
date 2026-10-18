import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os

# Дані для відправки
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "your_email@gmail.com")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD", "")

def send_email(to_email: str, subject: str, body: str):
    # --- РЕЖИМ ТЕСТУВАННЯ (Вивід у консоль) ---
    if SENDER_EMAIL == "your_email@gmail.com":
        print("\n" + "="*50)
        print(f"📧 [СИСТЕМА ПОВІДОМЛЕНЬ]")
        print(f"Кому: {to_email}")
        print(f"Тема: {subject}")
        print("-" * 50)
        print(body)
        print("="*50 + "\n")
        return
        
    # --- РЕЖИМ РЕАЛЬНОЇ ВІДПРАВКИ ---
    try:
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)
        server.quit()
    except Exception as e:
        print(f"Помилка відправки листа: {e}")
