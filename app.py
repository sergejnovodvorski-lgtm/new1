import streamlit as st
import gspread
import pandas as pd
import json
import re 
from datetime import datetime, timedelta
import time
import urllib.parse 


# =========================================================
# 1. КОНСТАНТЫ И НАСТРОЙКИ
# =========================================================


# --- ОБЯЗАТЕЛЬНО ИСПРАВИТЬ! ---
SPREADSHEET_NAME = "Start" 
WORKSHEET_NAME_ORDERS = "ЗАЯВКИ"


# ❗ НОМЕР ТЕЛЕФОНА (WhatsApp) ВАШЕГО МЕНЕДЖЕРА/ОТДЕЛЯ, КУДА БУДЕТ ОТПРАВЛЯТЬСЯ ССЫЛКА
MANAGER_WHATSAPP_PHONE = "79000000000" 
# ------------------------------


st.set_page_config(
    page_title="CRM: Ввод Новой Заявки", 
    layout="wide",
    initial_sidebar_state="expanded"
)


# =========================================================
# 2. ФУНКЦИИ ПОДКЛЮЧЕНИЯ И КЭШИРОВАНИЯ
# =========================================================


@st.cache_resource(ttl=3600)
def get_gsheet_client():
    """Подключается к Google Sheets API через Сервисный Аккаунт (используя st.secrets)."""
    
    # ❗ ИСПОЛЬЗУЕМ st.secrets ВМЕСТО secrets.json
    if "gcp_service_account" not in st.secrets:
        st.error("Ошибка: Секрет 'gcp_service_account' не найден в Streamlit Secrets.")
        st.stop() 
        
    try:
        gc = gspread.service_account_from_dict(st.secrets["gcp_service_account"])
        return gc
    except Exception as e:
        st.error(f"Ошибка аутентификации gspread. Проверьте содержимое секрета 'gcp_service_account'. Ошибка: {e}")
        st.stop()
        return None


@st.cache_data(ttl="1h")
def load_price_list():
    """Загружает лист 'ПРАЙС' в DataFrame pandas."""
    gc = get_gsheet_client()
    if not gc: return pd.DataFrame() 
        
    try:
        sh = gc.open(SPREADSHEET_NAME) 
        worksheet = sh.worksheet("ПРАЙС") 
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        
        if 'ЦЕНА' in df.columns:
            df['ЦЕНА'] = pd.to_numeric(df['ЦЕНА'], errors='coerce')
        
        return df
    
    except gspread.exceptions.SpreadsheetNotFound:
        st.error(f"Ошибка: Google Таблица с именем '{SPREADSHEET_NAME}' не найдена. Проверьте название.")
        st.stop()
    except gspread.exceptions.WorksheetNotFound:
        st.error("Ошибка: Лист 'ПРАЙС' не найден. Убедитесь в правильности названия.")
        st.stop()
    except Exception as e:
        st.error(f"Неизвестная ошибка при загрузке прайса (проверьте заголовки: НАИМЕНОВАНИЕ и ЦЕНА). Ошибка: {e}")
        st.stop()
        
    return pd.DataFrame()


@st.cache_resource
def get_orders_worksheet():
    """Получает объект листа для записи заявок."""
    gc = get_gsheet_client()
    if not gc: return None
    try:
        sh = gc.open(SPREADSHEET_NAME) 
        return sh.worksheet(WORKSHEET_NAME_ORDERS)
    except Exception as e:
        st.error(f"Ошибка доступа к листу '{WORKSHEET_NAME_ORDERS}'. Проверьте права доступа сервисного аккаунта! Ошибка: {e}")
        st.stop()
        return None


# Инициализация
price_df = load_price_list() 
orders_ws = get_orders_worksheet()


if price_df.empty: 
    price_items = ["--- Выберите позицию ---"]
else:
    price_items = ["--- Выберите позицию ---"] + price_df['НАИМЕНОВАНИЕ'].tolist()


if 'calculator_items' not in st.session_state:
    st.session_state.calculator_items = []
    
# =========================================================
# 3. ФУНКЦИЯ ЗАПИСИ ДАННЫХ В GOOGLE SHEETS
# =========================================================


def save_data_to_gsheets(data_row):
    """Добавляет строку данных на лист ЗАЯВКИ."""
    if orders_ws is None:
        st.error("Не удалось подключиться к листу для записи данных.")
        return False
        
    try:
        orders_ws.append_row(data_row)
        return True
    except Exception as e:
        st.error(f"Ошибка записи в Google Sheets: {e}")
        return False




# =========================================================
# 4. ФУНКЦИЯ ПАРСИНГА ПЕРЕПИСКИ
# =========================================================


def parse_conversation(text, price_items):
    """
    Базовая функция для извлечения данных из текста переписки.
    """
    
    # 1. Извлечение номера телефона (Поиск по частоте)
    
    # Ищем все возможные 10-значные номера, окруженные префиксами (+7, 8, 7) и разделителями
    phone_matches = re.findall(r'(?:\+7|8|\b7)?\s*\(?\s*(\d{3})\s*\)?\s*(\d{3})[-\s]*(\d{2})[-\s]*(\d{2})', text)
    
    if phone_matches:
        phone_counts = {}
        for match in phone_matches:
            # Нормализуем найденный номер до формата 7ХХХХХХХХХХ
            normalized_phone = "7" + "".join(match)
            
            # Считаем частоту
            phone_counts[normalized_phone] = phone_counts.get(normalized_phone, 0) + 1
            
        # Находим самый часто встречающийся номер (берем первый элемент кортежа - сам номер)
        most_frequent_item = max(phone_counts.items(), key=lambda item: item[1]) 
        phone = most_frequent_item[0]
        count = most_frequent_item[1]
        
        st.session_state['k_client_phone'] = phone
        st.info(f"✅ Телефон клиента (Найден {count} раз): **{phone}**")
    
    # 2. Извлечение номера заявки
    order_match = re.search(r'(?:заявк[аи]|заказ|счет|№)\s*(\d+)', text, re.IGNORECASE)
    if order_match:
        st.session_state['k_order_number'] = order_match.group(1)
        st.info(f"✅ Номер Заявки: {order_match.group(1)}")
        
    # 3. Извлечение даты доставки
    delivery_date = None
    if re.search(r'достав[итье]|нужно\s*к|дата\s*доставк[и]', text, re.IGNORECASE):
        if re.search(r'завтра', text, re.IGNORECASE):
            delivery_date = datetime.today().date() + timedelta(days=1)
        elif re.search(r'послезавтра', text, re.IGNORECASE):
            delivery_date = datetime.today().date() + timedelta(days=2)
        else:
             # Попытка найти формат ДД.ММ.ГГГГ или ДД.ММ
            date_match = re.search(r'(\d{1,2})[./](\d{1,2})(?:[./](\d{4}))?', text)
            if date_match:
                day, month, year = date_match.groups()
                year = year if year else str