import streamlit as st
import gspread
import pandas as pd
import re
from datetime import datetime, timedelta
import urllib.parse
import time




# =========================================================
# 1. КОНСТАНТЫ И НАСТРОЙКИ
# =========================================================


# ТЕХНИЧЕСКИЙ КОММЕНТАРИЙ:
# Данные константы используются для подключения к Google Sheets.
SPREADSHEET_NAME = "Start" 
WORKSHEET_NAME_ORDERS = "ЗАЯВКИ"
# УКАЖИТЕ СВОЙ НОМЕР МЕНЕДЖЕРА (используется только для внутренних целей, не для отправки)
MANAGER_WHATSAPP_PHONE = "79000000000" 


st.set_page_config(
    page_title="CRM: Ввод Новой Заявки", 
    layout="wide",
    initial_sidebar_state="expanded"
)




# ТЕХНИЧЕСКИЙ КОММЕНТАРИЙ:
# Инициализация st.session_state критически важна для Streamlit.
if 'critical_error' not in st.session_state:
    st.session_state.critical_error = None
if 'calculator_items' not in st.session_state:
    st.session_state.calculator_items = []
if 'k_client_phone' not in st.session_state:
    st.session_state.k_client_phone = ""
if 'k_order_number' not in st.session_state:
    st.session_state.k_order_number = ""
    
# Дефолтное значение для даты - None (чтобы поле было пустым)
if 'k_delivery_date' not in st.session_state:
    st.session_state.k_delivery_date = None
    
if 'new_item_qty' not in st.session_state: 
    st.session_state['new_item_qty'] = 1 
    
# Переменная для хранения лога парсинга
if 'parsing_log' not in st.session_state:
    st.session_state.parsing_log = ""
    
# Инициализация ключа для text_area
if 'conversation_text_input' not in st.session_state:
    st.session_state.conversation_text_input = "" 
    
# Функция для записи критической ошибки
def set_critical_error(message, error_details=None):
    full_message = f"Критическая ошибка: {message}"
    if error_details:
        full_message += f"\n\nДетали: {error_details}"
    st.session_state.critical_error = full_message




# =========================================================
# 2. ФУНКЦИИ ПОДКЛЮЧЕНИЯ И КЭШИРОВАНИЯ
# =========================================================




@st.cache_resource(ttl=3600)
def get_gsheet_client():
    if "gcp_service_account" not in st.secrets:
        set_critical_error("Секрет 'gcp_service_account' не найден. Убедитесь, что он настроен в secrets.toml.")
        return None 
    try:
        gc = gspread.service_account_from_dict(st.secrets["gcp_service_account"])
        return gc
    except Exception as e:
        set_critical_error("Ошибка аутентификации gspread.", f"Ошибка: {e}")
        return None




@st.cache_data(ttl="1h")
def load_price_list():
    gc = get_gsheet_client()
    if not gc: return pd.DataFrame() 
        
    try:
        sh = gc.open(SPREADSHEET_NAME) 
        worksheet = sh.worksheet("ПРАЙС") 
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        if 'ЦЕНА' in df.columns:
            df['ЦЕНА'] = pd.to_numeric(df['ЦЕНА'], errors='coerce')
        st.info(f"✅ Прайс-лист загружен успешно. Обнаружено {len(df)} позиций.")
        return df
    except gspread.exceptions.SpreadsheetNotFound:
        set_critical_error(f"Google Таблица '{SPREADSHEET_NAME}' не найдена.")
    except gspread.exceptions.WorksheetNotFound:
        set_critical_error("Лист 'ПРАЙС' не найден. Убедитесь в правильности названия.")
    except Exception as e:
        set_critical_error("Неизвестная ошибка при загрузке прайса (проверьте заголовки).", f"Ошибка: {e}")
    return pd.DataFrame()




@st.cache_resource
def get_orders_worksheet():
    gc = get_gsheet_client()
    if not gc: return None
    try:
        sh = gc.open(SPREADSHEET_NAME) 
        return sh.worksheet(WORKSHEET_NAME_ORDERS)
    except gspread.exceptions.WorksheetNotFound:
        set_critical_error(f"Лист для заявок '{WORKSHEET_NAME_ORDERS}' не найден.")
        return None
    except Exception as e:
        set_critical_error(f"Ошибка доступа к листу '{WORKSHEET_NAME_ORDERS}'.", f"Ошибка: {e}")
        return None




# Инициализация
price_df = load_price_list() 
orders_ws = get_orders_worksheet()
price_items = ["--- Выберите позицию ---"] + price_df['НАИМЕНОВАНИЕ'].tolist()




if 'new_item_select' not in st.session_state:
    st.session_state['new_item_select'] = price_items[0]




# =========================================================
# 3. ФУНКЦИИ ЛОГИКИ (ПАРСИНГ И ЗАПИСЬ)
# =========================================================




def parse_conversation(text):
    """Базовая функция для извлечения данных из текста переписки и обновления st.session_state."""
    
    # Сброс временных состояний для чистой отладки
    st.session_state['k_client_phone'] = ""
    st.session_state['k_order_number'] = ""
    st.session_state['k_delivery_date'] = None
    # НОВОЕ: Инициализация лога
    st.session_state.parsing_log = f"--- ЛОГ ПАРСИНГА ({datetime.now().strftime('%H:%M:%S')}) ---\n"
    
    # 1. Извлечение номера телефона (Поиск по частоте)
    phone_matches = re.findall(r'(?:\+7|8|\b7)?\s*\(?\s*(\d{3})\s*\)?\s*(\d{3})[-\s]*(\d{2})[-\s]*(\d{2})', text)
    
    st.session_state.parsing_log += f"Поиск телефонов (результаты): {phone_matches}\n"
    
    if phone_matches:
        phone_counts = {}
        for match in phone_matches:
            normalized_phone = "7" + "".join(match)
            phone_counts[normalized_phone] = phone_counts.get(normalized_phone, 0) + 1
        phone = max(phone_counts.items(), key=lambda item: item[1])[0]
        st.session_state['k_client_phone'] = phone 
        st.info(f"✅ Телефон клиента найден: **{phone}**")
        st.session_state.parsing_log += f"Определен основной телефон: {phone}\n"
    else:
        st.warning("⚠️ Телефон не найден. Пожалуйста, введите вручную.")
        st.session_state.parsing_log += f"Телефон не определен.\n"




    # 2. Извлечение номера заявки
    order_match = re.search(r'(?:заявк[аи]|заказ|счет|№)\s*(\d+)', text, re.IGNORECASE)
    
    st.session_state.parsing_log += f"Поиск номера заявки (матч): {order_match.group(0) if order_match else 'None'}\n"


    if order_match:
        st.session_state['k_order_number'] = order_match.group(1)
        st.info(f"✅ Номер Заявки найден: {order_match.group(1)}")
    else:
        st.warning("⚠️ Номер заявки не найден. Пожалуйста, введите вручную.")




    # 3. Извлечение даты доставки
    delivery_date = None
    
    # ПРОВЕРКА ОТНОСИТЕЛЬНЫХ ДАТ
    relative_match = ""
    if re.search(r'послезавтра', text, re.IGNORECASE):
        delivery_date = datetime.today().date() + timedelta(days=2)
        relative_match = "послезавтра (+2 дня)"
    elif re.search(r'завтра', text, re.IGNORECASE):
        delivery_date = datetime.today().date() + timedelta(days=1)
        relative_match = "завтра (+1 день)"
    
    st.session_state.parsing_log += f"Поиск относительной даты: {relative_match or 'Нет'}\n"


    # ПРОВЕРКА КОНКРЕТНЫХ ДАТ (только если относительная дата еще не найдена)
    if not delivery_date:
        # Ищем форматы дд.мм.гггг, дд/мм/гггг, дд.мм, дд/мм
        date_match = re.search(r'(\d{1,2})[./](\d{1,2})(?:[./](\d{4}))?', text)
        
        st.session_state.parsing_log += f"Поиск конкретной даты (матч): {date_match.groups() if date_match else 'None'}\n"
        
        if date_match:
            day, month, year = date_match.groups()
            current_year = datetime.today().year
            # Если год не указан, берем текущий
            year = int(year) if year else current_year 
            try:
                delivery_date = datetime(year, int(month), int(day)).date()
            except ValueError:
                pass
    
    if delivery_date:
        # КОРРЕКТИРОВАННАЯ ЛОГИКА: Перенос даты в будущее, если она оказалась в прошлом
        today = datetime.today().date()
        
        initial_date_str = delivery_date.strftime('%d.%m.%Y')
        year_corrected = False
        
        while delivery_date < today:
            delivery_date = delivery_date.replace(year=delivery_date.year + 1)
            year_corrected = True


        if year_corrected:
            st.warning(f"⚠️ Обнаруженная дата ({initial_date_str}) была в прошлом. Год скорректирован на **{delivery_date.year}**.")
            st.session_state.parsing_log += f"Коррекция года: Исходная {initial_date_str}, Скорректирована на {delivery_date.year}\n"
            
        st.session_state['k_delivery_date'] = delivery_date
        st.info(f"✅ Дата Доставки найдена: **{delivery_date.strftime('%d.%m.%Y')}**")
    else:
        # Если ничего не найдено, устанавливаем на "завтра" (как дефолтное значение)
        tomorrow = datetime.today().date() + timedelta(days=1)
        st.session_state['k_delivery_date'] = tomorrow
        st.warning("⚠️ Дата доставки не найдена. Установлена на 'завтра'.")
        st.session_state.parsing_log += f"Дата доставки не найдена, установлена по умолчанию: {tomorrow.strftime('%d.%m.%Y')}\n"


    # ⚠️ КРИТИЧЕСКОЕ ИЗМЕНЕНИЕ: УДАЛЕНА строка st.session_state.conversation_text_input = ""
    # Сброс поля теперь выполняется в основном блоке, чтобы избежать ошибки API.




    # Перезапуск для немедленного обновления полей
    st.rerun() 




def save_data_to_gsheets(data_row):
    """Добавляет строку данных на лист ЗАЯВКИ."""
    if orders_ws is None:
        st.error("Не удалось подключиться к листу для записи данных.")
        return False
    try:
        orders_ws.append_row(data_row)
        return True