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


print("--- 1. Начало: Установка констант ---") # LOG


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
print("--- 1. Конец: Константы установлены, конфигурация страницы задана ---") # LOG




# =========================================================
# 2. ФУНКЦИИ ПОДКЛЮЧЕНИЯ И КЭШИРОВАНИЯ
# =========================================================




@st.cache_resource(ttl=3600)
def get_gsheet_client():
    """Подключается к Google Sheets API через Сервисный Аккаунт (используя st.secrets)."""
    
    print("--- 2.1. Попытка подключения к gspread... ---") # LOG
    
    # ❗ ИСПОЛЬЗУЕМ st.secrets ВМЕСТО secrets.json
    if "gcp_service_account" not in st.secrets:
        st.error("Ошибка: Секрет 'gcp_service_account' не найден в Streamlit Secrets.")
        print("!!! ОШИБКА: Секрет 'gcp_service_account' не найден. !!!") # LOG
        st.stop() 
        
    try:
        gc = gspread.service_account_from_dict(st.secrets["gcp_service_account"])
        print("--- 2.1. Успешное подключение к gspread. ---") # LOG
        return gc
    except Exception as e:
        st.error(f"Ошибка аутентификации gspread. Проверьте содержимое секрета 'gcp_service_account'. Ошибка: {e}")
        print(f"!!! КРИТИЧЕСКАЯ ОШИБКА АУТЕНТИФИКАЦИИ gspread: {e} !!!") # LOG
        st.stop()
        return None




@st.cache_data(ttl="1h")
def load_price_list():
    """Загружает лист 'ПРАЙС' в DataFrame pandas."""
    print(f"--- 2.2. Попытка загрузки прайс-листа из: {SPREADSHEET_NAME} (лист 'ПРАЙС')... ---") # LOG
    
    gc = get_gsheet_client()
    if not gc: 
        print("!!! 2.2. Ошибка: Клиент gspread недоступен. !!!") # LOG
        return pd.DataFrame() 
        
    try:
        sh = gc.open(SPREADSHEET_NAME) 
        worksheet = sh.worksheet("ПРАЙС") 
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        
        if 'ЦЕНА' in df.columns:
            df['ЦЕНА'] = pd.to_numeric(df['ЦЕНА'], errors='coerce')
        
        st.info(f"✅ Прайс-лист загружен успешно. Обнаружено {len(df)} позиций.")
        print(f"--- 2.2. Успешно: Прайс-лист загружен. {len(df)} строк. ---") # LOG
        return df
    
    except gspread.exceptions.SpreadsheetNotFound:
        st.error(f"Ошибка: Google Таблица с именем '{SPREADSHEET_NAME}' не найдена. Проверьте название.")
        print(f"!!! 2.2. ОШИБКА: Таблица не найдена: {SPREADSHEET_NAME} !!!") # LOG
        st.stop()
    except gspread.exceptions.WorksheetNotFound:
        st.error("Ошибка: Лист 'ПРАЙС' не найден. Убедитесь в правильности названия.")
        print("!!! 2.2. ОШИБКА: Лист 'ПРАЙС' не найден. !!!") # LOG
        st.stop()
    except Exception as e:
        st.error(f"Неизвестная ошибка при загрузке прайса (проверьте заголовки: НАИМЕНОВАНИЕ и ЦЕНА). Ошибка: {e}")
        print(f"!!! 2.2. НЕИЗВЕСТНАЯ ОШИБКА ЗАГРУЗКИ ПРАЙСА: {e} !!!") # LOG
        st.stop()
        
    return pd.DataFrame()




@st.cache_resource
def get_orders_worksheet():
    """Получает объект листа для записи заявок."""
    print(f"--- 2.3. Попытка получения листа для записи заявок: '{WORKSHEET_NAME_ORDERS}'... ---") # LOG
    
    gc = get_gsheet_client()
    if not gc: return None
    try:
        sh = gc.open(SPREADSHEET_NAME) 
        worksheet = sh.worksheet(WORKSHEET_NAME_ORDERS)
        print(f"--- 2.3. Успешно: Лист '{WORKSHEET_NAME_ORDERS}' получен. ---") # LOG
        return worksheet
    except Exception as e:
        st.error(f"Ошибка доступа к листу '{WORKSHEET_NAME_ORDERS}'. Проверьте права доступа сервисного аккаунта! Ошибка: {e}")
        print(f"!!! 2.3. КРИТИЧЕСКАЯ ОШИБКА: Доступ к листу '{WORKSHEET_NAME_ORDERS}'. Ошибка: {e} !!!") # LOG
        st.stop()
        return None


# --- ЗАПУСК ИНИЦИАЛИЗАЦИИ ---


print("--- 3. Инициализация (запуск кэшированных функций) ---") # LOG


price_df = load_price_list() 
orders_ws = get_orders_worksheet()


if price_df.empty: 
    print("--- 3.1. Прайс-лист пуст. Использование заглушки. ---") # LOG
    price_items = ["--- Выберите позицию ---"]
else:
    print(f"--- 3.1. Прайс-лист содержит {len(price_df)} позиций. ---") # LOG
    price_items = ["--- Выберите позицию ---"] + price_df['НАИМЕНОВАНИЕ'].tolist()


if 'calculator_items' not in st.session_state:
    st.session_state.calculator_items = []
    print("--- 3.2. st.session_state.calculator_items инициализирован. ---") # LOG
    
print("--- 3. Конец: Инициализация завершена ---") # LOG
# =========================================================
# 3. ФУНКЦИЯ ЗАПИСИ ДАННЫХ В GOOGLE SHEETS
# =========================================================




def save_data_to_gsheets(data_row):
    """Добавляет строку данных на лист ЗАЯВКИ."""
    print(f"--- 4.1. Попытка записи строки данных: {data_row[:3]}... ---") # LOG
    if orders_ws is None:
        st.error("Не удалось подключиться к листу для записи данных.")
        print("!!! 4.1. ОШИБКА ЗАПИСИ: orders_ws is None !!!") # LOG
        return False
        
    try:
        orders_ws.append_row(data_row)
        print("--- 4.1. Успешная запись данных в Google Sheets. ---") # LOG
        return True
    except Exception as e:
        st.error(f"Ошибка записи в Google Sheets: {e}")
        print(f"!!! 4.1. ОШИБКА ЗАПИСИ в Google Sheets: {e} !!!") # LOG
        return False






# =========================================================
# 4. ФУНКЦИЯ ПАРСИНГА ПЕРЕПИСКИ
# =========================================================




def parse_conversation(text, price_items):
    """
    Базовая функция для извлечения данных из текста переписки.
    """
    print("--- 5. Начало парсинга переписки ---") # LOG
    
    # 1. Извлечение номера телефона (Поиск по частоте)
    
    phone_matches = re.findall(r'(?:\+7|8|\b7)?\s*\(?\s*(\d{3})\s*\)?\s*(\d{3})[-\s]*(\d{2})[-\s]*(\d{2})', text)
    
    if phone_matches:
        phone_counts = {}
        for match in phone_matches:
            normalized_phone = "7" + "".join(match)
            phone_counts[normalized_phone] = phone_counts.get(normalized_phone, 0) + 1
            
        most_frequent_item = max(phone_counts.items(), key=lambda item: item[1]) 
        phone = most_frequent_item[0]
        count = most_frequent_item[1]
        
        st.session_state['k_client_phone'] = phone
        st.info(f"✅ Телефон клиента (Найден {count} раз): **{phone}**")
        print(f"--- 5.1. Телефон найден: {phone} ({count} раз). ---") # LOG
    else:
        print("--- 5.1. Телефон не найден. ---") # LOG
    
    # 2. Извлечение номера заявки
    order_match = re.search(r'(?:заявк[аи]|заказ|счет|№)\s*(\d+)', text, re.IGNORECASE)
    if order_match:
        st.session_state['k_order_number'] = order_match.group(1)
        st.info(f"✅ Номер Заявки: {order_match.group(1)}")
        print(f"--- 5.2. Номер заявки найден: {order_match.group(1)}. ---") # LOG
    else:
        print("--- 5.2. Номер заявки не найден. ---") # LOG
        
    # 3. Извлечение даты доставки
    delivery_date = None
    if re.search(r'достав[итье]|нужно\s*к|дата\s*доставк[и]', text, re.IGNORECASE):
        print("--- 5.3. Обнаружено ключевое слово даты доставки. ---") # LOG
        if re.search(r'завтра', text, re.IGNORECASE):
            delivery_date = datetime.today().date() + timedelta(days=1)
        elif re.search(r'послезавтра', text, re.IGNORECASE):
            delivery_date = datetime.today().date() + timedelta(days=2)
        else:
            date_match = re.search(r'(\d{1,2})[./](\d{1,2})(?:[./](\d{4}))?', text)
            if date_match:
                day, month, year = date_match.groups()
                year = year if year else str