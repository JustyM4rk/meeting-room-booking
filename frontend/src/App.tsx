import React from 'react';
import { BrowserRouter as Router, Routes, Route, Link, Navigate } from 'react-router-dom';
import BookingPage from './components/BookingPage';
import AdminPanel from './components/AdminPanel';
import Login from './components/Login';
import MyBookings from './components/MyBookings';
import Register from './components/Register'; 
import Dashboard from './components/Dashboard'; // <--- ДОДАНО: Імпорт Дашборда
import axios from 'axios';

// Вказуємо Axios завжди використовувати посилання з Vercel, або локальне, якщо ми розробляємо вдома
axios.defaults.baseURL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';

// Додаємо JWT до кожного запиту
axios.interceptors.request.use((config) => {
  const userStr = localStorage.getItem('user');
  if (userStr) {
    const { access_token } = JSON.parse(userStr);
    if (access_token) {
      config.headers.Authorization = `Bearer ${access_token}`;
    }
  }
  return config;
});

// Якщо токен прострочений або недійсний (401) — повертаємо на логін
axios.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && window.location.pathname !== '/login') {
      localStorage.removeItem('user');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

// Компонент захисту маршрутів
const ProtectedRoute = ({ children, roleRequired }: { children: React.ReactNode, roleRequired?: string }) => {
  const userStr = localStorage.getItem('user');
  
  // 1. Якщо не увійшов -> на логін
  if (!userStr) {
    return <Navigate to="/login" replace />;
  }

  const user = JSON.parse(userStr);
  
  // 2. Якщо це сторінка адміна, а юзер не адмін -> на головну
  if (roleRequired && user.role !== roleRequired) {
    return <Navigate to="/booking" replace />;
  }

  return <>{children}</>;
};

function App() {
  const userStr = localStorage.getItem('user');
  const user = userStr ? JSON.parse(userStr) : null;

  const handleLogout = () => {
    localStorage.removeItem('user');
    window.location.href = '/login';
  };

  return (
    <Router>
      <div className="min-h-screen bg-gray-50">
        <nav className="bg-white shadow-md p-4 mb-4">
          <div className="max-w-7xl mx-auto flex justify-between items-center">
            <Link to="/booking" className="text-xl font-bold text-blue-600">🏢 Booking System</Link>
            
            <div className="space-x-4 flex items-center">
              {user ? (
                <>
                  <Link to="/booking" className="text-gray-600 hover:text-blue-600 font-medium">Забронювати</Link>
                  <Link to="/my-bookings" className="text-gray-600 hover:text-blue-600 font-medium">Мої зустрічі</Link>
                  
                  {/* Тільки адмін бачить ці посилання */}
                  {user.role === 'admin' && (
                    <div className="flex gap-2 border-l border-gray-300 pl-4 ml-2">
                      <Link to="/dashboard" className="text-purple-600 font-bold hover:text-purple-800 border border-purple-200 bg-purple-50 px-3 py-1 rounded transition">
                        📊 Аналітика
                      </Link>
                      <Link to="/admin" className="text-red-600 font-bold hover:text-red-800 border border-red-200 bg-red-50 px-3 py-1 rounded transition">
                        ⚙️ Адмінка
                      </Link>
                    </div>
                  )}
                  
                  <span className="text-sm bg-blue-50 text-blue-600 px-3 py-1 rounded-full font-bold ml-4">👤 {user.name}</span>
                  <button onClick={handleLogout} className="text-sm text-red-500 border border-red-500 px-3 py-1 rounded hover:bg-red-50 ml-2 transition">
                    Вийти
                  </button>
                </>
              ) : (
                <div className="space-x-2">
                  <Link to="/login" className="text-blue-600 font-medium hover:underline px-3 py-2">Увійти</Link>
                  <Link to="/register" className="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition font-bold shadow-sm">Реєстрація</Link>
                </div>
              )}
            </div>
          </div>
        </nav>

        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          
          {/* ЗАХИЩЕНІ МАРШРУТИ */}
          <Route path="/" element={<ProtectedRoute><BookingPage /></ProtectedRoute>} />
          <Route path="/booking" element={<ProtectedRoute><BookingPage /></ProtectedRoute>} />
          <Route path="/my-bookings" element={<ProtectedRoute><MyBookings /></ProtectedRoute>} />
          
          {/* ТІЛЬКИ ДЛЯ АДМІНА */}
          <Route path="/admin" element={
            <ProtectedRoute roleRequired="admin">
              <AdminPanel />
            </ProtectedRoute>
          } />
          
          {/* <--- ДОДАНО: Маршрут для Дашборда ---> */}
          <Route path="/dashboard" element={
            <ProtectedRoute roleRequired="admin">
              <Dashboard />
            </ProtectedRoute>
          } />
        </Routes>
      </div>
    </Router>
  );
}

export default App;