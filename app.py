import streamlit as st
import gspread
import pandas as pd
import json
from datetime import datetime
import time

# =========================================================
# 1. КОНСТАНТЫ И НАСТРОЙКИ
# =========================================================

# --- ОБЯЗАТЕЛЬНО ИСПРАВИТЬ! ---
# 1. ТОЧНОЕ ИМЯ ВАШЕЙ ТАБЛИЦЫ В GOOGLE DRIVE
SPREADSHEET_NAME = "Start" 
# 2. НАЗВАНИЕ ЛИСТА ДЛЯ ЗАПИСИ ЗАЯВОК
WORKSHEET_NAME_ORDERS = "ЗАЯВКИ"
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
    """Подключается к Google Sheets API через Сервисный Аккаунт."""
    try:
        secrets = json.load(open("secrets.json"))
    except FileNotFoundError:
        st.error("Ошибка: Файл secrets.json не найден. Убедитесь, что он лежит в корне проекта.")
        return None
        
    try:
        gc = gspread.service_account_from_dict(secrets)
        return gc
    except Exception as e:
        st.error(f"Ошибка аутентификации gspread. Проверьте JSON-ключ: {e}")
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
        return pd.DataFrame()
    except gspread.exceptions.WorksheetNotFound:
        st.error("Ошибка: Лист 'ПРАЙС' не найден. Убедитесь в правильности названия.")
        return pd.DataFrame()
    except Exception as e:
        # ИСПРАВЛЕНА F-строка
        st.error(f"Неизвестная ошибка при загрузке прайса (проверьте заголовки: НАИМЕНОВАНИЕ и ЦЕНА). Ошибка: {e}")
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
        return None

# Инициализация
price_df = load_price_list()
if price_df.empty and SPREADSHEET_NAME != "CRM/ЗАЯВКИ + КАЛЬКУЛЯТОР":
    st.stop() 

orders_ws = get_orders_worksheet()
if not orders_ws and WORKSHEET_NAME_ORDERS != "ЗАЯВКИ":
    st.stop() 

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
# 4. ФОРМА ВВОДА (50-60 РЕКВИЗИТОВ)
# =========================================================

st.title("Система Управления Заявками")
st.markdown("---")

# --- ФОРМА 1: Сбор 50-60 реквизитов ---
# Используем st.form, чтобы все поля обновлялись вместе
with st.form(key='data_form'):

    # 4.1. Раздел: Основная Информация о Клиенте
    st.header("1. Основные Данные")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        client_name = st.text_input("Название Компании", key="k_client_name")
        contact_person = st.text_input("Контактное Лицо", key="k_contact_person")
        source = st.selectbox("Источник Заявки", ["Сайт", "Звонок", "Партнер", "Прочее"], key="k_source")

    with col2:
        client_email = st.text_input("Email", key="k_client_email")
        client_phone = st.text_input("Телефон", key="k_client_phone")
        status = st.selectbox("Статус Заявки", ["Новая", "В работе", "Закрыта"], key="k_status")

    with col3:
        city = st.text_input("Город/Регион", key="k_city")
        date_created = st.date_input("Дата Создания Заявки", key="k_date_created")
        priority = st.slider("Приоритет", 1, 5, 3, key="k_priority")

    st.markdown("---")

    # 4.2. Раздел: Технические Реквизиты (Разбивка по вкладкам для 50+ полей)
    tab_tech_1, tab_tech_2 = st.tabs(["2. Требования (I)", "3. Требования (II)"])

    tech_fields = {} # Словарь для сбора всех реквизитов

    with tab_tech_1:
        st.subheader("Технические Детали (Поля 1-25)")
        
        # 25 полей ввода
        for i in range(1, 26):
            # Внимание: здесь мы сохраняем данные в словарь, а не в st.session_state напрямую
            tech_fields[f'Реквизит_{i}'] = st.text_input(f"Реквизит проекта №{i}", key=f"k_req_{i}")

    with tab_tech_2:
        st.subheader("Дополнительные Требования (Поля 26-50)")
        
        # Еще 25 полей ввода
        for i in range(26, 51):
            tech_fields[f'Реквизит_{i}'] = st.text_input(f"Реквизит проекта №{i}", key=f"k_req_{i}")

    # Кнопка отправки формы 1 (просто сохраняет введенные данные в памяти Streamlit)
    st.form_submit_button("Сохранить введенные данные", type="primary")

# КОНЕЦ ФОРМЫ 1

# =========================================================
# 5. КАЛЬКУЛЯТОР (ВНЕ ФОРМ)
# =========================================================
st.markdown("---")
st.header("4. Калькулятор Стоимости Заявки")

# Кнопка для добавления новой строки в калькулятор (st.button - теперь работает!)
add_item = st.button("➕ Добавить позицию в расчет")
if add_item:
    st.session_state.calculator_items.append({"item": price_items[0], "qty": 1})
    st.rerun()

total_cost = 0

# Отображение позиций и расчет суммы
for i, item_data in enumerate(st.session_state.calculator_items):
    
    col_item, col_qty, col_price, col_remove = st.columns([4, 1, 1, 0.5])

    with col_item:
        selected_item = st.selectbox(
            f"Позиция {i}", 
            price_items, 
            index=price_items.index(item_data["item"]),
            key=f"item_{i}",
            label_visibility="collapsed"
        )
        st.session_state.calculator_items[i]["item"] = selected_item

    with col_qty:
        quantity = st.number_input(
            f"Кол-во {i}", 
            min_value=1, 
            value=item_data["qty"], 
            step=1,
            key=f"qty_{i}",
            label_visibility="collapsed"
        )
        st.session_state.calculator_items[i]["qty"] = int(quantity)
        
    cost = 0
    if selected_item != price_items[0] and not price_df.empty:
        price_row = price_df[price_df['НАИМЕНОВАНИЕ'] == selected_item]
        if not price_row.empty:
            price = price_row['ЦЕНА'].iloc[0]
            cost = price * int(quantity)
            total_cost += cost
    
    with col_price:
        st.metric(f"Стоимость {i}", f"{cost:,.0f} ₽", label_visibility="collapsed")
        
    with col_remove:
        st.text("") # Выравнивание
        if st.button("🗑️", key=f"remove_{i}"):
            st.session_state.calculator_items.pop(i)
            st.rerun() 

st.markdown("---")
st.subheader(f"ИТОГО: {total_cost:,.0f} ₽")

# =========================================================
# 6. КНОПКА ОТПРАВКИ (ФОРМА 2)
# =========================================================
st.markdown("---")

# --- ФОРМА 2: Только для записи данных в Google Sheets ---
with st.form(key='submit_form'):
    
    # Кнопка отправки формы 2
    submitted = st.form_submit_button("✅ СОХРАНИТЬ ЗАЯВКУ В ТАБЛИЦУ", use_container_width=True)

    if submitted:
        
        # 6.1. Сбор всех данных из session_state (введенные 50-60 полей)
        # Все значения берутся из ключей 'k_' в session_state, созданных в Форме 1
        
        # Проверка обязательных полей
        if not st.session_state.k_client_name or not st.session_state.k_client_phone:
            st.error("Пожалуйста, заполните поля 'Название Компании' и 'Телефон' в разделе 1.")
        else:
            # Сбор всех данных в список для записи
            all_data = [
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"), # 1. Дата/Время записи
                st.session_state.k_client_name,               # 2. Название Компании
                st.session_state.k_contact_person,            # 3. Контактное Лицо
                st.session_state.k_client_email,              # 4. Email
                st.session_state.k_client_phone,              # 5. Телефон
                st.session_state.k_city,                      # 6. Город/Регион
                st.session_state.k_date_created.strftime("%Y-%m-%d"), # 7. Дата Создания
                st.session_state.k_source,                    # 8. Источник
                st.session_state.k_status,                    # 9. Статус
                st.session_state.k_priority,                  # 10. Приоритет
                # 11-60. Добавляем 50 реквизитов
                *[st.session_state[f'k_req_{i}'] for i in range(1, 51)],
                # 61. Итоговая стоимость
                total_cost 
            ]
            
            # 6.2. Запись данных
            if save_data_to_gsheets(all_data):
                st.success("✅ Заявка успешно сохранена в Google Таблице!")
                # Очистка состояния для новой заявки
                st.session_state.calculator_items = []
                time.sleep(1) 
                st.rerun() # Перезапуск формы для новой заявки
            else:
                st.error("Произошла ошибка при записи данных. Проверьте права доступа к листу 'ЗАЯВКИ'.")

