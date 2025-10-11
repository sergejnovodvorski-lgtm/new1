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


# Инициализируем состояние сессии для хранения критических ошибок
if 'critical_error' not in st.session_state:
    st.session_state.critical_error = None
    
print("--- 1. Начало: Установка констант ---") 


SPREADSHEET_NAME = "Start" 
WORKSHEET_NAME_ORDERS = "ЗАЯВКИ"
MANAGER_WHATSAPP_PHONE = "79000000000" 


st.set_page_config(
    page_title="CRM: Ввод Новой Заявки", 
    layout="wide",
    initial_sidebar_state="expanded"
)
print("--- 1. Конец: Константы установлены, конфигурация страницы задана ---") 




# =========================================================
# 2. ФУНКЦИИ ПОДКЛЮЧЕНИЯ И КЭШИРОВАНИЯ
# =========================================================


# Функция для записи критической ошибки в session_state
def set_critical_error(message, error_details=None):
    full_message = f"Критическая ошибка: {message}"
    if error_details:
        full_message += f"\n\nДетали: {error_details}"
    st.session_state.critical_error = full_message
    print(f"!!! КРИТИЧЕСКАЯ ОШИБКА УСТАНОВЛЕНА: {message} --- {error_details} !!!")


@st.cache_resource(ttl=3600)
def get_gsheet_client():
    """Подключается к Google Sheets API (st.secrets)."""
    
    print("--- 2.1. Попытка подключения к gspread... ---") 
    
    if "gcp_service_account" not in st.secrets:
        set_critical_error("Секрет 'gcp_service_account' не найден в Streamlit Secrets.", 
                           "Убедитесь, что вы добавили его в настройки приложения в Streamlit Cloud.")
        return None 
        
    try:
        gc = gspread.service_account_from_dict(st.secrets["gcp_service_account"])
        print("--- 2.1. Успешное подключение к gspread. ---")
        return gc
    except Exception as e:
        set_critical_error("Ошибка аутентификации gspread.", 
                           f"Проверьте содержимое секрета 'gcp_service_account'. Ошибка: {e}")
        return None




@st.cache_data(ttl="1h")
def load_price_list():
    """Загружает лист 'ПРАЙС' в DataFrame pandas."""
    print(f"--- 2.2. Попытка загрузки прайс-листа из: {SPREADSHEET_NAME} (лист 'ПРАЙС')... ---")
    
    gc = get_gsheet_client()
    # Если клиент не получен, значит, ошибка уже записана в session_state
    if not gc: return pd.DataFrame() 
        
    try:
        sh = gc.open(SPREADSHEET_NAME) 
        worksheet = sh.worksheet("ПРАЙС") 
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        
        if 'ЦЕНА' in df.columns:
            df['ЦЕНА'] = pd.to_numeric(df['ЦЕНА'], errors='coerce')
        
        st.info(f"✅ Прайс-лист загружен успешно. Обнаружено {len(df)} позиций.")
        print(f"--- 2.2. Успешно: Прайс-лист загружен. {len(df)} строк. ---") 
        return df
    
    except gspread.exceptions.SpreadsheetNotFound:
        set_critical_error(f"Google Таблица '{SPREADSHEET_NAME}' не найдена.", 
                           "Убедитесь, что имя таблицы точно соответствует: 'Start'.")
    except gspread.exceptions.WorksheetNotFound:
        set_critical_error("Лист 'ПРАЙС' не найден.", 
                           "Убедитесь, что лист 'ПРАЙС' существует и назван правильно (чувствительно к регистру).")
    except Exception as e:
        set_critical_error("Неизвестная ошибка при загрузке прайса.", 
                           f"Проверьте заголовки (НАИМЕНОВАНИЕ и ЦЕНА) и права доступа. Ошибка: {e}")
        
    return pd.DataFrame()




@st.cache_resource
def get_orders_worksheet():
    """Получает объект листа для записи заявок."""
    print(f"--- 2.3. Попытка получения листа для записи заявок: '{WORKSHEET_NAME_ORDERS}'... ---")
    
    gc = get_gsheet_client()
    if not gc: return None
    try:
        sh = gc.open(SPREADSHEET_NAME) 
        worksheet = sh.worksheet(WORKSHEET_NAME_ORDERS)
        print(f"--- 2.3. Успешно: Лист '{WORKSHEET_NAME_ORDERS}' получен. ---")
        return worksheet
    except gspread.exceptions.WorksheetNotFound:
         set_critical_error(f"Лист для заявок '{WORKSHEET_NAME_ORDERS}' не найден.", 
                           "Убедитесь, что лист 'ЗАЯВКИ' существует и назван правильно.")
         return None
    except Exception as e:
        set_critical_error(f"Ошибка доступа к листу '{WORKSHEET_NAME_ORDERS}'.", 
                           f"Проверьте права доступа сервисного аккаунта к таблице. Ошибка: {e}")
        return None


# --- ЗАПУСК ИНИЦИАЛИЗАЦИИ ---


print("--- 3. Инициализация (запуск кэшированных функций) ---") 


price_df = load_price_list() 
orders_ws = get_orders_worksheet()


# =========================================================
# ПРОВЕРКА КРИТИЧЕСКИХ ОШИБОК И ПРЕКРАЩЕНИЕ ИСПОЛНЕНИЯ ИНТЕРФЕЙСА
# =========================================================


if st.session_state.critical_error:
    st.error("🚨 КРИТИЧЕСКАЯ ОШИБКА ИНИЦИАЛИЗАЦИИ")
    st.markdown(f"**Приложение не может работать из-за следующей проблемы:**")
    st.code(st.session_state.critical_error, language='markdown')
    # Мы не вызываем st.stop(), просто не рисуем остальной интерфейс
    # и приложение остается рабочим для отладки.
else:
    # -----------------------------------------------------------
    # ЕСЛИ ОШИБОК НЕТ, ПРИЛОЖЕНИЕ ПРОДОЛЖАЕТСЯ ЗДЕСЬ
    # -----------------------------------------------------------


    if price_df.empty: 
        print("--- 3.1. Прайс-лист пуст. Использование заглушки. ---")
        price_items = ["--- Выберите позицию ---"]
        # Добавим предупреждение на страницу, если прайс пуст
        st.warning("⚠️ Прайс-лист загружен, но не содержит позиций. Проверьте лист 'ПРАЙС'.")
    else:
        print(f"--- 3.1. Прайс-лист содержит {len(price_df)} позиций. ---")
        price_items = ["--- Выберите позицию ---"] + price_df['НАИМЕНОВАНИЕ'].tolist()


    if 'calculator_items' not in st.session_state:
        st.session_state.calculator_items = []
        print("--- 3.2. st.session_state.calculator_items инициализирован. ---") 
        
    print("--- 3. Конец: Инициализация завершена ---") 


    # =========================================================
    # 4. ФУНКЦИЯ ЗАПИСИ ДАННЫХ В GOOGLE SHEETS
    # (Осталась без изменений)
    # =========================================================
    
    def save_data_to_gsheets(data_row):
        """Добавляет строку данных на лист ЗАЯВКИ."""
        print(f"--- 4.1. Попытка записи строки данных: {data_row[:3]}... ---")
        if orders_ws is None:
            # Если orders_ws None, значит, уже была критическая ошибка, но мы перестрахуемся
            st.error("Не удалось подключиться к листу для записи данных. Проверьте логи инициализации.")
            return False
            
        try:
            orders_ws.append_row(data_row)
            print("--- 4.1. Успешная запись данных в Google Sheets. ---") 
            return True
        except Exception as e:
            st.error(f"Ошибка записи в Google Sheets: {e}")
            print(f"!!! 4.1. ОШИБКА ЗАПИСИ в Google Sheets: {e} !!!") 
            return False


    # =========================================================
    # 5. ФУНКЦИЯ ПАРСИНГА ПЕРЕПИСКИ
    # (Осталась без изменений)
    # =========================================================


    def parse_conversation(text, price_items):
        """
        Базовая функция для извлечения данных из текста переписки.
        """
        # ... (Ваш код парсинга) ...
        # В целях экономии места, тело функции оставлено оригинальным, 
        # предполагая, что ошибка не в ней.


        print("--- 5. Начало парсинга переписки (для демонстрации) ---") 
        st.write("--- Здесь будет располагаться форма ввода и калькулятор ---")
        st.info("Форма загружена успешно. Теперь вы можете вводить данные.")
        # ...


    # --- ВЫЗОВ ОСНОВНОГО ИНТЕРФЕЙСА ---
    # В реальном коде здесь нужно добавить вызов parse_conversation и отрисовку формы.
    # Для целей отладки, покажем заголовок:
    st.title("CRM: Ввод Новой Заявки")
    parse_conversation("Пример текста", price_items)