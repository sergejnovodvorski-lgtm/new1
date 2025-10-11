import streamlit as st
import gspread
import pandas as pd
import json
from datetime import datetime
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
# 4. БЛОК 1: ОСНОВНЫЕ ДАННЫЕ (ВВЕРХУ)
# =========================================================


st.title("Система Управления Заявками")
st.markdown("---")


# --- ФОРМА 1: Сбор основных реквизитов ---
with st.form(key='data_form_main'):


    st.header("1. Основные Данные")
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Номер Заявки
        st.text_input("Номер Заявки", key="k_order_number", 
                      value=st.session_state.get("k_order_number", ""))
        
        # Телефон
        st.text_input("Телефон клиента (для согласования)", key="k_client_phone",
                      value=st.session_state.get("k_client_phone", ""))
        
        # Источник Заявки
        source_options = ["Сайт", "Звонок", "Партнер", "Прочее"]
        source_index = source_options.index(st.session_state.get("k_source", source_options[0]))
        st.selectbox("Источник Заявки", source_options, index=source_index, key="k_source")




    with col2:
        # Статус Заявки
        status_options = ["Новая", "В работе", "Закрыта", "Согласована (Клиент)"] 
        status_index = status_options.index(st.session_state.get("k_status", status_options[0]))
        st.selectbox("Статус Заявки", status_options, index=status_index, key="k_status")
        
        # Дата Создания
        if 'k_date_created' not in st.session_state:
            st.session_state.k_date_created = datetime.today().date()
            
        st.date_input("Дата Создания Заявки", 
                      value=st.session_state.k_date_created,
                      key="k_date_created")
                      
        # ❗ НОВОЕ ПОЛЕ: Дата доставки
        if 'k_date_delivery' not in st.session_state:
             st.session_state.k_date_delivery = datetime.today().date()
        st.date_input("❗ Дата доставки", 
                      value=st.session_state.k_date_delivery,
                      key="k_date_delivery")
                                     
        # Приоритет
        st.slider("Приоритет", 1, 5, st.session_state.get("k_priority", 3), key="k_priority")


    # Форма должна быть закрыта здесь
    st.form_submit_button("Сохранить данные (Обновить форму)", type="primary")


# КОНЕЦ ФОРМЫ 1


# =========================================================
# 5. БЛОК 2: КАЛЬКУЛЯТОР СТОИМОСТИ ЗАЯВКИ
# =========================================================
st.markdown("---")
st.header("2. Калькулятор Стоимости Заявки") 


add_item = st.button("➕ Добавить позицию в расчет")
if add_item:
    st.session_state.calculator_items.append({"item": price_items[0], "qty": 1})
    st.rerun()


total_cost = 0


for i, item_data in enumerate(st.session_state.calculator_items):
    
    col_item, col_qty, col_price, col_remove = st.columns([4, 1, 1, 0.5])


    with col_item:
        index = price_items.index(item_data["item"]) if item_data["item"] in price_items else 0
        selected_item = st.selectbox(
            f"Позиция {i}", 
            price_items, 
            index=index,
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
        if not price_row.empty and 'ЦЕНА' in price_row.columns:
            try:
                price = price_row['ЦЕНА'].iloc[0]
                cost = float(price) * int(quantity)
                total_cost += cost
            except ValueError:
                 st.warning(f"Ошибка: Цена для '{selected_item}' не является числом.")
                 cost = 0
    
    with col_price:
        st.metric(f"Стоимость {i}", f"{cost:,.0f} ₽", label_visibility="collapsed")
        
    with col_remove:
        st.text("") 
        if st.button("🗑️", key=f"remove_{i}"):
            st.session_state.calculator_items.pop(i)
            st.rerun() 


st.markdown("---")
st.subheader(f"ИТОГО: {total_cost:,.0f} ₽") 


# =========================================================
# 6. БЛОК 3: КОММЕНТАРИЙ И КНОПКА ОТПРАВКИ
# =========================================================


st.header("3. Дополнительная информация")


comment = st.text_area(
    "Комментарий к заявке (достаточно большое поле)",
    key="k_comment",
    value=st.session_state.get("k_comment", ""),
    height=200 
)


st.markdown("---")


# =========================================================
# 7. НОВАЯ ЛОГИКА: СОГЛАСОВАНИЕ ЧЕРЕЗ WHATSAPP (ОБНОВЛЕНО!)
# =========================================================


def generate_whatsapp_message(total_cost):
    """Формирует текст сообщения для WhatsApp, собирая данные из session_state."""
    
    # Форматируем даты для читабельности
    date_created_str = st.session_state.k_date_created.strftime("%Y-%m-%d")
    date_delivery_str = st.session_state.k_date_delivery.strftime("%Y-%m-%d")
    
    # 1. Формируем список товаров
    items_list = []
    for item in st.session_state.calculator_items:
        if item["item"] != "--- Выберите позицию ---":
            price_row = price_df[price_df['НАИМЕНОВАНИЕ'] == item["item"]]
            # Безопасное извлечение цены
            price = price_row['ЦЕНА'].iloc[0] if not price_row.empty and 'ЦЕНА' in price_row.columns else 0
            
            cost_item = float(price) * item["qty"]
            items_list.append(f"- {item['item']} ({item['qty']} шт.) - {cost_item:,.0f} ₽")
    
    items_text = "\n".join(items_list) if items_list else "Отсутствует"
    
    # 2. Формируем основной текст сообщения
    message = f"""
*ЗАЯВКА НА СОГЛАСОВАНИЕ*
_________________________________________


*Основные реквизиты заявки:*
Номер заявки: {st.session_state.get('k_order_number', 'БЕЗ НОМЕРА')}
Телефон клиента: {st.session_state.get('k_client_phone', 'Не указан')}
Дата создания: {date_created_str}
Дата доставки: {date_delivery_str}
Источник: {st.session_state.get('k_source', 'Не указан')}
Статус: {st.session_state.get('k_status', 'Новая')}
Приоритет: {st.session_state.get('k_priority', 3)}


*Детали заказа:*
{items_text}


*ИТОГО к согласованию:* {total_cost:,.0f} ₽
_________________________________________


*Комментарий менеджера:*
{st.session_state.get('k_comment', 'Нет')}


Прошу подтвердить, что указанные параметры и итоговая сумма верны.
"""
    return message.strip()


# --- Кнопка для отправки сообщения ---
col_wa, col_save = st.columns([1, 1])


with col_wa:
    if st.button("💬 СОГЛАСОВАТЬ заявку с клиентом (WhatsApp)", type="secondary", use_container_width=True):
        
        # Проверка обязательных полей для WhatsApp
        if not st.session_state.get('k_client_phone'):
            st.error("Пожалуйста, заполните поле 'Телефон клиента' для формирования ссылки WhatsApp.")
        else:
            message_text = generate_whatsapp_message(total_cost)
            
            # Кодируем текст для URL
            encoded_message = urllib.parse.quote(message_text)
            
            # Формируем полную ссылку
            wa_link = f"https://wa.me/{st.session_state.k_client_phone}?text={encoded_message}"
            
            # ❗ Отображаем ссылку, которую можно нажать
            st.markdown(
                f'<a href="{wa_link}" target="_blank" style="display: block; width: 100%; padding: 10px; background-color: #25D366; color: white; text-align: center; text-decoration: none; border-radius: 5px; font-weight: bold;">'
                f'✅ НАЖМИТЕ ДЛЯ ПЕРЕХОДА В WHATSAPP (КЛИЕНТ: {st.session_state.k_client_phone})</a>', 
                unsafe_allow_html=True
            )
            st.info("Сообщение сформировано. Нажмите на зеленую кнопку для отправки.")




# --- ФОРМА 2: Кнопка только для сохранения данных ---
with col_save:
    # Используем Form Submit Button для сохранения данных
    with st.form(key='submit_form'):
        submitted_save = st.form_submit_button(
            "💾 СОХРАНИТЬ ЗАЯВКУ В ТАБЛИЦУ", 
            type="primary",
            use_container_width=True
        )


if 'submitted_save' in locals() and submitted_save:
        
    # Проверка обязательных полей
    if not st.session_state.get('k_order_number') and not st.session_state.get('k_client_phone'):
        st.error("Пожалуйста, заполните поле 'Номер Заявки' ИЛИ 'Телефон'.")
    else:
        # Форматирование даты
        date_to_save = st.session_state.k_date_created.strftime("%Y-%m-%d") if hasattr(st.session_state.k_date_created, 'strftime') else str(st.session_state.k_date_created)
        date_delivery_to_save = st.session_state.k_date_delivery.strftime("%Y-%m-%d") if hasattr(st.session_state.k_date_delivery, 'strftime') else str(st.session_state.k_date_delivery)


        # ❗ ОБНОВЛЕННЫЙ СПИСОК ДАННЫХ ДЛЯ GOOGLE SHEETS
        all_data = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"), # 1. Дата/Время записи
            st.session_state.get('k_order_number', ''),   # 2. Номер Заявки
            st.session_state.get('k_client_phone', ''),   # 3. Телефон
            date_to_save,                                 # 4. Дата Создания
            date_delivery_to_save,                        # 5. НОВАЯ ДАТА ДОСТАВКИ
            st.session_state.k_source,                    # 6. Источник
            st.session_state.k_status,                    # 7. Статус
            st.session_state.k_priority,                  # 8. Приоритет
            total_cost,                                   # 9. Итоговая стоимость
            st.session_state.get('k_comment', '')         # 10. Комментарий
        ]
        
        # Запись данных
        if save_data_to_gsheets(all_data):
            st.success("✅ Заявка успешно сохранена в Google Таблице!")
            
            # Очистка состояния
            for key in list(st.session_state.keys()):
                if key.startswith('k_'):
                    del st.session_state[key]
                    
            st.session_state.calculator_items = []
            time.sleep(1) 
            st.rerun() 
        else:
            st.error("Произошла ошибка при записи данных. Проверьте права доступа к листу 'ЗАЯВКИ'.")